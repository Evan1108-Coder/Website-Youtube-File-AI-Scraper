from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from pathlib import Path
from statistics import mean

from PIL import ImageStat
from ai_scraper_bot.config import Settings
from ai_scraper_bot.models import VisualInput
from ai_scraper_bot.services.summarizer import LiteLLMSummarizer
from ai_scraper_bot.utils.image_loading import load_image_with_fallback

logger = logging.getLogger(__name__)


class LocalVisionAnalyzer:
    def __init__(self, settings: Settings, summarizer: LiteLLMSummarizer | None = None) -> None:
        self.settings = settings
        self.summarizer = summarizer

    async def analyze_image_file(self, image_path: Path, *, use_minimax: bool = True) -> str:
        if not self.settings.enable_local_vision or not use_minimax:
            return _basic_image_notes(image_path)
        diagnostics = await asyncio.to_thread(_image_diagnostics, image_path)
        try:
            minimax_caption = await self._describe_with_minimax(
                image_path=image_path,
                image_diagnostics=diagnostics.summary,
            )
        except Exception as exc:
            logger.warning("MiniMax vision failed for %s: %s", image_path, exc)
            minimax_caption = ""
        if _looks_like_hallucinated_description(minimax_caption):
            logger.warning("MiniMax vision returned a non-visual response for %s", image_path)
            minimax_caption = ""
        if _looks_like_visual_failure(minimax_caption) and not diagnostics.likely_blank:
            retry_reason = (
                "The first answer suggested the image might be blank or lack visible detail, "
                "but local diagnostics indicate the image has meaningful visual content."
            )
            try:
                retried_caption = await self._describe_with_minimax(
                    image_path=image_path,
                    image_diagnostics=diagnostics.summary,
                    retry_reason=retry_reason,
                )
            except Exception as exc:
                logger.warning("MiniMax vision retry failed for %s: %s", image_path, exc)
                retried_caption = ""
            if _looks_like_hallucinated_description(retried_caption):
                retried_caption = ""
            if retried_caption.strip():
                minimax_caption = retried_caption
        return _combine_analysis_lines(
            notes=_loaded_image_notes(image_path),
            minimax_caption=minimax_caption,
        )

    async def _describe_with_minimax(
        self,
        *,
        image_path: Path,
        image_diagnostics: str = "",
        retry_reason: str = "",
    ) -> str:
        if self.summarizer is None:
            return ""
        visual_input = await asyncio.to_thread(_build_visual_input, image_path)
        if visual_input is None:
            return ""
        return await self.summarizer.describe_visual_input(
            visual_input=visual_input,
            image_diagnostics=image_diagnostics,
            retry_reason=retry_reason,
        )


def _combine_analysis_lines(
    *,
    notes: list[str],
    minimax_caption: str,
) -> str:
    lines = [note for note in notes if note.strip()]
    if minimax_caption.strip():
        lines.append(f"Visual description: {minimax_caption.strip()}")
    return "\n".join(lines).strip()

def _loaded_image_notes(image_path: Path) -> list[str]:
    return list(load_image_with_fallback(image_path).notes)


def _basic_image_notes(image_path: Path) -> str:
    notes = _loaded_image_notes(image_path)
    return "\n".join(note for note in notes if note.strip()).strip()


class _ImageDiagnostics:
    def __init__(self, summary: str, likely_blank: bool) -> None:
        self.summary = summary
        self.likely_blank = likely_blank


def _image_diagnostics(image_path: Path) -> _ImageDiagnostics:
    loaded = load_image_with_fallback(image_path)
    image = loaded.image
    rgb_image = image.convert("RGB")
    stat = ImageStat.Stat(rgb_image)
    channel_means = stat.mean[:3]
    channel_stdevs = stat.stddev[:3]
    average_brightness = mean(channel_means)
    average_variation = mean(channel_stdevs)
    width, height = rgb_image.size
    likely_blank = average_brightness < 8 and average_variation < 4
    summary = (
        f"image size {width}x{height}; average brightness {average_brightness:.1f}/255; "
        f"average variation {average_variation:.1f}/255; likely blank: {'yes' if likely_blank else 'no'}"
    )
    return _ImageDiagnostics(summary=summary, likely_blank=likely_blank)


def _looks_like_visual_failure(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    suspicious_phrases = (
        "blank image",
        "black image",
        "completely black",
        "entirely black",
        "appears black",
        "appears blank",
        "looks blank",
        "looks black",
        "no visible detail",
        "no clear visual detail",
        "no discernible detail",
        "cannot identify any objects",
        "unable to determine any content",
        "too dark to identify",
    )
    return any(phrase in lowered for phrase in suspicious_phrases)


def _looks_like_hallucinated_description(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    suspicious_phrases = (
        "image_not_visible",
        "i cannot see the image",
        "i can't see the image",
        "i cannot view the image",
        "i can't view the image",
        "as an ai",
        "as a language model",
        "i do not have the ability to see",
        "i don't have the ability to see",
        "cannot directly access the image",
        "can't directly access the image",
    )
    return any(phrase in lowered for phrase in suspicious_phrases)


def _build_visual_input(image_path: Path) -> VisualInput | None:
    loaded = load_image_with_fallback(image_path)
    data_uri = _image_to_data_uri(loaded.image, image_path.suffix.lower())
    if not data_uri:
        return None
    return VisualInput(
        kind="image_data",
        value=data_uri,
        label=image_path.name,
    )


def _image_to_data_uri(image, extension: str) -> str:
    import io

    output = io.BytesIO()
    preview = image.copy()
    preview.thumbnail((1024, 1024))
    format_name = "PNG" if extension in {".png", ".avif"} else "JPEG"
    mime_type = "image/png" if format_name == "PNG" else (mimetypes.guess_type(f"image{extension}")[0] or "image/jpeg")
    if format_name == "JPEG" and preview.mode not in {"RGB", "L"}:
        preview = preview.convert("RGB")
    preview.save(output, format=format_name, optimize=True, quality=85)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
