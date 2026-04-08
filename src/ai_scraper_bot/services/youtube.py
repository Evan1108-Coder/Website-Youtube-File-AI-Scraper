from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import random
import re
from time import monotonic
from urllib.parse import parse_qs, urlparse

import httpx
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api._errors import CouldNotRetrieveTranscript, VideoUnavailable
import yt_dlp
from yt_dlp.utils import DownloadError

from ai_scraper_bot.config import Settings
from ai_scraper_bot.models import ExtractedContent
from ai_scraper_bot.services.downsub import DownSubTranscriptError, DownSubTranscriptService
from ai_scraper_bot.services.savesubs import SaveSubsTranscriptError, SaveSubsTranscriptService
from ai_scraper_bot.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)


class YouTubeExtractionError(RuntimeError):
    pass


class _CachedYouTubeResult:
    __slots__ = ("extracted", "expires_at")

    def __init__(self, extracted: ExtractedContent, expires_at: float) -> None:
        self.extracted = extracted
        self.expires_at = expires_at


class YouTubeService:
    def __init__(self, settings: Settings, transcription_service: TranscriptionService) -> None:
        self.settings = settings
        self.transcription_service = transcription_service
        self.transcript_api = YouTubeTranscriptApi()
        self.downsub_service = DownSubTranscriptService(
            settings.youtube_downsub_timeout_seconds,
            headless=settings.youtube_transcript_site_headless,
            browser_channel=settings.youtube_transcript_site_browser_channel,
        )
        self.savesubs_service = SaveSubsTranscriptService(
            settings.youtube_savesubs_timeout_seconds,
            headless=settings.youtube_transcript_site_headless,
            browser_channel=settings.youtube_transcript_site_browser_channel,
        )
        self._yt_dlp_lock = asyncio.Lock()
        self._next_yt_dlp_attempt_at = 0.0
        self._auth_gated_videos: dict[str, float] = {}
        self._auth_gate_counts: dict[str, int] = {}
        self._global_auth_gate_count = 0
        self._global_auth_gate_until = 0.0
        self._result_cache: dict[str, _CachedYouTubeResult] = {}
        self._title_cache: dict[str, tuple[dict[str, str], float]] = {}
        self._cookie_warning_emitted = False

    async def extract(self, url: str) -> ExtractedContent:
        video_id = _extract_video_id(url)
        cookie_alert = self._cookie_alert_message()
        cached = self._get_cached_result(video_id)
        if cached is not None:
            logger.info("YouTube cache hit for %s", video_id)
            return cached
        video_metadata = await self._get_video_metadata(url, video_id)
        title = video_metadata["title"]
        issues: list[str] = [cookie_alert] if cookie_alert else []
        reviewed_media = ["YouTube Data API metadata"]

        logger.info("YouTube extract start: video_id=%s url=%s", video_id, url)
        transcript, transcript_issue = await self._get_transcript_from_youtube(video_id)
        reviewed_media.append("youtube-transcript-api transcript attempt")
        if transcript:
            logger.info("YouTube transcript tier succeeded with youtube-transcript-api for %s", video_id)
            extracted = self._build_extracted_content(
                title=title,
                url=url,
                body=transcript,
                tier="youtube-transcript-api",
                metadata=video_metadata,
                issues=issues,
                reviewed_media=reviewed_media,
                has_timestamps=True,
            )
            self._cache_result(video_id, extracted)
            return extracted
        if transcript_issue:
            issues.append(transcript_issue)

        try:
            transcript = await self._get_transcript_from_ytdlp(url, video_id)
        except YouTubeExtractionError as exc:
            issues.append(str(exc))
            transcript = None
        reviewed_media.append("yt-dlp subtitle attempt")
        if transcript:
            logger.info("YouTube transcript tier succeeded with yt-dlp subtitles for %s", video_id)
            extracted = self._build_extracted_content(
                title=title,
                url=url,
                body=transcript,
                tier="yt-dlp",
                metadata=video_metadata,
                issues=issues,
                reviewed_media=reviewed_media,
                has_timestamps=True,
            )
            self._cache_result(video_id, extracted)
            return extracted
        if not any("yt-dlp" in issue.lower() for issue in issues):
            issues.append(
                f"yt-dlp did not return a usable subtitle track within {max(1, self.settings.youtube_ytdlp_timeout_seconds)} second(s)."
            )

        transcript = await self._get_transcript_from_downsub(url, issues)
        reviewed_media.append("DownSub transcript-site fallback")
        if transcript:
            logger.info("YouTube transcript tier succeeded with DownSub fallback for %s", video_id)
            extracted = self._build_extracted_content(
                title=title,
                url=url,
                body=transcript,
                tier="downsub-playwright",
                metadata=video_metadata,
                issues=issues,
                reviewed_media=reviewed_media,
            )
            self._cache_result(video_id, extracted)
            return extracted

        transcript = await self._get_transcript_from_savesubs(url, issues)
        reviewed_media.append("SaveSubs transcript-site fallback")
        if transcript:
            logger.info("YouTube transcript tier succeeded with SaveSubs fallback for %s", video_id)
            extracted = self._build_extracted_content(
                title=title,
                url=url,
                body=transcript,
                tier="savesubs-playwright",
                metadata=video_metadata,
                issues=issues,
                reviewed_media=reviewed_media,
            )
            self._cache_result(video_id, extracted)
            return extracted

        extracted = self._build_extracted_content(
            title=title,
            url=url,
            body=_metadata_fallback_body(video_metadata, issues),
            tier="metadata-fallback",
            metadata=video_metadata,
            issues=issues
            + [
                "Transcript extraction failed across youtube-transcript-api, yt-dlp, DownSub, and SaveSubs. Returning YouTube metadata instead of a dead-end error."
            ],
            reviewed_media=reviewed_media,
        )
        self._cache_result(video_id, extracted)
        return extracted

    def _build_extracted_content(
        self,
        *,
        title: str,
        url: str,
        body: str,
        tier: str,
        metadata: dict[str, str],
        issues: list[str],
        reviewed_media: list[str],
        has_timestamps: bool = False,
    ) -> ExtractedContent:
        merged_metadata = {
            "type": "youtube",
            "tier": tier,
            "youtube_attempt_order": "youtube-transcript-api -> yt-dlp -> DownSub -> SaveSubs -> metadata-fallback",
            "youtube_success_path": tier,
            **metadata,
        }
        if has_timestamps:
            merged_metadata["has_timestamps"] = "true"
        return ExtractedContent(
            title=title,
            body=body,
            source_label=url,
            metadata=merged_metadata,
            issues=list(dict.fromkeys(issue for issue in issues if issue)),
            reviewed_media=list(dict.fromkeys(reviewed_media)),
            related_urls=[url],
        )

    async def _get_video_metadata(self, url: str, video_id: str) -> dict[str, str]:
        cached = self._title_cache.get(url)
        now = monotonic()
        if cached and now < cached[1]:
            return dict(cached[0])

        if self.settings.youtube_data_api_key:
            metadata = await self._get_video_metadata_from_api(video_id)
            if metadata:
                self._title_cache[url] = (metadata, now + 3600)
                return dict(metadata)

        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            try:
                response = await client.get(
                    "https://www.youtube.com/oembed",
                    params={"url": url, "format": "json"},
                )
                response.raise_for_status()
                title = response.json().get("title") or "YouTube Video"
                metadata = {
                    "title": title,
                    "video_id": video_id,
                    "youtube_metadata_source": "youtube-oembed",
                }
                self._title_cache[url] = (metadata, now + 3600)
                return dict(metadata)
            except Exception:
                logger.info("YouTube oEmbed title lookup failed for %s; using fallback title.", url)
        return {
            "title": "YouTube Video",
            "video_id": video_id,
            "youtube_metadata_source": "youtube-fallback-title",
        }

    async def _get_video_metadata_from_api(self, video_id: str) -> dict[str, str] | None:
        params = {
            "part": "snippet,contentDetails",
            "id": video_id,
            "key": self.settings.youtube_data_api_key,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            try:
                response = await client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params=params,
                )
                response.raise_for_status()
                items = response.json().get("items") or []
                if not items:
                    return None
                item = items[0]
                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})
                title = str(snippet.get("title") or "YouTube Video")
                metadata: dict[str, str] = {
                    "title": title,
                    "video_id": video_id,
                    "youtube_metadata_source": "youtube-data-api",
                }
                channel_title = str(snippet.get("channelTitle") or "").strip()
                published_at = str(snippet.get("publishedAt") or "").strip()
                duration_iso = str(content_details.get("duration") or "").strip()
                if channel_title:
                    metadata["channel_title"] = channel_title
                if published_at:
                    metadata["published_at"] = published_at
                if duration_iso:
                    metadata["duration"] = _format_iso8601_duration(duration_iso)
                description = str(snippet.get("description") or "").strip()
                if description:
                    metadata["description"] = description[:4000]
                return metadata
            except Exception as exc:
                logger.info("YouTube Data API lookup failed for %s: %s", video_id, exc)
                return None

    async def _get_transcript_from_youtube(self, video_id: str) -> tuple[str | None, str | None]:
        try:
            timeout = max(1, self.settings.youtube_transcript_api_timeout_seconds)
            transcript_list = await asyncio.wait_for(
                asyncio.to_thread(self.transcript_api.list, video_id),
                timeout=timeout,
            )
            transcript = await asyncio.wait_for(
                asyncio.to_thread(_fetch_best_transcript, transcript_list),
                timeout=timeout,
            )
        except (
            NoTranscriptFound,
            TranscriptsDisabled,
            CouldNotRetrieveTranscript,
            VideoUnavailable,
        ):
            return None, (
                "youtube-transcript-api did not return a public transcript. The video may not expose captions, "
                "or YouTube may have refused transcript retrieval on this network path."
            )
        except asyncio.TimeoutError:
            logger.info("youtube-transcript-api timed out for %s", video_id)
            return None, (
                f"youtube-transcript-api did not finish within {max(1, self.settings.youtube_transcript_api_timeout_seconds)} second(s)."
            )
        except Exception as exc:
            logger.warning("youtube-transcript-api failed for %s: %s", video_id, exc)
            return None, f"youtube-transcript-api failed unexpectedly: {exc}"
        return (
            _transcript_items_to_text(
                transcript,
                window_seconds=self.settings.youtube_transcript_window_seconds,
            ),
            None,
        )

    async def _get_transcript_from_ytdlp(self, url: str, video_id: str) -> str | None:
        await self._guard_yt_dlp_attempt(video_id)
        output_template = str(self.settings.downloads_dir / "%(id)s.%(ext)s")
        options = self._yt_dlp_base_options()
        options.update({
            "quiet": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-US", "en-GB", "zh-Hans", "zh-Hant", "zh", "all"],
            "outtmpl": output_template,
        })
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(self._extract_info, url, options),
                timeout=max(1, self.settings.youtube_ytdlp_timeout_seconds),
            )
        except DownloadError as exc:
            if _looks_like_youtube_auth_gate(str(exc)):
                self._mark_auth_gate(video_id)
                raise YouTubeExtractionError(_youtube_auth_gate_message(self.settings)) from exc
            logger.warning("yt-dlp subtitle extraction failed for %s: %s", url, exc)
            return None
        except asyncio.TimeoutError:
            logger.info("yt-dlp subtitle extraction timed out for %s", url)
            return None
        except Exception as exc:
            logger.warning("yt-dlp subtitle extraction failed for %s: %s", url, exc)
            return None
        requested = info.get("requested_subtitles") or info.get("subtitles") or {}
        for subtitle in requested.values():
            candidates = subtitle if isinstance(subtitle, list) else [subtitle]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                subtitle_url = candidate.get("url")
                if subtitle_url:
                    return await self._download_text(subtitle_url)
        return None

    async def _get_transcript_from_downloaded_audio(
        self,
        url: str,
        video_id: str,
        issues: list[str],
    ) -> str | None:
        try:
            media_path = await self._download_audio(url, video_id)
        except YouTubeExtractionError as exc:
            issues.append(str(exc))
            return None

        try:
            duration_minutes = await self.transcription_service.probe_duration_minutes(media_path)
            return await self.transcription_service.transcribe_media(media_path, duration_minutes)
        except Exception as exc:
            issues.append(f"Audio download succeeded, but transcription failed: {exc}")
            return None
        finally:
            await asyncio.to_thread(media_path.unlink, True)

    async def _get_transcript_from_downsub(self, url: str, issues: list[str]) -> str | None:
        if not self.settings.youtube_downsub_enabled:
            issues.append("DownSub fallback is disabled in configuration.")
            return None
        try:
            transcript = await self.downsub_service.fetch_transcript(url)
        except DownSubTranscriptError as exc:
            issues.append(f"DownSub fallback failed or timed out: {exc}")
            return None
        except Exception as exc:
            issues.append(f"DownSub fallback failed unexpectedly: {exc}")
            return None
        if transcript:
            return transcript
        issues.append("DownSub fallback did not return a usable transcript.")
        return None

    async def _get_transcript_from_savesubs(self, url: str, issues: list[str]) -> str | None:
        if not self.settings.youtube_savesubs_enabled:
            issues.append("SaveSubs fallback is disabled in configuration.")
            return None
        try:
            transcript = await self.savesubs_service.fetch_transcript(url)
        except SaveSubsTranscriptError as exc:
            issues.append(f"SaveSubs fallback failed or timed out: {exc}")
            return None
        except Exception as exc:
            issues.append(f"SaveSubs fallback failed unexpectedly: {exc}")
            return None
        if transcript:
            return transcript
        issues.append("SaveSubs fallback did not return a usable transcript.")
        return None

    async def _download_audio(self, url: str, video_id: str) -> Path:
        await self._guard_yt_dlp_attempt(video_id)
        output_template = str(self.settings.downloads_dir / "%(id)s.%(ext)s")
        options = self._yt_dlp_base_options()
        options.update({
            "format": "bestaudio/best",
            "outtmpl": output_template,
        })
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(self._extract_info, url, options),
                timeout=120,
            )
        except DownloadError as exc:
            if _looks_like_js_runtime_issue(str(exc)):
                raise YouTubeExtractionError(
                    "YouTube extraction needs a JavaScript runtime on this machine. "
                    "Install Node.js or Deno, then try again."
                ) from exc
            if _looks_like_youtube_auth_gate(str(exc)):
                self._mark_auth_gate(video_id)
                raise YouTubeExtractionError(_youtube_auth_gate_message(self.settings)) from exc
            raise YouTubeExtractionError(f"yt-dlp could not download the YouTube audio: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise YouTubeExtractionError(
                "YouTube download took too long and was stopped. Please try again."
            ) from exc
        except Exception as exc:
            raise YouTubeExtractionError(f"YouTube extraction failed: {exc}") from exc
        path = Path(yt_dlp.YoutubeDL(options).prepare_filename(info))
        if not path.exists():
            raise YouTubeExtractionError("yt-dlp did not produce a downloadable media file.")
        return path

    async def _download_text(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
            response = await client.get(url)
            response.raise_for_status()
        return _subtitle_text_to_timestamped_transcript(
            response.text,
            window_seconds=self.settings.youtube_transcript_window_seconds,
        )

    def _yt_dlp_base_options(self) -> dict:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 1,
            "logger": _YTDLPLogger(),
            "sleep_interval": max(0, self.settings.youtube_sleep_interval_seconds),
            "max_sleep_interval": max(
                max(0, self.settings.youtube_sleep_interval_seconds),
                self.settings.youtube_max_sleep_interval_seconds,
            ),
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                }
            },
        }
        cookiefile, cookiesfrombrowser = self._safe_cookie_options()
        if cookiefile:
            options["cookiefile"] = cookiefile
        elif cookiesfrombrowser:
            options["cookiesfrombrowser"] = cookiesfrombrowser
        return options

    async def _guard_yt_dlp_attempt(self, video_id: str) -> None:
        now = monotonic()
        if self._global_auth_gate_until and now < self._global_auth_gate_until:
            remaining_minutes = max(1, int((self._global_auth_gate_until - now) / 60))
            raise YouTubeExtractionError(
                "The bot recently hit YouTube's anti-bot gate multiple times across videos, "
                f"so it is in a global cooldown for about {remaining_minutes} more minute(s). "
                "This protects the current network path from repeated blocked requests. "
                "For now, the safest fallback is transcript-only content, direct upload, or waiting for the cooldown to expire."
            )
        blocked_until = self._auth_gated_videos.get(video_id)
        if blocked_until and now < blocked_until:
            remaining_minutes = max(1, int((blocked_until - now) / 60))
            raise YouTubeExtractionError(
                "This video recently triggered YouTube's anti-bot gate, so I'm pausing automatic retries "
                f"for about {remaining_minutes} more minute(s) to reduce repeated blocked requests. "
                "Without cookies, the safest fallback is to upload the video or audio directly, or try another public video."
            )

        async with self._yt_dlp_lock:
            now = monotonic()
            wait_seconds = self._next_yt_dlp_attempt_at - now
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            jitter_floor = max(0, self.settings.youtube_sleep_interval_seconds)
            jitter_ceiling = max(
                jitter_floor,
                self.settings.youtube_max_sleep_interval_seconds,
            )
            if jitter_ceiling > 0:
                await asyncio.sleep(random.uniform(jitter_floor, jitter_ceiling))
            self._next_yt_dlp_attempt_at = (
                monotonic() + max(0, self.settings.youtube_min_request_interval_seconds)
            )

    def _mark_auth_gate(self, video_id: str) -> None:
        self._auth_gate_counts[video_id] = self._auth_gate_counts.get(video_id, 0) + 1
        self._global_auth_gate_count += 1
        multiplier = min(4, self._auth_gate_counts[video_id])
        cooldown_seconds = max(60, self.settings.youtube_auth_gate_cooldown_minutes * 60 * multiplier)
        self._auth_gated_videos[video_id] = monotonic() + cooldown_seconds
        if self._global_auth_gate_count >= max(1, self.settings.youtube_auth_gate_global_threshold):
            self._global_auth_gate_until = monotonic() + max(
                60,
                self.settings.youtube_auth_gate_global_cooldown_minutes * 60,
            )
            self._global_auth_gate_count = 0

    def _get_cached_result(self, video_id: str) -> ExtractedContent | None:
        cached = self._result_cache.get(video_id)
        now = monotonic()
        if cached is None:
            return None
        if now >= cached.expires_at:
            self._result_cache.pop(video_id, None)
            return None
        return cached.extracted

    def _cache_result(self, video_id: str, extracted: ExtractedContent) -> None:
        ttl_seconds = max(60, self.settings.youtube_result_cache_minutes * 60)
        self._result_cache[video_id] = _CachedYouTubeResult(
            extracted=extracted,
            expires_at=monotonic() + ttl_seconds,
        )
        self._auth_gated_videos.pop(video_id, None)
        self._auth_gate_counts.pop(video_id, None)
        self._global_auth_gate_count = 0

    def _safe_cookie_options(self) -> tuple[str | None, tuple | None]:
        if not self.settings.youtube_cookie_mode_enabled:
            if not self._cookie_warning_emitted and (
                self.settings.youtube_cookies_file or self.settings.youtube_cookies_from_browser
            ):
                logger.warning(
                    "YouTube cookie settings are present but cookie mode is disabled, so the bot will ignore them."
                )
                self._cookie_warning_emitted = True
            return None, None

        if self.settings.youtube_cookies_file:
            cookiefile = Path(self.settings.youtube_cookies_file).expanduser()
            if cookiefile.exists():
                return str(cookiefile), None
            logger.warning("Configured YouTube cookies file was not found, so cookie mode was skipped.")
            return None, None

        if self.settings.youtube_cookies_from_browser:
            browser = self.settings.youtube_cookies_from_browser
            profile = self.settings.youtube_cookies_browser_profile
            if self.settings.youtube_require_browser_profile_for_cookies and not profile:
                logger.warning(
                    "YouTube cookie mode was enabled, but no browser profile was set. "
                    "For safety, browser cookies are ignored until YOUTUBE_COOKIES_BROWSER_PROFILE is set."
                )
                return None, None
            return None, (browser, None, None, profile) if profile else (browser,)

        return None, None

    def _cookie_alert_message(self) -> str:
        if not self.settings.youtube_cookie_mode_enabled:
            return ""
        if self.settings.youtube_cookies_file:
            cookie_path = Path(self.settings.youtube_cookies_file).expanduser()
            if cookie_path.exists():
                return (
                    "Cookie alert: YouTube cookie mode was active for this request using a local cookies file. "
                    "Treat that browser session as sensitive and keep it isolated from personal accounts."
                )
            return ""
        if self.settings.youtube_cookies_from_browser:
            profile = self.settings.youtube_cookies_browser_profile or "default profile"
            return (
                "Cookie alert: YouTube cookie mode was active for this request using browser cookies "
                f"from profile '{profile}'. Use a separate browser profile and account for this mode."
            )
        return ""

    @staticmethod
    def _extract_info(url: str, options: dict) -> dict:
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=not options.get("skip_download", False))


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be"}:
        return parsed.path.lstrip("/")
    if parsed.hostname and "youtube.com" in parsed.hostname:
        query = parse_qs(parsed.query)
        if "v" in query:
            return query["v"][0]
    raise YouTubeExtractionError("Could not extract a YouTube video ID from the provided URL.")


def _clean_subtitle_text(raw_text: str) -> str:
    if "<text" in raw_text:
        cleaned = re.sub(r"<[^>]+>", " ", raw_text)
    else:
        cleaned = raw_text
        cleaned = re.sub(r"WEBVTT", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}",
            " ",
            cleaned,
        )
        cleaned = re.sub(r"\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}\.\d{3}", " ", cleaned)
    cleaned = re.sub(r"&[a-z]+;", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _subtitle_text_to_timestamped_transcript(raw_text: str, window_seconds: int = 150) -> str:
    if "<text" in raw_text:
        entries = re.findall(
            r'<text[^>]*start="([^"]+)"[^>]*>(.*?)</text>',
            raw_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        timeline_entries: list[tuple[float, str]] = []
        for start_raw, text_raw in entries:
            text = re.sub(r"<[^>]+>", " ", text_raw)
            text = re.sub(r"&[a-z]+;", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            start_seconds = _parse_seconds(start_raw)
            if timeline_entries and timeline_entries[-1][1].strip().lower() == text.strip().lower():
                continue
            timeline_entries.append((start_seconds, text))
        return _group_timestamped_entries(timeline_entries, window_seconds=window_seconds)

    if "WEBVTT" in raw_text.upper():
        timeline_entries: list[tuple[float, str]] = []
        blocks = re.split(r"\n\s*\n", raw_text.strip())
        for block in blocks:
            block = block.strip()
            if not block or block.upper() == "WEBVTT":
                continue
            block_lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not block_lines:
                continue
            timing_line = next((line for line in block_lines if "-->" in line), "")
            if not timing_line:
                continue
            text_lines = [
                line
                for line in block_lines
                if "-->" not in line and not re.fullmatch(r"\d+", line)
            ]
            text = re.sub(r"&[a-z]+;", " ", " ".join(text_lines))
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            start_raw = timing_line.split("-->", 1)[0].strip()
            start_seconds = _parse_vtt_seconds(start_raw)
            if timeline_entries and timeline_entries[-1][1].strip().lower() == text.strip().lower():
                continue
            timeline_entries.append((start_seconds, text))
        if timeline_entries:
            return _group_timestamped_entries(timeline_entries, window_seconds=window_seconds)

    return _clean_subtitle_text(raw_text)


def _fetch_best_transcript(transcript_list):
    preferred_languages = [
        "en",
        "en-US",
        "en-GB",
        "zh-Hans",
        "zh-Hant",
        "zh",
    ]
    try:
        transcript = transcript_list.find_transcript(preferred_languages)
        return transcript.fetch()
    except Exception:
        pass

    try:
        transcript = transcript_list.find_generated_transcript(preferred_languages)
        return transcript.fetch()
    except Exception:
        pass

    try:
        first = next(iter(transcript_list))
        return first.fetch()
    except StopIteration as exc:
        raise NoTranscriptFound("No transcript available for this video.") from exc


def _looks_like_js_runtime_issue(message: str) -> bool:
    lowered = message.lower()
    return "javascript runtime" in lowered or "js runtime" in lowered or "ejs" in lowered


def _looks_like_youtube_auth_gate(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "sign in to confirm you’re not a bot",
            "sign in to confirm you're not a bot",
            "use --cookies-from-browser",
            "use --cookies",
            "authentication",
            "login required",
            "age-restricted",
        )
    )


def _youtube_auth_gate_message(settings: Settings) -> str:
    return (
        "yt-dlp hit YouTube's sign-in or anti-bot media gate for this video, so the bot skipped direct media access "
        "and moved on to transcript-site fallbacks instead. "
        f"The bot will still pause repeated yt-dlp retries for about {max(1, settings.youtube_auth_gate_cooldown_minutes)} minute(s) "
        "to avoid hammering the same blocked video."
    )


class _YTDLPLogger:
    def debug(self, message: str) -> None:
        if message.startswith("[debug]"):
            logger.debug("yt-dlp: %s", message)

    def warning(self, message: str) -> None:
        logger.warning("yt-dlp: %s", message)

    def error(self, message: str) -> None:
        logger.warning("yt-dlp: %s", message)


def _transcript_items_to_text(transcript, window_seconds: int = 150) -> str:
    timeline_entries: list[tuple[float, str]] = []
    for item in transcript:
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            start = item.get("start")
        else:
            text = str(getattr(item, "text", "")).strip()
            start = getattr(item, "start", None)
        if text:
            start_seconds = _parse_seconds(start) if start is not None else 0.0
            if timeline_entries and timeline_entries[-1][1].strip().lower() == text.strip().lower():
                continue
            timeline_entries.append((start_seconds, text))
    return _group_timestamped_entries(timeline_entries, window_seconds=window_seconds)


def _format_seconds(value) -> str:
    try:
        total_seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "00:00"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_vtt_timestamp(value: str) -> str:
    cleaned = value.replace(".", ":").strip()
    parts = [part for part in cleaned.split(":") if part != ""]
    if len(parts) >= 4:
        hours, minutes, seconds = parts[-4], parts[-3], parts[-2]
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
    if len(parts) >= 3:
        minutes, seconds = parts[-3], parts[-2]
        hours = parts[-4] if len(parts) >= 4 else None
        if hours is not None:
            return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
        return f"{int(minutes):02d}:{int(seconds):02d}"
    return value


def _same_caption_text(existing_line: str, new_text: str) -> bool:
    existing_text = re.sub(r"^\[[^\]]+\]\s*", "", existing_line).strip().lower()
    return existing_text == new_text.strip().lower()


def _parse_seconds(value) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _parse_vtt_seconds(value: str) -> float:
    cleaned = value.strip().replace(",", ".")
    parts = cleaned.split(":")
    try:
        if len(parts) == 3:
            hours = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        if len(parts) == 2:
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
    except ValueError:
        return 0.0
    return 0.0


def _group_timestamped_entries(
    entries: list[tuple[float, str]],
    *,
    window_seconds: int,
) -> str:
    if not entries:
        return ""
    window_seconds = max(60, window_seconds)
    grouped: list[str] = []
    bucket_start = None
    bucket_end = None
    bucket_texts: list[str] = []

    for start_seconds, text in entries:
        if bucket_start is None:
            bucket_start = start_seconds
            bucket_end = start_seconds + window_seconds
        elif start_seconds >= bucket_end:
            grouped.append(_render_timeline_bucket(bucket_start, bucket_end, bucket_texts))
            bucket_start = start_seconds
            bucket_end = start_seconds + window_seconds
            bucket_texts = []
        if not bucket_texts or bucket_texts[-1].strip().lower() != text.strip().lower():
            bucket_texts.append(text)

    if bucket_start is not None and bucket_texts:
        grouped.append(_render_timeline_bucket(bucket_start, bucket_end or bucket_start + window_seconds, bucket_texts))
    return "\n\n".join(section for section in grouped if section.strip())


def _render_timeline_bucket(start_seconds: float, end_seconds: float, texts: list[str]) -> str:
    merged = " ".join(texts)
    merged = re.sub(r"\s+", " ", merged).strip()
    return f"[{_format_seconds(start_seconds)} - {_format_seconds(end_seconds)}] {merged}"


def _format_iso8601_duration(value: str) -> str:
    match = re.fullmatch(
        r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        value,
    )
    if not match:
        return value
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    return _format_seconds(total)


def _metadata_fallback_body(metadata: dict[str, str], issues: list[str] | None = None) -> str:
    lines = [
        "Transcript retrieval did not succeed, so this result is based on YouTube metadata only.",
        "",
        f"Title: {metadata.get('title', 'Unknown')}",
    ]
    if metadata.get("channel_title"):
        lines.append(f"Channel: {metadata['channel_title']}")
    if metadata.get("published_at"):
        lines.append(f"Published at: {metadata['published_at']}")
    if metadata.get("duration"):
        lines.append(f"Duration: {metadata['duration']}")
    if metadata.get("description"):
        lines.extend(["", "Description:", metadata["description"]])
    if issues:
        lines.append("")
        lines.append("Transcript attempt notes:")
        for issue in issues:
            if issue:
                lines.append(f"- {issue}")
    return "\n".join(lines).strip()
