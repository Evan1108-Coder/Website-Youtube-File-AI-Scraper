from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib.util
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from ai_scraper_bot.config import Settings

try:
    import essentia.standard as es
except ImportError:  # pragma: no cover
    es = None

try:
    import acoustid
except ImportError:  # pragma: no cover
    acoustid = None


@dataclass(slots=True)
class MusicAnalysisResult:
    summary_text: str = ""
    reviewed_media: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class _EssentiaSummary:
    bpm: float | None = None
    beat_confidence: float | None = None
    key: str = ""
    scale: str = ""
    key_strength: float | None = None
    average_loudness_db: float | None = None


class LocalMusicAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._mirflex_available = bool(settings.music_mirflex_repo_path)

    async def analyze_media_file(
        self,
        media_path: Path,
        *,
        transcript_text: str = "",
        source_label: str = "",
    ) -> MusicAnalysisResult:
        if not self.settings.enable_music_detection:
            return MusicAnalysisResult()

        reviewed_media: list[str] = []
        issues: list[str] = []
        metadata: dict[str, str] = {
            "music_analysis_ran": "true",
        }
        attempted_libraries = _attempted_music_libraries(self.settings)
        if attempted_libraries:
            metadata["music_libraries_attempted"] = ", ".join(attempted_libraries)

        with TemporaryDirectory(prefix="music_analysis_", dir=str(media_path.parent)) as temp_dir:
            sample_path = Path(temp_dir) / "music_sample.wav"
            try:
                extracted = await self._extract_audio_sample(media_path, sample_path)
            except Exception as exc:
                return MusicAnalysisResult(
                    issues=[f"Music analysis could not extract an audio sample: {exc}"]
                )

            if not extracted:
                return MusicAnalysisResult(
                    issues=["Music analysis did not get a usable audio sample from this media."]
                )

            reviewed_media.append(
                f"Audio sample for music analysis from {source_label or media_path.name}"
            )

            essentia_result = await self._run_music_stage(
                "Essentia",
                self._analyze_with_essentia(sample_path, issues, metadata),
                issues,
            )
            acoustid_result = await self._run_music_stage(
                "AcoustID",
                self._analyze_with_acoustid(sample_path, issues, metadata),
                issues,
            )
            mirflex_result = await self._run_music_stage(
                "MIRFLEX",
                self._analyze_with_mirflex(sample_path, issues, metadata),
                issues,
            )

        successful_libraries = _successful_music_libraries(
            essentia_result=essentia_result,
            acoustid_result=acoustid_result,
            mirflex_result=mirflex_result,
        )
        if successful_libraries:
            metadata["music_libraries_with_output"] = ", ".join(successful_libraries)

        music_detected = _music_likely_present(
            transcript_text=transcript_text,
            essentia_result=essentia_result,
            acoustid_result=acoustid_result,
            mirflex_result=mirflex_result,
        )
        metadata["music_detected"] = "true" if music_detected else "false"

        summary_lines = _build_music_summary_lines(
            essentia_result=essentia_result,
            acoustid_result=acoustid_result,
            mirflex_result=mirflex_result,
            transcript_text=transcript_text,
            music_detected=music_detected,
        )
        if not summary_lines and music_detected:
            summary_lines = ["- Music-like structure was detected, but only limited details were recovered."]
        if not summary_lines and not music_detected:
            issues.append("Music analysis ran, but no strong standalone music signal was confirmed in the sampled audio.")

        summary_text = ""
        if summary_lines:
            summary_text = "Music analysis:\n" + "\n".join(summary_lines)

        return MusicAnalysisResult(
            summary_text=summary_text,
            reviewed_media=reviewed_media,
            issues=_dedupe_preserve_order(issues),
            metadata=metadata,
        )

    async def _run_music_stage(
        self,
        stage_name: str,
        awaitable,
        issues: list[str],
    ):
        try:
            return await awaitable
        except Exception as exc:
            issues.append(
                f"{stage_name} music analysis failed unexpectedly, but the rest of the music pipeline continued: {exc}"
            )
            return None

    async def _extract_audio_sample(self, media_path: Path, output_path: Path) -> bool:
        has_audio = await _media_has_audio_stream(media_path)
        if has_audio is False:
            raise RuntimeError("This media file does not contain an audio stream for music analysis.")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media_path),
            "-map",
            "a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-t",
            str(max(15, self.settings.music_analysis_sample_seconds)),
            str(output_path),
            "-y",
        ]
        try:
            await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg is not available for extracting audio samples.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip()
            if _looks_like_missing_audio_stream(stderr):
                raise RuntimeError("This media file does not contain an audio stream for music analysis.") from exc
            raise RuntimeError(_short_ffmpeg_reason(stderr) or str(exc)) from exc
        return output_path.exists() and output_path.stat().st_size > 0

    async def _analyze_with_essentia(
        self,
        audio_path: Path,
        issues: list[str],
        metadata: dict[str, str],
    ) -> _EssentiaSummary | None:
        if not self.settings.music_essentia_enabled:
            return None
        if es is None:
            issues.append("Essentia was not installed, so local musical feature extraction was skipped.")
            return None
        try:
            summary = await asyncio.to_thread(_run_essentia_summary, audio_path)
        except Exception as exc:
            issues.append(f"Essentia music analysis failed: {exc}")
            return None

        if summary.bpm is not None:
            metadata["music_bpm"] = f"{summary.bpm:.1f}"
        if summary.key:
            metadata["music_key"] = summary.key
        if summary.scale:
            metadata["music_scale"] = summary.scale
        return summary

    async def _analyze_with_acoustid(
        self,
        audio_path: Path,
        issues: list[str],
        metadata: dict[str, str],
    ) -> dict[str, str] | None:
        if not self.settings.music_acoustid_enabled:
            return None
        if not self.settings.music_acoustid_api_key:
            issues.append("AcoustID was enabled, but no MUSIC_ACOUSTID_API_KEY was configured.")
            return None
        if acoustid is None:
            issues.append("pyacoustid was not installed, so AcoustID song identification was skipped.")
            return None
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_acoustid_lookup,
                    audio_path,
                    self.settings.music_acoustid_api_key,
                    self.settings.music_fpcalc_binary,
                ),
                timeout=max(5, self.settings.music_acoustid_timeout_seconds),
            )
        except asyncio.TimeoutError:
            issues.append("AcoustID identification timed out.")
            return None
        except Exception as exc:
            issues.append(f"AcoustID identification failed: {exc}")
            return None
        if not result:
            return None
        metadata["music_track_title"] = result.get("title", "")
        metadata["music_track_artist"] = result.get("artist", "")
        if result.get("score"):
            metadata["music_track_score"] = result["score"]
        return result

    async def _analyze_with_mirflex(
        self,
        audio_path: Path,
        issues: list[str],
        metadata: dict[str, str],
    ) -> dict[str, str] | None:
        if not self.settings.music_mirflex_enabled:
            return None
        repo_path = self.settings.music_mirflex_repo_path.strip()
        if not repo_path:
            issues.append(
                "MIRFLEX support was enabled, but no local MIRFLEX repo path was configured. "
                "Essentia and AcoustID still continued normally."
            )
            return None
        repo = Path(repo_path).expanduser()
        if not repo.exists():
            issues.append(
                "MIRFLEX support was enabled, but the configured MIRFLEX repo path does not exist. "
                "Essentia and AcoustID still continued normally."
            )
            return None
        if importlib.util.find_spec("yaml") is None:
            issues.append(
                "MIRFLEX support needs PyYAML/config tooling that is not installed in this environment. "
                "Essentia and AcoustID still continued normally."
            )
            return None
        issues.append(
            "MIRFLEX repo support is configured as an optional local hook, but this project does not yet have a stable auto-run config for that repo. "
            "Essentia and AcoustID still continued normally."
        )
        metadata["mirflex_repo_detected"] = "true"
        return None


def _run_essentia_summary(audio_path: Path) -> _EssentiaSummary:
    loader = es.MonoLoader(filename=str(audio_path), sampleRate=44100)
    audio = loader()
    if len(audio) == 0:
        raise RuntimeError("Essentia loaded an empty audio sample.")

    rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
    bpm, _beats, beat_confidence, _estimates, _intervals = rhythm_extractor(audio)
    key_extractor = es.KeyExtractor()
    key, scale, key_strength = key_extractor(audio)
    loudness_algo = es.Loudness()
    loudness = float(loudness_algo(audio))

    return _EssentiaSummary(
        bpm=float(bpm) if bpm else None,
        beat_confidence=float(beat_confidence) if beat_confidence is not None else None,
        key=str(key or ""),
        scale=str(scale or ""),
        key_strength=float(key_strength) if key_strength is not None else None,
        average_loudness_db=loudness,
    )


def _run_acoustid_lookup(audio_path: Path, api_key: str, fpcalc_binary: str) -> dict[str, str] | None:
    acoustid.FPCALC_COMMAND = fpcalc_binary
    matches = list(acoustid.match(api_key, str(audio_path)))
    if not matches:
        return None
    best = matches[0]
    score = float(best[0]) if len(best) >= 1 and best[0] is not None else 0.0
    recording_id = str(best[1]) if len(best) >= 2 and best[1] is not None else ""
    title = str(best[2]) if len(best) >= 3 and best[2] is not None else ""
    artist = str(best[3]) if len(best) >= 4 and best[3] is not None else ""
    if not title and not artist and not recording_id:
        return None
    return {
        "title": title,
        "artist": artist,
        "recording_id": recording_id,
        "score": f"{score:.3f}",
    }


def _music_likely_present(
    *,
    transcript_text: str,
    essentia_result: _EssentiaSummary | None,
    acoustid_result: dict[str, str] | None,
    mirflex_result: dict[str, str] | None,
) -> bool:
    if acoustid_result:
        return True
    if mirflex_result:
        return True
    if essentia_result is None:
        return False
    if essentia_result.key_strength is not None and essentia_result.key_strength >= 0.16:
        if essentia_result.bpm is not None and 45 <= essentia_result.bpm <= 220:
            return True
    if transcript_text.strip() and len(transcript_text.strip()) > 500:
        return False
    if essentia_result.beat_confidence is not None and essentia_result.beat_confidence >= 1.2:
        return True
    return False


def _build_music_summary_lines(
    *,
    essentia_result: _EssentiaSummary | None,
    acoustid_result: dict[str, str] | None,
    mirflex_result: dict[str, str] | None,
    transcript_text: str,
    music_detected: bool,
) -> list[str]:
    lines: list[str] = []
    if acoustid_result:
        title = acoustid_result.get("title", "").strip()
        artist = acoustid_result.get("artist", "").strip()
        score = acoustid_result.get("score", "").strip()
        if title and artist:
            detail = f"- **AcoustID match:** {title} by {artist}"
            if score:
                detail += f" (score {score})"
            lines.append(detail + ".")
        elif title:
            detail = f"- **AcoustID match:** {title}"
            if score:
                detail += f" (score {score})"
            lines.append(detail + ".")

    if essentia_result is not None:
        musical_bits: list[str] = []
        if essentia_result.bpm is not None:
            musical_bits.append(f"tempo around {essentia_result.bpm:.0f} BPM")
        if essentia_result.key:
            key_text = essentia_result.key
            if essentia_result.scale:
                key_text = f"{key_text} {essentia_result.scale}"
            if essentia_result.key_strength is not None:
                key_text = f"{key_text} (strength {essentia_result.key_strength:.2f})"
            musical_bits.append(f"estimated key {key_text}")
        if essentia_result.average_loudness_db is not None:
            musical_bits.append(f"loudness score {essentia_result.average_loudness_db:.2f}")
        if musical_bits:
            lines.append("- **Essentia features:** " + ", ".join(musical_bits) + ".")

    if mirflex_result:
        tag_text = ", ".join(f"{key}: {value}" for key, value in mirflex_result.items() if value)
        if tag_text:
            lines.append(f"- **MIRFLEX tags:** {tag_text}.")

    if music_detected and transcript_text.strip() and len(transcript_text.strip()) > 500:
        lines.append("- **Context note:** speech is substantial, so any detected music may be background rather than the main focus.")
    elif music_detected and not lines:
        lines.append("- **Context note:** music-like structure was detected in the sampled audio.")
    return lines


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _attempted_music_libraries(settings: Settings) -> list[str]:
    attempted: list[str] = []
    if settings.music_essentia_enabled:
        attempted.append("Essentia")
    if settings.music_acoustid_enabled:
        attempted.append("AcoustID")
    if settings.music_mirflex_enabled:
        attempted.append("MIRFLEX")
    return attempted


def _successful_music_libraries(
    *,
    essentia_result: _EssentiaSummary | None,
    acoustid_result: dict[str, str] | None,
    mirflex_result: dict[str, str] | None,
) -> list[str]:
    successful: list[str] = []
    if essentia_result is not None:
        successful.append("Essentia")
    if acoustid_result:
        successful.append("AcoustID")
    if mirflex_result:
        successful.append("MIRFLEX")
    return successful


async def _media_has_audio_stream(media_path: Path) -> bool | None:
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "json",
        str(media_path),
    ]
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return None
    return bool(streams)


def _looks_like_missing_audio_stream(text: str) -> bool:
    lowered = text.lower()
    return (
        "does not contain any stream" in lowered
        or "stream map 'a:0' matches no streams" in lowered
        or "contains no audio stream" in lowered
        or "no audio stream" in lowered
    )


def _short_ffmpeg_reason(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1][:240]
