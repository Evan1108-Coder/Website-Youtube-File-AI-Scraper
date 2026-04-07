from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
import httpx

try:
    import trafilatura
except ImportError:  # pragma: no cover
    trafilatura = None

from ai_scraper_bot.models import ExtractedContent, VisualInput
from ai_scraper_bot.services.music_analysis import LocalMusicAnalyzer
from ai_scraper_bot.services.video_analysis import LocalVideoAnalyzer
from ai_scraper_bot.services.vision import LocalVisionAnalyzer

DEFAULT_WEBSITE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

HTTP2_AVAILABLE = importlib.util.find_spec("h2") is not None
DIRECT_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".ogv"}
MAX_DIRECT_VIDEO_BYTES = 45 * 1024 * 1024


@dataclass(slots=True)
class WebsiteImageCandidate:
    url: str
    label: str
    context: str


@dataclass(slots=True)
class WebsiteVideoCandidate:
    url: str
    label: str
    kind: str


async def extract_website_text(
    url: str,
    *,
    vision_analyzer: LocalVisionAnalyzer | None = None,
    video_analyzer: LocalVideoAnalyzer | None = None,
    music_analyzer: LocalMusicAnalyzer | None = None,
    downloads_dir: Path | None = None,
) -> ExtractedContent:
    html = await _fetch_website_html(url)

    title = url
    body = ""
    metadata: dict[str, str] = {"type": "website"}
    visual_inputs: list[VisualInput] = []
    reviewed_media: list[str] = []
    issues: list[str] = []

    if trafilatura is not None:
        downloaded = await asyncio.to_thread(
            trafilatura.extract,
            html,
            include_comments=False,
            include_tables=True,
        )
        if downloaded:
            body = downloaded.strip()

    soup = await asyncio.to_thread(BeautifulSoup, html, "html.parser")
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    meta_description = _meta_description(soup)
    if meta_description:
        metadata["meta_description"] = meta_description

    if not body:
        body = await asyncio.to_thread(soup.get_text, "\n", strip=True)

    image_candidates = _extract_page_images(soup, url)
    video_candidates = _extract_page_videos(soup, url)
    related_urls = _extract_related_urls(soup, url, extra_urls=[candidate.url for candidate in video_candidates])

    for candidate in image_candidates:
        visual_inputs.append(
            VisualInput(
                kind="image_url",
                value=candidate.url,
                label=candidate.label or candidate.context or "website image",
            )
        )

    body_sections = [body.strip()]
    if meta_description and meta_description not in body:
        body_sections.append(f"Meta description: {meta_description}")
    if image_candidates:
        image_cues = []
        for candidate in image_candidates[:8]:
            detail = candidate.label or "Unlabeled image"
            if candidate.context:
                detail = f"{detail} | Nearby context: {candidate.context}"
            image_cues.append(f"- {detail}")
        body_sections.append("Image and artwork cues:\n" + "\n".join(image_cues))

    if vision_analyzer is not None and downloads_dir is not None and image_candidates:
        image_notes, image_reviewed, image_issues = await _describe_website_images(
            image_candidates=image_candidates[:3],
            vision_analyzer=vision_analyzer,
            downloads_dir=downloads_dir,
        )
        if image_notes:
            body_sections.append("Visual image review:\n" + image_notes)
        reviewed_media.extend(image_reviewed)
        issues.extend(image_issues)

    if video_candidates and downloads_dir is not None:
        video_notes, video_reviewed, video_issues = await _inspect_website_videos(
            video_candidates=video_candidates[:2],
            downloads_dir=downloads_dir,
            video_analyzer=video_analyzer,
            music_analyzer=music_analyzer,
        )
        if video_notes:
            body_sections.append("Website video review:\n" + video_notes)
        reviewed_media.extend(video_reviewed)
        issues.extend(video_issues)

    combined_body = "\n\n".join(section for section in body_sections if section).strip()
    metadata["image_count"] = str(len(image_candidates))
    metadata["video_count"] = str(len(video_candidates))

    return ExtractedContent(
        title=title,
        body=combined_body,
        source_label=url,
        metadata=metadata,
        visual_inputs=visual_inputs[:4],
        issues=_dedupe_preserve_order(issues),
        reviewed_media=_dedupe_preserve_order(reviewed_media),
        related_urls=related_urls,
    )


async def _fetch_website_html(url: str) -> str:
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(45.0),
        headers=DEFAULT_WEBSITE_HEADERS,
        http2=HTTP2_AVAILABLE,
    ) as client:
        for attempt in range(2):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 403:
                    raise RuntimeError(
                        "This website returned 403 Forbidden. It is publicly visible in a browser, "
                        "but it is blocking automated requests from the bot. Some sites, including "
                        "certain .edu and .gov pages, use anti-bot or firewall rules that cannot always "
                        "be bypassed safely. The safest fallback is to upload the file or page content directly."
                    ) from exc
                if status_code in {429, 500, 502, 503, 504} and attempt == 0:
                    last_error = exc
                    await asyncio.sleep(1.5)
                    continue
                raise RuntimeError(
                    f"This website returned HTTP {status_code}, so the bot could not fetch it safely."
                ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                break
    raise RuntimeError(
        f"The bot could not fetch this website after retrying. Last error: {last_error}"
    )


def _meta_description(soup: BeautifulSoup) -> str:
    for key, value in (("name", "description"), ("property", "og:description")):
        tag = soup.find("meta", attrs={key: value})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def _extract_page_images(soup: BeautifulSoup, base_url: str) -> list[WebsiteImageCandidate]:
    results: list[WebsiteImageCandidate] = []
    seen: set[str] = set()
    for image in soup.find_all("img"):
        raw_url = image.get("src") or image.get("data-src") or ""
        if not raw_url and image.get("srcset"):
            raw_url = str(image["srcset"]).split(",")[0].strip().split(" ")[0]
        if not raw_url:
            continue
        absolute_url = urljoin(base_url, raw_url)
        if not absolute_url.startswith(("http://", "https://")) or absolute_url in seen:
            continue
        seen.add(absolute_url)
        label = " ".join(str(image.get("alt", "")).split())
        context = _nearby_text(image)
        results.append(WebsiteImageCandidate(url=absolute_url, label=label, context=context))
        if len(results) >= 8:
            break
    return results


def _extract_page_videos(soup: BeautifulSoup, base_url: str) -> list[WebsiteVideoCandidate]:
    results: list[WebsiteVideoCandidate] = []
    seen: set[str] = set()

    for video in soup.find_all("video"):
        urls = [video.get("src")] + [source.get("src") for source in video.find_all("source")]
        label = _nearby_text(video)
        for raw_url in urls:
            if not raw_url:
                continue
            absolute_url = urljoin(base_url, raw_url)
            if absolute_url in seen:
                continue
            seen.add(absolute_url)
            results.append(WebsiteVideoCandidate(url=absolute_url, label=label, kind="direct"))

    for iframe in soup.find_all("iframe"):
        raw_url = iframe.get("src") or ""
        if not raw_url:
            continue
        absolute_url = urljoin(base_url, raw_url)
        if absolute_url in seen:
            continue
        seen.add(absolute_url)
        hostname = (urlparse(absolute_url).hostname or "").lower()
        kind = "youtube" if ("youtube.com" in hostname or "youtu.be" in hostname) else "embed"
        results.append(
            WebsiteVideoCandidate(
                url=absolute_url,
                label=_nearby_text(iframe),
                kind=kind,
            )
        )
    return results


def _extract_related_urls(
    soup: BeautifulSoup,
    base_url: str,
    *,
    extra_urls: list[str] | None = None,
) -> list[str]:
    base_host = (urlparse(base_url).hostname or "").lower()
    results: list[str] = []
    seen: set[str] = set()
    disallowed_host_markers = (
        "doubleclick",
        "googlesyndication",
        "googleadservices",
        "adservice",
        "ads.",
        "analytics",
        "facebook.com/sharer",
        "twitter.com/intent",
    )

    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)
        host = (parsed.hostname or "").lower()
        if not host or any(marker in absolute_url.lower() for marker in disallowed_host_markers):
            continue
        if parsed.scheme not in {"http", "https"}:
            continue
        text = " ".join(anchor.get_text(" ", strip=True).split()).lower()
        if text in {"advertisement", "ad", "sponsored"}:
            continue
        if host != base_host and ("youtube.com" not in host and "youtu.be" not in host):
            continue
        normalized = absolute_url.split("#", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
        if len(results) >= 8:
            break

    for raw_url in extra_urls or []:
        normalized = raw_url.split("#", 1)[0]
        if normalized and normalized not in seen:
            results.append(normalized)
            seen.add(normalized)
        if len(results) >= 8:
            break

    return results[:8]


async def _describe_website_images(
    *,
    image_candidates: list[WebsiteImageCandidate],
    vision_analyzer: LocalVisionAnalyzer,
    downloads_dir: Path,
) -> tuple[str, list[str], list[str]]:
    notes: list[str] = []
    reviewed_media: list[str] = []
    issues: list[str] = []
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
        headers=DEFAULT_WEBSITE_HEADERS,
    ) as client:
        for index, candidate in enumerate(image_candidates, start=1):
            suffix = Path(candidate.url.split("?")[0]).suffix or ".jpg"
            temp_path = downloads_dir / f"website_image_{index}{suffix}"
            try:
                response = await client.get(candidate.url)
                response.raise_for_status()
                temp_path.write_bytes(response.content)
                description = await asyncio.wait_for(
                    vision_analyzer.analyze_image_file(temp_path),
                    timeout=20,
                )
                if description:
                    label = candidate.label or candidate.context or f"Website image {index}"
                    reviewed_media.append(f"Image {index}: {label}")
                    notes.append(
                        f"- **Image {index}** ({label}): {description}"
                    )
            except Exception:
                issues.append(
                    f"Could not inspect website image {index} from {candidate.url}."
                )
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
    return "\n".join(notes), reviewed_media, issues


async def _inspect_website_videos(
    *,
    video_candidates: list[WebsiteVideoCandidate],
    downloads_dir: Path,
    video_analyzer: LocalVideoAnalyzer | None,
    music_analyzer: LocalMusicAnalyzer | None,
) -> tuple[str, list[str], list[str]]:
    notes: list[str] = []
    reviewed_media: list[str] = []
    issues: list[str] = []
    if not video_candidates:
        return "", reviewed_media, issues

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0),
        headers=DEFAULT_WEBSITE_HEADERS,
    ) as client:
        for index, candidate in enumerate(video_candidates, start=1):
            if candidate.kind == "youtube":
                issues.append(
                    f"Website video {index} is a YouTube embed and was skipped here so one blocked video would not stop the whole website analysis."
                )
                continue
            if candidate.kind == "embed":
                issues.append(
                    f"Website video {index} is an embedded player that was detected but not auto-controlled safely."
                )
                continue
            suffix = Path(candidate.url.split("?")[0]).suffix.lower()
            if suffix not in DIRECT_VIDEO_SUFFIXES:
                issues.append(
                    f"Website video {index} was detected, but its source was not a directly supported video file."
                )
                continue
            temp_path = downloads_dir / f"website_video_{index}{suffix or '.mp4'}"
            try:
                downloaded = await _download_limited_file(client, candidate.url, temp_path, MAX_DIRECT_VIDEO_BYTES)
                if not downloaded:
                    issues.append(
                        f"Website video {index} was skipped because it was too large or could not be downloaded safely."
                    )
                    continue
                reviewed_media.append(
                    f"Website video {index}: {candidate.label or candidate.url}"
                )
                if video_analyzer is None:
                    analysis = None
                else:
                    analysis = await video_analyzer.analyze_video_file(temp_path)
                music_analysis = None
                if music_analyzer is not None:
                    music_analysis = await music_analyzer.analyze_media_file(
                        temp_path,
                        source_label=candidate.label or candidate.url,
                    )
                note_parts: list[str] = []
                if analysis and analysis.summary_text:
                    note_parts.append(analysis.summary_text)
                if music_analysis and music_analysis.summary_text:
                    note_parts.append(music_analysis.summary_text)
                if note_parts:
                    notes.append(
                        f"- **Video {index}** ({candidate.label or candidate.url}):\n" + "\n\n".join(note_parts)
                    )
                if analysis:
                    issues.extend(analysis.issues)
                if music_analysis:
                    issues.extend(music_analysis.issues)
                    reviewed_media.extend(music_analysis.reviewed_media)
            except Exception:
                issues.append(
                    f"Could not inspect website video {index} from {candidate.url}."
                )
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
    return "\n\n".join(notes), reviewed_media, issues


async def _download_limited_file(
    client: httpx.AsyncClient,
    url: str,
    output_path: Path,
    max_bytes: int,
) -> bool:
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    return False
            except ValueError:
                pass

        bytes_written = 0
        with output_path.open("wb") as handle:
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    handle.close()
                    output_path.unlink(missing_ok=True)
                    return False
                handle.write(chunk)
    return output_path.exists()


def _nearby_text(tag: Tag) -> str:
    snippets: list[str] = []
    parent = tag.parent
    if parent:
        caption = parent.find("figcaption")
        if caption:
            snippets.append(" ".join(caption.get_text(" ", strip=True).split()))
        for sibling in list(parent.children):
            if sibling is tag or not isinstance(sibling, Tag):
                continue
            text = " ".join(sibling.get_text(" ", strip=True).split())
            if text:
                snippets.append(text)
            if len(snippets) >= 2:
                break
    joined = " | ".join(text for text in snippets if text)
    return joined[:220]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
