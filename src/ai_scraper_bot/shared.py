from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
import random
from typing import Literal
from urllib.parse import urlparse

from ai_scraper_bot.models import JobSource
from ai_scraper_bot.parsers.file_parser import AUDIO_TYPES, SUPPORTED_FILE_TYPES, VIDEO_TYPES
from ai_scraper_bot.utils.runtime_diary import get_recent_runtime_diary

Language = Literal["english", "chinese"]
URL_PATTERN = re.compile(r"https?://\S+")
CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
LANGUAGE_HINTS = {
    "english": ("reply in english", "answer in english", "use english", "英文"),
    "chinese": ("reply in chinese", "answer in chinese", "use chinese", "中文", "请用中文"),
}
WEBSITE_EXTRACT_TIMEOUT_SECONDS = 75
FILE_PARSE_TIMEOUT_SECONDS = 120
SUMMARY_TIMEOUT_SECONDS = 180


def classify_source(raw: str) -> JobSource:
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        if parsed.hostname and (
            "youtube.com" in parsed.hostname or "youtu.be" in parsed.hostname
        ):
            return JobSource(kind="youtube", value=raw)
        return JobSource(kind="website", value=raw)
    raise ValueError("The request must be a supported URL or an uploaded file.")


def _extract_first_url(text: str) -> str | None:
    match = URL_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).rstrip(").,!?]>")


def _should_treat_message_as_source(text: str, url: str | None) -> bool:
    if not url:
        return False
    if _should_treat_user_message_as_quoted_text(text):
        return False
    if len(re.findall(r"https?://\S+", text)) >= 2 and "summar" not in text.lower():
        return False
    return True


def _looks_like_runtime_diary_or_error_dump(text: str) -> bool:
    lowered = text.lower()
    log_keywords = (
        "traceback",
        "http request:",
        "warning ",
        " error",
        " info ",
        "ai_scraper_bot",
        "socket.gaierror",
        "clientconnectordnserror",
        "terminal diary",
        "runtime diary",
        "here is the diary",
        "here is the log",
        "paste the diary",
        "paste the log",
        "should_reply=",
        "has_url=",
        "has_attachments=",
        "author=",
        "channel=",
        "dm=",
        "content=",
    )
    if any(keyword in lowered for keyword in log_keywords):
        return True
    if re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 3:
        logish_lines = 0
        for line in lines:
            if re.match(r"^\d{4}-\d{2}-\d{2}", line):
                logish_lines += 1
            elif any(marker in line for marker in ("INFO", "WARNING", "ERROR", "Traceback")):
                logish_lines += 1
        if logish_lines >= 2:
            return True
    return False


def _should_treat_user_message_as_quoted_text(text: str) -> bool:
    return _looks_like_runtime_diary_or_error_dump(text) or _looks_like_terminal_or_quoted_block(text)


def _looks_like_terminal_or_quoted_block(text: str) -> bool:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    shellish_lines = 0
    quoted_instruction_lines = 0
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
        if re.match(r"^(?:\$|#|%|>)\s+\S+", stripped):
            shellish_lines += 1
            continue
        if re.match(r"^(?:cd|ls|pwd|python(?:3)?|pip|ffmpeg|ffprobe|curl|source|export|pytest|git)\b", lowered):
            shellish_lines += 1
            continue
        if 'content="' in line or "content='" in line:
            quoted_instruction_lines += 1
            continue
        if any(marker in lowered for marker in ("reply=true", "reply=false", "should_reply=", "has_url=", "has_attachments=")):
            quoted_instruction_lines += 1

    if shellish_lines >= 2:
        return True
    if quoted_instruction_lines >= 1 and len(lines) >= 2:
        return True
    return False


def _preferred_language(text: str) -> Language:
    lowered = text.lower()
    for language, markers in LANGUAGE_HINTS.items():
        if any(marker in lowered or marker in text for marker in markers):
            return language  # type: ignore[return-value]
    if CHINESE_PATTERN.search(text):
        return "chinese"
    return "english"


def _language_label(language: Language) -> str:
    return "Chinese" if language == "chinese" else "English"


def _file_parse_timeout_seconds(filename: str) -> float:
    extension = Path(filename).suffix.lower()
    if extension in VIDEO_TYPES:
        return 900.0
    if extension in AUDIO_TYPES:
        return 600.0
    return float(FILE_PARSE_TIMEOUT_SECONDS)


def _should_use_source_follow_up(prompt: str) -> bool:
    lowered = prompt.lower()
    trigger_phrases = (
        "what",
        "which",
        "where",
        "when",
        "who",
        "why",
        "how",
        "list",
        "find",
        "show",
        "tell me",
        "page",
        "table",
        "chart",
        "image",
        "picture",
        "photo",
        "art",
        "video",
        "pdf",
        "document",
        "translate",
        "brief",
        "detail",
        "details",
        "specific",
        "summar",
        "explain",
        "scenario",
        "tier",
        "fallback",
        "deepgram",
        "whisper",
        "transcript",
        "subtitle",
        "subtitles",
        "cookie",
        "cookies",
        "分析",
        "总结",
        "表格",
        "图片",
        "照片",
        "这份",
        "这个文件",
        "这个网页",
        "这个视频",
        "这一页",
        "方案",
        "场景",
        "回退",
        "转录",
        "字幕",
        "cookie",
    )
    return any(phrase in lowered or phrase in prompt for phrase in trigger_phrases)


def _prepend_extraction_status(summary: str, extracted, language: Language) -> str:
    tier = extracted.metadata.get("tier", "").strip()
    internal_facts = _status_internal_fact_lines(extracted.metadata)
    if extracted.metadata.get("type", "").strip() != "youtube":
        return summary
    if not tier and not extracted.issues and not internal_facts:
        return summary
    if language == "chinese":
        heading = "**提取状态**"
        lines = [heading]
        if tier:
            lines.append(f"- 实际成功使用的路径：`{tier}`")
        lines.extend(internal_facts)
        if extracted.issues:
            lines.append("- 阶段说明：")
            lines.extend(f"  - {item}" for item in extracted.issues[:6])
    else:
        heading = "**Extraction Status**"
        lines = [heading]
        if tier:
            lines.append(f"- Actual successful path used: `{tier}`")
        lines.extend(internal_facts)
        if extracted.issues:
            lines.append("- Stage notes:")
            lines.extend(f"  - {item}" for item in extracted.issues[:6])
    status_block = "\n".join(lines).strip()
    if not summary.strip():
        return status_block
    return f"{status_block}\n\n{summary}"


def _build_source_fallback_summary(*, language: Language, extracted, reason: str) -> str:
    preview = extracted.body.strip()
    if len(preview) > 3000:
        preview = preview[:3000].rstrip() + "..."
    tier = extracted.metadata.get("tier", "unknown")
    issues = extracted.issues[:6]
    diary_lines = extracted.runtime_diary[:6]
    internal_facts = _status_internal_fact_lines(extracted.metadata)
    clean_reason = (reason or "").strip() or "The summarizer did not return a visible error message."
    if language == "chinese":
        lines = [
            "**临时回退结果**",
            f"- 标题：{extracted.title}",
            f"- 来源：{extracted.source_label}",
            f"- 当前已知路径：`{tier}`",
            f"- 生成完整总结时发生的问题：{clean_reason}",
        ]
        lines.extend(internal_facts)
        if issues:
            lines.append("- 当前已知阶段说明：")
            lines.extend(f"  - {item}" for item in issues)
        if diary_lines:
            lines.append("- 最近终端日志：")
            lines.extend(f"  - {item}" for item in diary_lines)
        if preview:
            lines.extend(["", "**已提取内容预览**", preview])
        return "\n".join(lines).strip()

    lines = [
        "**Temporary Fallback Result**",
        f"- Title: {extracted.title}",
        f"- Source: {extracted.source_label}",
        f"- Best-known extraction path: `{tier}`",
        f"- What happened while generating the full summary: {clean_reason}",
    ]
    lines.extend(internal_facts)
    if issues:
        lines.append("- Current stage notes:")
        lines.extend(f"  - {item}" for item in issues)
    if diary_lines:
        lines.append("- Recent terminal diary:")
        lines.extend(f"  - {item}" for item in diary_lines)
    if preview:
        lines.extend(["", "**Extracted Content Preview**", preview])
    return "\n".join(lines).strip()


def _status_internal_fact_lines(metadata: dict[str, str]) -> list[str]:
    pairs = []
    media_kind = metadata.get("media_kind", "").strip()
    if media_kind:
        pairs.append(("Media kind", media_kind))
    music_detected = metadata.get("music_detected", "").strip()
    if music_detected:
        pairs.append(("Music detected", music_detected))
    music_attempted = metadata.get("music_libraries_attempted", "").strip()
    if music_attempted:
        pairs.append(("Music libraries attempted", music_attempted))
    music_output = metadata.get("music_libraries_with_output", "").strip()
    if music_output:
        pairs.append(("Music libraries with output", music_output))
    youtube_source = metadata.get("youtube_metadata_source", "").strip()
    if youtube_source:
        pairs.append(("YouTube metadata source", youtube_source))
    youtube_attempt_order = metadata.get("youtube_attempt_order", "").strip()
    if youtube_attempt_order:
        pairs.append(("YouTube transcript attempt order", youtube_attempt_order))
    return [f"- {label}: `{value}`" for label, value in pairs]


def _runtime_diary_for_prompt(prompt: str) -> list[str]:
    if not _wants_runtime_diary(prompt):
        return []
    prompt_keywords = [item for item in re.findall(r"[A-Za-z0-9_.:/-]+", prompt) if len(item) >= 4][:8]
    return get_recent_runtime_diary(
        limit=10,
        keywords=prompt_keywords,
        logger_prefixes=("ai_scraper_bot", "httpx"),
    )


def _wants_runtime_diary(prompt: str) -> bool:
    lowered = prompt.lower()
    markers = (
        "error",
        "problem",
        "issue",
        "log",
        "logs",
        "diary",
        "terminal",
        "traceback",
        "warning",
        "why did",
        "why does",
        "failed",
        "failure",
        "bug",
        "错误",
        "问题",
        "日志",
        "终端",
        "报错",
        "失败",
        "为什么",
    )
    return any(marker in lowered or marker in prompt for marker in markers)


def _reply_text(language: Language, key: str, **kwargs: str) -> str:
    templates = {
        "english": {
            "help": (
                "I can analyze websites, YouTube videos, images, and supported files. "
                "Send me a link, upload a file, or just ask naturally."
            ),
        },
        "chinese": {
            "help": "我可以分析网站、YouTube 视频、图片和支持的文件。你直接发链接、上传文件，或者自然地问我就可以。",
        },
    }
    chosen = templates[language][key]
    if isinstance(chosen, list):
        return random.choice(chosen)
    return chosen.format(**kwargs)


def _local_fast_reply(prompt: str, language: Language) -> str | None:
    lowered = prompt.strip().lower()
    normalized = re.sub(r"[^\w\u3400-\u9fff\s]", "", lowered).strip()
    if not normalized:
        return None

    greetings = {
        "hello",
        "hi",
        "hey",
        "hello again",
        "hey there",
        "ping",
        "yo",
        "你好",
        "嗨",
        "哈喽",
        "哈囉",
        "在吗",
        "在嗎",
    }
    if normalized in greetings:
        return (
            "I’m here. Send me a link, a file, or a question and I’ll jump in."
            if language == "english"
            else "我在。你直接发链接、文件，或者直接问我就可以。"
        )

    if any(phrase in lowered for phrase in ("are you online", "are you there", "you online", "still there")):
        return (
            "Yes, I’m here and ready. Source analysis takes longer, but simple chat should be quicker now."
            if language == "english"
            else "我在，而且已经准备好了。内容分析会慢一些，但普通聊天现在应该会更快。"
        )

    if any(phrase in lowered for phrase in ("what can you do", "what do you do", "help")):
        return _reply_text(language, "help")

    if any(
        phrase in lowered
        for phrase in (
            "quicker next time",
            "faster next time",
            "be quicker",
            "be faster",
            "too slow",
            "so slow",
            "why so slow",
            "can you do it quicker",
            "快一点",
            "太慢了",
            "能快一点吗",
            "能快一點嗎",
        )
    ):
        return (
            "Yes. I’ll keep simple chat replies local when I can, and save the heavier model calls for real analysis."
            if language == "english"
            else "可以。我会尽量把简单聊天放在本地快速回复，把真正需要的分析再交给模型。"
        )

    return None
