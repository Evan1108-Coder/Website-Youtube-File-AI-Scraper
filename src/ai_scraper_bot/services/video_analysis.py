from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops, ImageStat

from ai_scraper_bot.config import Settings
from ai_scraper_bot.services.summarizer import MiniMaxHTTPSummarizer
from ai_scraper_bot.services.vision import LocalVisionAnalyzer


@dataclass(slots=True)
class VideoAnalysisResult:
    summary_text: str = ""
    reviewed_media: list[str] = field(default_factory=list)
    interval_history: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _PreviewFrame:
    path: Path
    timestamp_seconds: float
    change_score: float


class LocalVideoAnalyzer:
    def __init__(
        self,
        settings: Settings,
        vision_analyzer: LocalVisionAnalyzer | None,
        summarizer: MiniMaxHTTPSummarizer | None = None,
    ) -> None:
        self.settings = settings
        self.vision_analyzer = vision_analyzer
        self.summarizer = summarizer

    async def analyze_video_file(self, video_path: Path, transcript_text: str = "") -> VideoAnalysisResult:
        if self.vision_analyzer is None or not self.settings.enable_local_vision:
            return VideoAnalysisResult()

        duration_seconds = await self._probe_duration_seconds(video_path)
        if duration_seconds is None or duration_seconds <= 0:
            return VideoAnalysisResult(issues=["Could not determine the video duration for visual analysis."])

        issues: list[str] = []
        base_interval = max(1, self.settings.video_scan_base_interval_seconds)
        max_interval = max(base_interval, self.settings.video_scan_max_interval_seconds)
        interval_history = [
            f"Base scan started at {base_interval} seconds.",
            f"Maximum calm-section interval allowed: {max_interval} seconds.",
        ]

        with TemporaryDirectory(prefix="video_preview_", dir=str(self.settings.downloads_dir)) as temp_dir:
            temp_path = Path(temp_dir)
            preview_interval = base_interval
            interval_history.append(
                f"Preview pass used about {preview_interval} second spacing to map major changes across the full video."
            )
            preview_frames = await self._extract_preview_frames(
                video_path,
                temp_path,
                preview_interval,
            )
            if not preview_frames:
                return VideoAnalysisResult(
                    interval_history=interval_history,
                    issues=["The bot could not extract preview frames from this video."],
                )

            preview_signals = await self._build_preview_signals(
                preview_frames=preview_frames,
                duration_seconds=duration_seconds,
                transcript_text=transcript_text,
            )

            selected_timestamps, interval_events = await self._build_ai_review_plan(
                preview_frames=preview_frames,
                preview_signals=preview_signals,
                duration_seconds=duration_seconds,
                base_interval=base_interval,
                max_interval=max_interval,
                transcript_text=transcript_text,
            )
            interval_history.extend(interval_events)

            reviewed_media: list[str] = []
            lines: list[str] = []
            for index, timestamp in enumerate(selected_timestamps, start=1):
                frame_path = temp_path / f"review_{index:03d}.jpg"
                try:
                    extracted = await self._extract_single_frame(
                        video_path=video_path,
                        timestamp_seconds=timestamp,
                        output_path=frame_path,
                    )
                    if not extracted:
                        continue
                    description = await asyncio.wait_for(
                        self.vision_analyzer.analyze_image_file(frame_path, use_minimax=True),
                        timeout=30,
                    )
                    reviewed_media.append(f"Video frame at {_format_timecode(timestamp)}")
                    if description:
                        lines.append(f"- **{_format_timecode(timestamp)}**: {description}")
                except asyncio.TimeoutError:
                    issues.append(
                        f"Visual review timed out around {_format_timecode(timestamp)}."
                    )
                except Exception:
                    issues.append(
                        f"The bot could not inspect a frame around {_format_timecode(timestamp)}."
                    )
                finally:
                    if frame_path.exists():
                        frame_path.unlink(missing_ok=True)

        summary_text = ""
        if lines:
            summary_text = (
                "Video visual review:\n"
                f"- Adaptive scan started at {base_interval}-second intervals.\n"
                f"- Calm sections were allowed to stretch up to {max_interval} seconds between detailed reviews.\n"
                "- When the scene stayed stable across repeated checks, the bot could widen the interval gradually instead of forcing the same spacing forever.\n"
                "- Final frame descriptions were generated with MiniMax.\n"
                "- Suspicious changes were revisited with denser local sampling.\n"
                "Key frame notes:\n"
                + "\n".join(lines)
            )
        elif not issues:
            issues.append("No clear visual frame descriptions were produced from the sampled video frames.")

        return VideoAnalysisResult(
            summary_text=summary_text,
            reviewed_media=reviewed_media,
            interval_history=_dedupe_preserve_order(interval_history),
            issues=_dedupe_preserve_order(issues),
        )

    async def _build_preview_signals(
        self,
        *,
        preview_frames: list[_PreviewFrame],
        duration_seconds: float,
        transcript_text: str,
    ) -> list[dict[str, object]]:
        selected_frames = _select_signal_frames(preview_frames)
        signals: list[dict[str, object]] = []
        for frame in selected_frames:
            visual_note = ""
            try:
                visual_note = await asyncio.wait_for(
                    self.vision_analyzer.analyze_image_file(frame.path, use_minimax=False),
                    timeout=20,
                )
            except Exception:
                visual_note = ""
            signals.append(
                {
                    "timestamp_seconds": round(frame.timestamp_seconds, 2),
                    "change_score": round(frame.change_score, 2),
                    "visual_note": visual_note,
                    "transcript_excerpt": _transcript_excerpt_for_timestamp(
                        transcript_text,
                        frame.timestamp_seconds,
                        duration_seconds,
                    ),
                }
            )
        return signals

    async def _build_ai_review_plan(
        self,
        *,
        preview_frames: list[_PreviewFrame],
        preview_signals: list[dict[str, object]],
        duration_seconds: float,
        base_interval: int,
        max_interval: int,
        transcript_text: str,
    ) -> tuple[list[float], list[str]]:
        if self.summarizer is None:
            return _fallback_rule_plan(
                preview_frames=preview_frames,
                duration_seconds=duration_seconds,
                base_interval=base_interval,
                max_interval=max_interval,
            )

        plan = await self.summarizer.plan_video_review(
            duration_seconds=duration_seconds,
            base_interval_seconds=base_interval,
            max_interval_seconds=max_interval,
            transcript_text=transcript_text,
            preview_signals=preview_signals,
        )
        if not plan:
            return _fallback_rule_plan(
                preview_frames=preview_frames,
                duration_seconds=duration_seconds,
                base_interval=base_interval,
                max_interval=max_interval,
            )
        return _timestamps_from_ai_plan(
            plan=plan,
            duration_seconds=duration_seconds,
            base_interval=base_interval,
            max_interval=max_interval,
        )

    async def _probe_duration_seconds(self, video_path: Path) -> float | None:
        command = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "default=noprint_wrappers=1:nokey=1",
            "-show_entries",
            "format=duration",
            str(video_path),
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
            return float(completed.stdout.strip())
        except ValueError:
            return None

    async def _extract_preview_frames(
        self,
        video_path: Path,
        temp_dir: Path,
        interval_seconds: int,
    ) -> list[_PreviewFrame]:
        output_pattern = str(temp_dir / "preview_%05d.jpg")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{max(1, interval_seconds)},scale=240:-1",
            "-q:v",
            "6",
            output_pattern,
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
        except (OSError, subprocess.CalledProcessError):
            return []

        frames = sorted(temp_dir.glob("preview_*.jpg"))
        preview_frames: list[_PreviewFrame] = []
        previous_path: Path | None = None
        for index, frame_path in enumerate(frames):
            timestamp_seconds = float(index * interval_seconds)
            change_score = 0.0
            if previous_path is not None:
                change_score = await asyncio.to_thread(
                    _frame_difference_score,
                    previous_path,
                    frame_path,
                )
            preview_frames.append(
                _PreviewFrame(
                    path=frame_path,
                    timestamp_seconds=timestamp_seconds,
                    change_score=change_score,
                )
            )
            previous_path = frame_path
        return preview_frames

    async def _extract_single_frame(
        self,
        *,
        video_path: Path,
        timestamp_seconds: float,
        output_path: Path,
    ) -> bool:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, timestamp_seconds):.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=960:-1",
            "-q:v",
            "4",
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
        except (OSError, subprocess.CalledProcessError):
            return False
        return output_path.exists()


def _fallback_rule_plan(
    *,
    preview_frames: list[_PreviewFrame],
    duration_seconds: float,
    base_interval: int,
    max_interval: int,
) -> tuple[list[float], list[str]]:
    if not preview_frames:
        return [0.0], [f"No preview frames were available, so the bot fell back to 0 seconds only."]

    selected: list[float] = [0.0]
    suspicious: list[float] = []
    last_selected = 0.0
    interval_events: list[str] = []
    current_target = float(base_interval)
    stable_streak = 0
    low_threshold, medium_threshold, high_threshold = (9.0, 16.0, 24.0)

    for frame in preview_frames[1:]:
        gap = frame.timestamp_seconds - last_selected
        if frame.change_score >= high_threshold:
            selected.append(frame.timestamp_seconds)
            suspicious.append(frame.timestamp_seconds)
            current_target = float(base_interval)
            stable_streak = 0
            interval_events.append(
                f"Strong visual change near {_format_timecode(frame.timestamp_seconds)} triggered a tighter local review from the base interval."
            )
            last_selected = frame.timestamp_seconds
            continue
        if frame.change_score >= medium_threshold and gap >= current_target:
            selected.append(frame.timestamp_seconds)
            current_target = float(base_interval)
            stable_streak = 0
            interval_events.append(
                f"Meaningful change near {_format_timecode(frame.timestamp_seconds)} kept the review close to the {base_interval} second base interval."
            )
            last_selected = frame.timestamp_seconds
            continue
        if frame.change_score <= low_threshold:
            stable_streak += 1
            if stable_streak >= 2 and current_target < max_interval:
                previous_target = current_target
                current_target = min(float(max_interval), current_target + 1.0)
                if current_target != previous_target:
                    interval_events.append(
                        f"Stable stretch through {_format_timecode(frame.timestamp_seconds)} widened the interval from {previous_target:g} to {current_target:g} seconds."
                    )
        else:
            stable_streak = 0
        if gap >= current_target:
            selected.append(frame.timestamp_seconds)
            last_selected = frame.timestamp_seconds

    if duration_seconds > 1:
        selected.append(max(0.0, duration_seconds - 0.5))

    expanded = set()
    for timestamp in selected:
        expanded.add(round(max(0.0, min(duration_seconds, timestamp)), 2))
    for timestamp in suspicious[:8]:
        for offset in (-3.0, -1.5, 1.5, 3.0):
            candidate = max(0.0, min(duration_seconds, timestamp + offset))
            expanded.add(round(candidate, 2))

    ordered = sorted(expanded)
    interval_events.append(
        f"AI planning was unavailable, so the bot temporarily used a fallback adaptive plan and selected {len(ordered)} timestamps."
    )
    return ordered, interval_events


def _timestamps_from_ai_plan(
    *,
    plan: dict[str, object],
    duration_seconds: float,
    base_interval: int,
    max_interval: int,
) -> tuple[list[float], list[str]]:
    ordered: set[float] = {0.0}
    interval_events: list[str] = []

    mode = str(plan.get("mode") or "mixed").strip()
    mode_reason = str(plan.get("mode_reason") or "").strip()
    interval_events.append(
        f"AI-directed review mode: {mode.replace('_', ' ')}." + (f" {mode_reason}" if mode_reason else "")
    )

    coverage_plan = plan.get("coverage_plan")
    if isinstance(coverage_plan, list):
        for item in coverage_plan[:10]:
            if not isinstance(item, dict):
                continue
            start = _clamp_number(item.get("start_seconds"), 0.0, duration_seconds, 0.0)
            end = _clamp_number(item.get("end_seconds"), start, duration_seconds, start)
            interval = _clamp_number(item.get("interval_seconds"), float(base_interval), float(max_interval), float(base_interval))
            interval = _snap_coverage_interval(interval, base_interval, max_interval)
            reason = str(item.get("reason") or "").strip()
            ordered.update(_expand_window(start, end, interval))
            if reason:
                interval_events.append(
                    f"AI coverage window {_format_timecode(start)}-{_format_timecode(end)} at about {interval:g}s: {reason}"
                )

    focus_windows = plan.get("focus_windows")
    if isinstance(focus_windows, list):
        for item in focus_windows[:12]:
            if not isinstance(item, dict):
                continue
            start = _clamp_number(item.get("start_seconds"), 0.0, duration_seconds, 0.0)
            end = _clamp_number(item.get("end_seconds"), start, duration_seconds, start)
            interval = _clamp_number(item.get("interval_seconds"), 0.5, float(max_interval), max(1.0, base_interval / 2))
            interval = _snap_focus_interval(interval, base_interval, max_interval)
            reason = str(item.get("reason") or "").strip()
            ordered.update(_expand_window(start, end, interval))
            if reason:
                interval_events.append(
                    f"AI focus window {_format_timecode(start)}-{_format_timecode(end)} at about {interval:g}s: {reason}"
                )

    if duration_seconds > 1:
        ordered.add(round(max(0.0, duration_seconds - 0.5), 2))
    sorted_times = sorted(ordered)
    interval_events.append(
        f"AI-selected detailed review covers {len(sorted_times)} timestamps after combining broad coverage and focused rewinds."
    )
    return sorted_times, interval_events


def _expand_window(start: float, end: float, interval: float) -> set[float]:
    points: set[float] = set()
    current = start
    while current <= end + 0.001:
        points.add(round(current, 2))
        current += max(0.5, interval)
    points.add(round(end, 2))
    return points


def _snap_coverage_interval(interval: float, base_interval: int, max_interval: int) -> float:
    snapped = round(interval)
    snapped = max(base_interval, min(max_interval, snapped))
    return float(snapped)


def _snap_focus_interval(interval: float, base_interval: int, max_interval: int) -> float:
    step = max(0.5, float(base_interval) / 2.0)
    snapped = round(interval / step) * step
    minimum = step
    snapped = max(minimum, min(float(max_interval), snapped))
    return round(snapped, 2)


def _clamp_number(value: object, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _select_signal_frames(preview_frames: list[_PreviewFrame], max_signals: int = 24) -> list[_PreviewFrame]:
    if len(preview_frames) <= max_signals:
        return preview_frames
    selected: dict[int, _PreviewFrame] = {}
    total = len(preview_frames)
    coverage_count = max(8, max_signals // 2)
    for index in range(coverage_count):
        mapped = round(index * (total - 1) / max(coverage_count - 1, 1))
        selected[mapped] = preview_frames[mapped]
    ranked_changes = sorted(
        enumerate(preview_frames),
        key=lambda item: item[1].change_score,
        reverse=True,
    )
    for index, frame in ranked_changes:
        if len(selected) >= max_signals:
            break
        selected[index] = frame
    return [selected[index] for index in sorted(selected)]


def _transcript_excerpt_for_timestamp(
    transcript_text: str,
    timestamp_seconds: float,
    duration_seconds: float,
    excerpt_chars: int = 260,
) -> str:
    if not transcript_text.strip():
        return ""
    if duration_seconds <= 0:
        return transcript_text[:excerpt_chars]
    position = min(1.0, max(0.0, timestamp_seconds / duration_seconds))
    center = int(len(transcript_text) * position)
    start = max(0, center - excerpt_chars // 2)
    end = min(len(transcript_text), start + excerpt_chars)
    excerpt = transcript_text[start:end].strip()
    return excerpt.replace("\n", " ")


def _frame_difference_score(first_path: Path, second_path: Path) -> float:
    with Image.open(first_path) as first_image, Image.open(second_path) as second_image:
        first = first_image.convert("RGB").resize((128, 128))
        second = second_image.convert("RGB").resize((128, 128))
        difference = ImageChops.difference(first, second)
        stat = ImageStat.Stat(difference)
        return float(sum(stat.mean) / len(stat.mean))


def _format_timecode(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


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
