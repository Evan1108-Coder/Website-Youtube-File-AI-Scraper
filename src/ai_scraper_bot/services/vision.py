from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ai_scraper_bot.config import Settings
from ai_scraper_bot.utils.image_loading import load_image_with_fallback

logger = logging.getLogger(__name__)


class VisionAnalysisError(RuntimeError):
    pass


class LocalVisionAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._caption_pipeline = None
        self._detection_pipeline = None
        self._caption_disabled_reason: str | None = None
        self._detection_disabled_reason: str | None = None

    async def analyze_image_file(self, image_path: Path) -> str:
        if not self.settings.enable_local_vision:
            return ""
        try:
            caption_pipeline, detection_pipeline = await self._ensure_pipelines()
        except VisionAnalysisError as exc:
            logger.warning("Local vision unavailable: %s", exc)
            return ""

        return await asyncio.to_thread(
            self._analyze_sync,
            image_path,
            caption_pipeline,
            detection_pipeline,
        )

    async def _ensure_pipelines(self):
        try:
            from transformers import pipeline
        except Exception as exc:  # pragma: no cover
            reason = (
                "transformers/torch are not installed. Install them from requirements.txt to enable local vision."
            )
            raise VisionAnalysisError(reason) from exc

        if self._caption_pipeline is None and self._caption_disabled_reason is None:
            try:
                self._caption_pipeline = await asyncio.to_thread(
                    _build_caption_pipeline,
                    pipeline,
                    self.settings.vision_caption_model,
                )
            except Exception as exc:  # pragma: no cover
                self._caption_disabled_reason = (
                    "could not load the local image-captioning model. "
                    "Please reinstall the pinned torch/transformers versions from requirements.txt. "
                    f"Original error: {exc}"
                )
                logger.warning("Image caption pipeline unavailable: %s", self._caption_disabled_reason)

        if self._detection_pipeline is None and self._detection_disabled_reason is None:
            try:
                self._detection_pipeline = await asyncio.to_thread(
                    pipeline,
                    "object-detection",
                    model=self.settings.vision_object_model,
                )
            except Exception as exc:  # pragma: no cover
                self._detection_disabled_reason = (
                    "object detection is unavailable. "
                    "Install `timm` and restart the bot if you want object detection too. "
                    f"Original error: {exc}"
                )
                logger.warning("Object detection pipeline unavailable: %s", self._detection_disabled_reason)

        if self._caption_pipeline is None and self._detection_pipeline is None:
            reasons = [reason for reason in (self._caption_disabled_reason, self._detection_disabled_reason) if reason]
            raise VisionAnalysisError(" ".join(reasons) or "No local vision pipelines are available.")

        return self._caption_pipeline, self._detection_pipeline

    def _analyze_sync(self, image_path: Path, caption_pipeline, detection_pipeline) -> str:
        loaded = load_image_with_fallback(image_path)
        image = loaded.image
        lines: list[str] = []
        lines.extend(loaded.notes)

        if caption_pipeline is not None:
            try:
                caption_result = caption_pipeline(image)
                caption = _extract_caption(caption_result)
                if caption:
                    lines.append(f"Visual description: {caption}")
            except Exception as exc:
                logger.warning("Image captioning failed for %s: %s", image_path, exc)

        if detection_pipeline is not None:
            try:
                detection_result = detection_pipeline(image)
                object_summary = _summarize_detections(detection_result)
                if object_summary:
                    lines.append(f"Detected objects: {object_summary}")
            except Exception as exc:
                logger.warning("Object detection failed for %s: %s", image_path, exc)

        return "\n".join(lines).strip()


def _extract_caption(result) -> str:
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            return str(first.get("generated_text", "")).strip()
    return ""


def _summarize_detections(result) -> str:
    if not isinstance(result, list):
        return ""
    labels: list[str] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        score = float(item.get("score", 0))
        label = str(item.get("label", "")).strip()
        if score >= 0.45 and label:
            labels.append(label)
    if not labels:
        return ""
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(
        f"{label} x{count}" if count > 1 else label for label, count in ordered[:8]
    )


def _build_caption_pipeline(pipeline, model_name: str):
    errors = []
    for task_name in ("image-to-text", "image-text-to-text"):
        try:
            return pipeline(task_name, model=model_name)
        except Exception as exc:
            errors.append(f"{task_name}: {exc}")
    raise RuntimeError("; ".join(errors))
