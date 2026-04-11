from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path
import re

import litellm

logger = logging.getLogger(__name__)

from ai_scraper_bot.models import VisualInput
from ai_scraper_bot.config import Settings
from ai_scraper_bot.prompts import (
    CHAT_SYSTEM_PROMPT,
    SOURCE_ANALYSIS_SYSTEM_PROMPT,
    build_chat_user_prompt,
    build_source_analysis_user_prompt,
)


class SummarizerError(RuntimeError):
    pass


MiniMaxHTTPSummarizer = None  # removed; use LiteLLMSummarizer


class LiteLLMSummarizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def describe_visual_input(
        self,
        *,
        visual_input: VisualInput,
        response_language: str = "english",
        local_caption: str = "",
        object_summary: str = "",
        image_diagnostics: str = "",
        retry_reason: str = "",
    ) -> str:
        if not self.settings.llm_vision_model:
            return ""

        hint_lines: list[str] = []
        if local_caption.strip():
            hint_lines.append(f"- Supporting caption hint: {local_caption.strip()}")
        if object_summary.strip():
            hint_lines.append(f"- Supporting object hint: {object_summary.strip()}")
        if image_diagnostics.strip():
            hint_lines.append(f"- Local image diagnostics: {image_diagnostics.strip()}")
        if retry_reason.strip():
            hint_lines.append(f"- Recheck reason: {retry_reason.strip()}")
        hints = "\n".join(hint_lines) if hint_lines else "- No local hints were available."
        prompt = (
            f"Describe this image in {response_language}. "
            "Be literal, conservative, and grounded only in what is directly visible. "
            "Do not invent story details, relationships, events, intentions, identities, emotions, or off-frame context. "
            "Do not claim the image is blank, black, empty, unreadable, or lacking visible detail unless that is clearly true. "
            "Use the local hints only as hints to verify or correct, not as guaranteed facts.\n\n"
            f"Local hints:\n{hints}\n\n"
            "If you genuinely cannot see or interpret the image, return exactly: IMAGE_NOT_VISIBLE\n"
            "Return exactly these four short lines and nothing else:\n"
            "Main subject: ...\n"
            "Setting/background: ...\n"
            "Visible details: ...\n"
            "Uncertainty: ...\n"
            "If something is unclear, say uncertain instead of guessing."
        )
        content = _build_multimodal_content(prompt, [visual_input])
        try:
            return await self._complete(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a careful image description assistant. Be literal, concise, and do not speculate.",
                    },
                    {
                        "role": "user",
                        "content": content,
                    },
                ],
                temperature=0.2,
                model_name=self.settings.llm_vision_model,
            )
        except Exception as exc:
            logger.warning(
                "Vision call failed with model %s: %s",
                self.settings.llm_vision_model,
                exc,
            )
            if self.settings.llm_vision_model == self.settings.llm_model:
                return ""
            try:
                return await self._complete(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a careful image description assistant. Be literal, concise, and do not speculate.",
                        },
                        {
                            "role": "user",
                            "content": content,
                        },
                    ],
                    temperature=0.2,
                    model_name=self.settings.llm_model,
                )
            except Exception as fallback_exc:
                logger.warning(
                    "Vision fallback also failed with model %s: %s",
                    self.settings.llm_model,
                    fallback_exc,
                )
                return ""

    async def analyze_source(
        self,
        title: str,
        source_label: str,
        body: str,
        response_language: str,
        user_request: str = "",
        metadata: dict[str, str] | None = None,
        recent_context: str = "",
        visual_inputs: list[VisualInput] | None = None,
        issues: list[str] | None = None,
        runtime_diary: list[str] | None = None,
        reviewed_media: list[str] | None = None,
        video_interval_history: list[str] | None = None,
        related_urls: list[str] | None = None,
    ) -> str:
        if not self.settings.llm_model:
            raise SummarizerError(
                "No LLM model configured. Set LLM_MODEL in .env (e.g. gpt-4o, claude-sonnet-4-6)."
            )

        analysis_temperature = _analysis_temperature(metadata)
        content = _build_multimodal_content(
            text=build_source_analysis_user_prompt(
                title=title,
                source_label=source_label,
                body=_prepare_source_body(body, user_request),
                response_language=response_language,
                user_request=user_request,
                metadata=metadata,
                recent_context=recent_context,
                issues=issues,
                runtime_diary=runtime_diary,
                reviewed_media=reviewed_media,
                video_interval_history=video_interval_history,
                related_urls=related_urls,
            ),
            visual_inputs=visual_inputs or [],
        )
        messages = [
            {"role": "system", "content": SOURCE_ANALYSIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": content,
            },
        ]
        return await self._complete_with_visual_fallback(
            messages=messages,
            fallback_text=build_source_analysis_user_prompt(
                title=title,
                source_label=source_label,
                body=_prepare_source_body(body, user_request),
                response_language=response_language,
                user_request=user_request,
                metadata=metadata,
                recent_context=recent_context,
                issues=issues,
                runtime_diary=runtime_diary,
                reviewed_media=reviewed_media,
                video_interval_history=video_interval_history,
                related_urls=related_urls,
            ),
            temperature=analysis_temperature,
            had_visuals=bool(visual_inputs),
            model_name=self.settings.llm_vision_model if visual_inputs else self.settings.llm_model,
        )

    async def chat(
        self,
        user_message: str,
        response_language: str,
        recent_context: str = "",
        visual_inputs: list[VisualInput] | None = None,
        runtime_diary: list[str] | None = None,
        quoted_input_mode: bool = False,
    ) -> str:
        if not self.settings.llm_model:
            raise SummarizerError(
                "No LLM model configured. Set LLM_MODEL in .env (e.g. gpt-4o, claude-sonnet-4-6)."
            )

        content = _build_multimodal_content(
            text=build_chat_user_prompt(
                user_message=user_message,
                response_language=response_language,
                recent_context=recent_context,
                runtime_diary=runtime_diary,
                quoted_input_mode=quoted_input_mode,
            ),
            visual_inputs=visual_inputs or [],
        )
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": content,
            },
        ]
        return await self._complete_with_visual_fallback(
            messages=messages,
            fallback_text=build_chat_user_prompt(
                user_message=user_message,
                response_language=response_language,
                recent_context=recent_context,
                runtime_diary=runtime_diary,
                quoted_input_mode=quoted_input_mode,
            ),
            temperature=0.5,
            had_visuals=bool(visual_inputs),
            model_name=self.settings.llm_vision_model if visual_inputs else self.settings.llm_model,
        )

    async def plan_video_review(
        self,
        *,
        duration_seconds: float,
        base_interval_seconds: int,
        max_interval_seconds: int,
        transcript_text: str,
        preview_signals: list[dict[str, object]],
    ) -> dict[str, object] | None:
        if not self.settings.llm_model:
            return None

        transcript_excerpt = transcript_text[:12000].strip() or "No transcript text available."
        signal_json = json.dumps(preview_signals, ensure_ascii=False)
        prompt = f"""Create a JSON-only adaptive video review plan.

Goal:
- Decide how the bot should combine audio/transcript importance and visual importance.
- Do not use a fixed frame cap strategy.
- Use the transcript and preview frame signals to decide where visual review should stay sparse and where it should zoom in.
- For talking-head interviews or speech-heavy videos, do not overreact to normal face movement or ordinary camera cuts.
- For art shows, demos, or visual-heavy videos, keep more visual attention.

Return JSON only with this exact shape:
{{
  "mode": "speech_heavy" | "mixed" | "visual_heavy",
  "mode_reason": "short sentence",
  "coverage_plan": [
    {{"start_seconds": 0, "end_seconds": 120, "interval_seconds": 8, "reason": "..." }}
  ],
  "focus_windows": [
    {{"start_seconds": 110, "end_seconds": 126, "interval_seconds": 1.5, "reason": "..." }}
  ]
}}

Rules:
- The bot starts from a base interval of {base_interval_seconds} seconds.
- The maximum calm-section interval is {max_interval_seconds} seconds.
- Coverage-plan intervals may widen gradually in small sensible steps when the video stays visually stable. For example, a base interval of 3 can later widen to 4, then 5, instead of only jumping in large rigid steps.
- Focus-window intervals should stay sensible and small, but they do not need to follow rigid multiples if a slightly different value better fits the evidence.
- Coverage plan should describe broader scanning windows across the video.
- Focus windows are for places that deserve denser review and local rewind.
- Keep coverage_plan to at most 10 windows.
- Keep focus_windows to at most 12 windows.
- Intervals must be positive and reasonable.
- Prefer fewer, smarter windows over noisy micromanagement.
- If transcript or audio guidance is weak, unavailable, or clearly unhelpful, rely more on visual novelty without pretending that strong audio guidance exists.
- If transcript guidance is strong and the visuals mostly show a stable talking-head scene, widen intervals instead of reacting to ordinary face or body motion.
- If the preview signals show repeated stability across several early checks, it is good to widen the interval progressively instead of staying stuck at the base interval forever.
- JSON only. No markdown. No explanation outside JSON.

Video duration seconds: {duration_seconds}

Transcript excerpt:
{transcript_excerpt}

Preview signals:
{signal_json}
"""
        try:
            response_text = await self._complete(
                messages=[
                    {"role": "system", "content": "You design adaptive multimodal video review plans and respond with strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                model_name=self.settings.llm_model,
            )
        except SummarizerError:
            return None
        return _extract_json_object(response_text)

    async def _complete_with_visual_fallback(
        self,
        *,
        messages: list[dict[str, object]],
        fallback_text: str,
        temperature: float,
        had_visuals: bool,
        model_name: str,
    ) -> str:
        try:
            return await self._complete(messages=messages, temperature=temperature, model_name=model_name)
        except SummarizerError:
            if not had_visuals:
                raise
            if model_name != self.settings.llm_model:
                try:
                    return await self._complete(
                        messages=messages,
                        temperature=temperature,
                        model_name=self.settings.llm_model,
                    )
                except SummarizerError:
                    pass
            fallback_messages = [
                messages[0],
                {"role": "user", "content": fallback_text},
            ]
            return await self._complete(
                messages=fallback_messages,
                temperature=temperature,
                model_name=self.settings.llm_model,
            )

    async def _complete(self, messages: list[dict[str, object]], temperature: float, model_name: str | None = None) -> str:
        model = model_name or self.settings.llm_model
        kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "timeout": 120.0,
        }

        if model.startswith("minimax/"):
            if self.settings.minimax_api_key:
                kwargs["api_key"] = self.settings.minimax_api_key
            if self.settings.minimax_api_url:
                base = self.settings.minimax_api_url
                for suffix in ("/chat/completions", "/text/chatcompletion", "/text/chatcompletion_v2"):
                    if base.endswith(suffix):
                        base = base[: -len(suffix)]
                        break
                kwargs["api_base"] = base.rstrip("/")
                kwargs["model"] = f"openai/{model.removeprefix('minimax/')}"

        try:
            response = await litellm.acompletion(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            raise SummarizerError(f"LLM request failed ({model}): {exc}") from exc

        content = response.choices[0].message.content or ""
        if not content:
            raise SummarizerError(f"LLM returned an empty response ({model}).")
        cleaned = _sanitize_model_output(content)
        if not cleaned:
            raise SummarizerError(f"LLM returned empty visible content after cleanup ({model}).")
        return cleaned



def _sanitize_model_output(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?think>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_json_object(text: str) -> dict[str, object] | None:
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _build_multimodal_content(
    text: str, visual_inputs: list[VisualInput]
) -> str | list[dict[str, object]]:
    """Build OpenAI-compatible multimodal content.

    Returns a plain string when there are no visuals, or a list of content
    parts (text + image_url objects) when visuals are present.  This is the
    standard format used by LiteLLM across all providers.
    """
    if not visual_inputs:
        return text

    parts: list[dict[str, object]] = [{"type": "text", "text": text}]
    for visual in visual_inputs[:4]:
        image_url = _visual_to_url(visual)
        if not image_url:
            continue
        parts.append({
            "type": "image_url",
            "image_url": {"url": image_url},
        })
    return parts if len(parts) > 1 else text


def _visual_to_url(visual: VisualInput) -> str | None:
    if visual.kind == "image_url":
        return visual.value
    if visual.kind == "image_data":
        if visual.value.startswith("data:"):
            return visual.value
        path = Path(visual.value)
        if not path.exists():
            return None
        mime_type, _ = mimetypes.guess_type(path.name)
        mime_type = mime_type or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
    return None


def _looks_like_multimodal_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "image_url",
            "invalid chat format",
            "invalid type",
            "unsupported",
            "multimodal",
            "vision",
            "content format",
            "invalid content",
            "does not support",
            "not support image",
            "invalid_request_error",
            "content must be",
            "invalid message format",
        )
    )



def _prepare_source_body(body: str, user_request: str, max_chars: int = 120_000) -> str:
    if len(body) <= max_chars:
        return body

    chunks = _chunk_text(body, chunk_size=5000, overlap=500)
    query_terms = _keywords(user_request)
    summary_like_request = _looks_like_summary_request(user_request)

    selected_by_index: dict[int, str] = {}

    for index in _coverage_indices(len(chunks), desired=min(10, len(chunks))):
        selected_by_index[index] = chunks[index]

    for index, chunk in _top_fact_chunks(chunks, limit=min(8, len(chunks))):
        selected_by_index[index] = chunk

    if query_terms and not summary_like_request:
        for index, chunk in _top_query_chunks(chunks, query_terms, limit=min(8, len(chunks))):
            selected_by_index[index] = chunk

    if not selected_by_index:
        for index, chunk in enumerate(chunks[:8]):
            selected_by_index[index] = chunk

    combined = "\n\n".join(selected_by_index[index] for index in sorted(selected_by_index))
    return combined[:max_chars]


def _analysis_temperature(metadata: dict[str, str] | None) -> float:
    source_type = (metadata or {}).get("type", "").lower()
    if source_type == "youtube":
        return 0.32
    if source_type in {"website", "file"}:
        return 0.38
    return 0.45


def _keywords(text: str) -> list[str]:
    return [token for token in re.findall(r"[\w\u3400-\u9fff]+", text.lower()) if len(token) > 1]


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _looks_like_summary_request(text: str) -> bool:
    lowered = text.lower()
    summary_markers = (
        "summarize",
        "summary",
        "brief summary",
        "give me a summary",
        "overview",
        "recap",
        "总结",
        "概括",
        "摘要",
        "总结一下",
        "概述",
    )
    return not lowered.strip() or any(marker in lowered for marker in summary_markers)


def _coverage_indices(total: int, desired: int) -> list[int]:
    if total <= 0:
        return []
    if total <= desired:
        return list(range(total))
    if desired <= 1:
        return [0]
    indices = {0, total - 1}
    for step in range(desired):
        index = round(step * (total - 1) / (desired - 1))
        indices.add(index)
    return sorted(indices)


def _top_fact_chunks(chunks: list[str], limit: int) -> list[tuple[int, str]]:
    scored: list[tuple[int, int, str]] = []
    for index, chunk in enumerate(chunks):
        score = _fact_score(chunk)
        if index == 0:
            score += 1
        scored.append((score, index, chunk))
    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return [(index, chunk) for score, index, chunk in scored[:limit] if score > 0]


def _top_query_chunks(chunks: list[str], query_terms: list[str], limit: int) -> list[tuple[int, str]]:
    scored: list[tuple[int, int, str]] = []
    for index, chunk in enumerate(chunks):
        score = 0
        lowered = chunk.lower()
        for term in query_terms:
            if term in lowered:
                score += 3
        score += _fact_score(chunk)
        if index == 0:
            score += 1
        scored.append((score, index, chunk))
    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return [(index, chunk) for score, index, chunk in scored[:limit] if score > 0]


def _fact_score(chunk: str) -> int:
    lowered = chunk.lower()
    score = 0
    year_hits = re.findall(r"\b(?:1[6-9]\d{2}|20\d{2}|2100)\b", chunk)
    number_hits = re.findall(r"\b\d[\d,.\-:/%]*\b", chunk)
    heading_hits = re.findall(r"(?m)^(?:#{1,6}\s+.+|[A-Z][^\n]{0,80}:)$", chunk)
    proper_like_hits = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b", chunk)
    if year_hits:
        score += min(len(year_hits), 6) * 2
    if number_hits:
        score += min(len(number_hits), 8)
    if heading_hits:
        score += min(len(heading_hits), 4) * 2
    if proper_like_hits:
        score += min(len(proper_like_hits), 6)
    for token in (
        "table",
        "timeline",
        "history",
        "historical",
        "founded",
        "born",
        "died",
        "population",
        "date",
        "page ",
        "chapter",
        "section",
        "artwork",
        "figure",
        "chart",
        "total",
        "percent",
    ):
        if token in lowered:
            score += 1
    return score
