from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import logging
import random
import re
from time import time
from typing import Literal
from uuid import uuid4
from urllib.parse import urlparse

import discord
from discord.ext import commands

from ai_scraper_bot.config import Settings
from ai_scraper_bot.models import JobSource
from ai_scraper_bot.parsers.file_parser import AUDIO_TYPES, SUPPORTED_FILE_TYPES, VIDEO_TYPES, FileParser
from ai_scraper_bot.services.music_analysis import LocalMusicAnalyzer
from ai_scraper_bot.services.summarizer import MiniMaxHTTPSummarizer
from ai_scraper_bot.services.transcription import TranscriptionService
from ai_scraper_bot.services.video_analysis import LocalVideoAnalyzer
from ai_scraper_bot.services.vision import LocalVisionAnalyzer
from ai_scraper_bot.services.website import extract_website_text
from ai_scraper_bot.services.youtube import YouTubeService
from ai_scraper_bot.utils.chunker import split_message
from ai_scraper_bot.utils.files import ensure_directory, sweep_old_temp_files
from ai_scraper_bot.utils.session_memory import SessionMemoryStore
from ai_scraper_bot.utils.runtime_diary import get_recent_runtime_diary
from ai_scraper_bot.utils.typing_indicator import TypingIndicator

Language = Literal["english", "chinese"]
URL_PATTERN = re.compile(r"https?://\S+")
CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
LANGUAGE_HINTS = {
    "english": ("reply in english", "answer in english", "use english", "英文"),
    "chinese": ("reply in chinese", "answer in chinese", "use chinese", "中文", "请用中文"),
}
CHANNEL_SESSION_TTL_SECONDS = 10 * 60
WEBSITE_EXTRACT_TIMEOUT_SECONDS = 75
FILE_PARSE_TIMEOUT_SECONDS = 120
SUMMARY_TIMEOUT_SECONDS = 180
logger = logging.getLogger(__name__)


class ScraperBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="", intents=intents)
        self.settings = settings
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
        self.summarizer = MiniMaxHTTPSummarizer(settings)
        self.transcription_service = TranscriptionService(settings)
        self.vision_analyzer = LocalVisionAnalyzer(settings, self.summarizer)
        self.music_analyzer = LocalMusicAnalyzer(settings)
        self.video_analyzer = LocalVideoAnalyzer(settings, self.vision_analyzer, self.summarizer)
        self.file_parser = FileParser(
            self.transcription_service,
            self.vision_analyzer,
            self.video_analyzer,
            self.music_analyzer,
        )
        self.youtube_service = YouTubeService(settings, self.transcription_service)
        self.background_jobs: set[asyncio.Task] = set()
        self.sweeper_task: asyncio.Task | None = None
        self.memory = SessionMemoryStore()
        self.active_channels: dict[int, float] = {}

    async def setup_hook(self) -> None:
        ensure_directory(self.settings.downloads_dir)
        self.sweeper_task = asyncio.create_task(self._run_temp_sweeper())

    async def close(self) -> None:
        if self.sweeper_task:
            self.sweeper_task.cancel()
        await super().close()

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (ID: {self.user.id if self.user else 'unknown'})")
        logger.info("Bot is ready and waiting for messages.")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        is_dm = _is_dm(message)
        cleaned_content = _normalize_message_content(
            message.content,
            self.user.id if self.user else None,
            self.settings.bot_prefix,
        )
        should_reply = (
            is_dm
            or self.settings.reply_to_all_server_messages
            or _mentions_bot(message, self.user)
            or _is_reply_to_bot(message, self.user)
            or bool(message.attachments)
            or self._channel_is_active(message)
        )
        detected_url = _extract_first_url(cleaned_content)
        url = detected_url if _should_treat_message_as_source(cleaned_content, detected_url) else None
        if url:
            should_reply = True
        logger.info(
            "Received message: author=%s channel=%s dm=%s should_reply=%s has_url=%s has_attachments=%s content=%r",
            message.author,
            message.channel.id,
            is_dm,
            should_reply,
            bool(url),
            bool(message.attachments),
            cleaned_content[:200],
        )
        if not should_reply:
            return
        language = _preferred_language(cleaned_content)
        source = self._build_source(message, url)
        self._touch_channel(message)

        if source:
            if not await self._safe_send(
                message.channel,
                _reply_text(language, "job_received", source_kind=source.kind),
            ):
                return
            task = asyncio.create_task(self._process_job(message, source, language, cleaned_content))
        else:
            task = asyncio.create_task(self._handle_conversation(message, cleaned_content, language))
        self.background_jobs.add(task)
        task.add_done_callback(self.background_jobs.discard)

    async def _process_job(
        self,
        message: discord.Message,
        source: JobSource,
        language: Language,
        user_request: str,
    ) -> None:
        async with self.semaphore:
            temp_file: Path | None = None
            try:
                async with TypingIndicator(message.channel):
                    if not await self._safe_send(
                        message.channel,
                        _reply_text(language, "extracting", source_kind=source.kind),
                    ):
                        return
                    if source.kind == "youtube":
                        extracted = await self.youtube_service.extract(source.value)
                    elif source.kind == "website":
                        extracted = await asyncio.wait_for(
                            extract_website_text(
                                source.value,
                                vision_analyzer=self.vision_analyzer,
                                video_analyzer=self.video_analyzer,
                                music_analyzer=self.music_analyzer,
                                downloads_dir=self.settings.downloads_dir,
                            ),
                            timeout=WEBSITE_EXTRACT_TIMEOUT_SECONDS,
                        )
                    else:
                        attachment = message.attachments[0]
                        _validate_attachment(attachment, self.settings.max_file_size_mb)
                        temp_file = self.settings.downloads_dir / f"{uuid4().hex}_{attachment.filename}"
                        await attachment.save(temp_file)
                        extracted = await asyncio.wait_for(
                            self.file_parser.parse(temp_file),
                            timeout=_file_parse_timeout_seconds(attachment.filename),
                        )
                    extracted = _attach_runtime_diary(
                        extracted=extracted,
                        source=source,
                        attachment=message.attachments[0] if message.attachments else None,
                    )

                    if not extracted.body.strip() and not extracted.visual_inputs:
                        raise RuntimeError(_reply_text(language, "empty_content"))

                    recent_context, _memory_visuals = self.memory.build_context(
                        _context_key(message),
                        user_request,
                        include_artifacts=False,
                    )
                    if not await self._safe_send(
                        message.channel,
                        _reply_text(language, "analyzing"),
                    ):
                        return
                    try:
                        summary = await asyncio.wait_for(
                            self.summarizer.analyze_source(
                                title=extracted.title,
                                source_label=extracted.source_label,
                                body=extracted.body,
                                response_language=_language_label(language),
                                user_request=user_request,
                                metadata=extracted.metadata,
                                recent_context=recent_context,
                                visual_inputs=extracted.visual_inputs,
                                issues=extracted.issues,
                                runtime_diary=extracted.runtime_diary,
                                reviewed_media=extracted.reviewed_media,
                                video_interval_history=extracted.video_interval_history,
                                related_urls=extracted.related_urls,
                            ),
                            timeout=SUMMARY_TIMEOUT_SECONDS,
                        )
                    except Exception as summary_exc:
                        summary = _build_source_fallback_summary(
                            language=language,
                            extracted=extracted,
                            reason=str(summary_exc),
                        )
                    summary = _prepend_extraction_status(summary, extracted, language)
                self.memory.add_artifact(_context_key(message), extracted, user_request)
                self.memory.add_turn(_context_key(message), user_request or source.value, summary)
                for chunk in split_message(summary, self.settings.message_chunk_size):
                    if not await self._safe_send(message.channel, chunk):
                        return
            except Exception as exc:
                error_text = _build_processing_failure_message(
                    language=language,
                    source=source,
                    error=exc,
                    attachment=message.attachments[0] if message.attachments else None,
                    runtime_diary=_runtime_diary_for_source(
                        source,
                        attachment=message.attachments[0] if message.attachments else None,
                    ),
                )
                self.memory.add_turn(_context_key(message), user_request or source.value, error_text)
                await self._safe_send(message.channel, error_text)
            finally:
                if temp_file and temp_file.exists():
                    await asyncio.to_thread(temp_file.unlink, True)

    async def _handle_conversation(
        self,
        message: discord.Message,
        cleaned_content: str,
        language: Language,
    ) -> None:
        prompt = cleaned_content or _reply_text(language, "empty_chat_prompt")
        if not prompt.strip():
            await self._safe_send(message.channel, _reply_text(language, "help"))
            return

        local_reply = _local_fast_reply(prompt, language)
        if local_reply:
            self.memory.add_turn(_context_key(message), prompt, local_reply)
            await self._safe_send(message.channel, local_reply)
            return

        quoted_input_mode = _should_treat_user_message_as_quoted_text(prompt)
        use_source_follow_up = _should_use_source_follow_up(prompt) and not quoted_input_mode
        recent_context, visual_inputs = self.memory.build_context(
            _context_key(message),
            prompt,
            include_artifacts=use_source_follow_up,
        )
        primary_artifact = self.memory.get_primary_artifact(_context_key(message), prompt) if use_source_follow_up else None
        runtime_diary = (
            primary_artifact.runtime_diary
            if primary_artifact and use_source_follow_up
            else _runtime_diary_for_prompt(prompt)
        )
        try:
            async with TypingIndicator(message.channel):
                if primary_artifact and use_source_follow_up:
                    reply = await self.summarizer.analyze_source(
                        title=primary_artifact.title,
                        source_label=primary_artifact.source_label,
                        body=primary_artifact.body,
                        response_language=_language_label(language),
                        user_request=prompt,
                        metadata=primary_artifact.metadata,
                        recent_context=recent_context,
                        visual_inputs=primary_artifact.visual_inputs or visual_inputs,
                        issues=primary_artifact.issues,
                        runtime_diary=primary_artifact.runtime_diary,
                        reviewed_media=primary_artifact.reviewed_media,
                        video_interval_history=primary_artifact.video_interval_history,
                        related_urls=primary_artifact.related_urls,
                    )
                else:
                    reply = await self.summarizer.chat(
                        user_message=prompt,
                        response_language=_language_label(language),
                        recent_context=recent_context,
                        visual_inputs=visual_inputs,
                        runtime_diary=runtime_diary,
                        quoted_input_mode=quoted_input_mode,
                    )
            self.memory.add_turn(_context_key(message), prompt, reply)
            for chunk in split_message(reply, self.settings.message_chunk_size):
                if not await self._safe_send(message.channel, chunk):
                    return
        except Exception as exc:
            error_text = _reply_text(language, "job_failed", error=str(exc))
            self.memory.add_turn(_context_key(message), prompt, error_text)
            await self._safe_send(message.channel, error_text)

    async def _run_temp_sweeper(self) -> None:
        while True:
            try:
                await sweep_old_temp_files(
                    self.settings.downloads_dir,
                    self.settings.temp_sweep_hours,
                )
            except Exception:
                pass
            await asyncio.sleep(3600)

    def _build_source(
        self,
        message: discord.Message,
        url: str | None,
    ) -> JobSource | None:
        if message.attachments:
            attachment = message.attachments[0]
            return JobSource(kind="file", value=attachment.url, attachment_name=attachment.filename)
        if url:
            return classify_source(url)
        return None

    def _touch_channel(self, message: discord.Message) -> None:
        if not _is_dm(message):
            self.active_channels[message.channel.id] = time()

    def _channel_is_active(self, message: discord.Message) -> bool:
        if _is_dm(message):
            return True
        last_seen = self.active_channels.get(message.channel.id)
        if last_seen is None:
            return False
        if time() - last_seen > CHANNEL_SESSION_TTL_SECONDS:
            self.active_channels.pop(message.channel.id, None)
            return False
        return True

    async def _safe_send(self, channel, content: str) -> bool:
        try:
            await channel.send(content)
            return True
        except discord.NotFound:
            logger.warning("Channel %s is no longer available; skipping send.", getattr(channel, "id", "unknown"))
            return False
        except discord.Forbidden:
            logger.warning("Bot no longer has permission to send to channel %s.", getattr(channel, "id", "unknown"))
            return False
        except discord.HTTPException as exc:
            logger.warning(
                "Discord send failed for channel %s: %s",
                getattr(channel, "id", "unknown"),
                exc,
            )
            return False


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
        "discord.client",
        "discord.gateway",
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


def _normalize_message_content(content: str, bot_user_id: int | None, bot_prefix: str) -> str:
    text = content.strip()
    if bot_user_id is not None:
        text = text.replace(f"<@{bot_user_id}>", " ")
        text = text.replace(f"<@!{bot_user_id}>", " ")
    if bot_prefix and text.startswith(bot_prefix):
        text = text[len(bot_prefix) :]
    return " ".join(text.split()).strip()


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


def _mentions_bot(message: discord.Message, bot_user: discord.ClientUser | None) -> bool:
    if not bot_user:
        return False
    return any(user.id == bot_user.id for user in message.mentions)


def _is_reply_to_bot(message: discord.Message, bot_user: discord.ClientUser | None) -> bool:
    if not bot_user or not message.reference or not message.reference.resolved:
        return False
    referenced = message.reference.resolved
    if isinstance(referenced, discord.Message) and referenced.author:
        return referenced.author.id == bot_user.id
    return False


def _is_dm(message: discord.Message) -> bool:
    return message.guild is None


def _context_key(message: discord.Message) -> tuple[int, int]:
    return (message.channel.id, message.author.id)


def _validate_attachment(attachment: discord.Attachment, max_file_size_mb: int) -> None:
    extension = Path(attachment.filename).suffix.lower()
    if extension not in SUPPORTED_FILE_TYPES:
        raise RuntimeError(
            f"I can't read `{attachment.filename}` yet. Supported types: "
            + ", ".join(sorted(SUPPORTED_FILE_TYPES))
        )
    if attachment.size > max_file_size_mb * 1024 * 1024:
        raise RuntimeError(
            f"`{attachment.filename}` is too large. The current limit is {max_file_size_mb} MB."
        )


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


def _build_processing_failure_message(
    *,
    language: Language,
    source: JobSource,
    error: Exception,
    attachment: discord.Attachment | None = None,
    runtime_diary: list[str] | None = None,
) -> str:
    detail = str(error).strip() or error.__class__.__name__
    if isinstance(error, asyncio.TimeoutError):
        if source.kind == "file":
            detail = "The file took too long to parse, so the bot stopped the job before it could hang forever."
        elif source.kind == "youtube":
            detail = "The YouTube extraction path took too long and was stopped before it could hang forever."
        else:
            detail = "The website took too long to process, so the bot stopped the job before it could hang forever."
    diary_lines = list(runtime_diary or [])[:6]
    if source.kind == "file" and attachment is not None:
        extension = Path(attachment.filename).suffix.lower() or "unknown"
        size_mb = attachment.size / (1024 * 1024)
        if language == "chinese":
            lines = [
                "这个文件没有成功完整处理，但我先告诉你目前知道的情况：",
                f"- 文件名：`{attachment.filename}`",
                f"- 类型：`{extension}`",
                f"- 大小：约 {size_mb:.2f} MB",
                f"- 处理时发生的情况：{detail}",
            ]
            if diary_lines:
                lines.append("- 最近终端日志：")
                lines.extend(f"  - {line}" for line in diary_lines)
            return "\n".join(lines)
        lines = [
            "I couldn't fully process that file, but here is what I do know so far:",
            f"- Filename: `{attachment.filename}`",
            f"- Type: `{extension}`",
            f"- Size: about {size_mb:.2f} MB",
            f"- What happened while processing it: {detail}",
        ]
        if diary_lines:
            lines.append("- Recent terminal diary:")
            lines.extend(f"  - {line}" for line in diary_lines)
        return "\n".join(lines)
    if source.kind == "youtube":
        if language == "chinese":
            lines = [
                "这个 YouTube 任务没有完整成功，但我至少知道这是一个视频链接，并且已经尽量尝试了可用的提取路径。",
                f"- 链接：{source.value}",
                f"- 当前问题：{detail}",
            ]
            if diary_lines:
                lines.append("- 最近终端日志：")
                lines.extend(f"  - {line}" for line in diary_lines)
            return "\n".join(lines)
        lines = [
            "This YouTube request did not complete cleanly, but I did at least identify it as a video task and try the available extraction paths.",
            f"- URL: {source.value}",
            f"- Current issue: {detail}",
        ]
        if diary_lines:
            lines.append("- Recent terminal diary:")
            lines.extend(f"  - {line}" for line in diary_lines)
        return "\n".join(lines)
    if language == "chinese":
        lines = [f"这个任务没有完整成功，不过我已经尽量处理了当前来源。当前问题：{detail}"]
        if diary_lines:
            lines.append("- 最近终端日志：")
            lines.extend(f"  - {line}" for line in diary_lines)
        return "\n".join(lines)
    lines = [f"This task did not complete cleanly, but I did process as much as I could. Current issue: {detail}"]
    if diary_lines:
        lines.append("- Recent terminal diary:")
        lines.extend(f"  - {line}" for line in diary_lines)
    return "\n".join(lines)


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


def _attach_runtime_diary(
    *,
    extracted,
    source: JobSource,
    attachment: discord.Attachment | None = None,
):
    diary_lines = _runtime_diary_for_source(source, attachment=attachment)
    if not diary_lines:
        return extracted
    merged_diary = list(dict.fromkeys([*getattr(extracted, "runtime_diary", []), *diary_lines]))
    return replace(extracted, runtime_diary=merged_diary)


def _runtime_diary_for_source(
    source: JobSource,
    *,
    attachment: discord.Attachment | None = None,
) -> list[str]:
    keywords: list[str] = [source.value]
    parsed = urlparse(source.value)
    if source.kind == "youtube":
        video_id_match = re.search(r"(?:v=|youtu\\.be/)([A-Za-z0-9_-]{6,})", source.value)
        if video_id_match:
            keywords.append(video_id_match.group(1))
    if parsed.hostname:
        keywords.append(parsed.hostname)
    if attachment is not None:
        keywords.append(attachment.filename)
    return get_recent_runtime_diary(
        limit=10,
        keywords=keywords,
        logger_prefixes=("ai_scraper_bot", "discord.", "httpx"),
    )


def _runtime_diary_for_prompt(prompt: str) -> list[str]:
    if not _wants_runtime_diary(prompt):
        return []
    prompt_keywords = [item for item in re.findall(r"[A-Za-z0-9_.:/-]+", prompt) if len(item) >= 4][:8]
    return get_recent_runtime_diary(
        limit=10,
        keywords=prompt_keywords,
        logger_prefixes=("ai_scraper_bot", "discord.", "httpx"),
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
            "job_received": {
                "youtube": [
                    "I’ve got the YouTube link. Let me dig into it.",
                    "I found the video. I’m starting with that now.",
                    "I see the YouTube link. I’ll check it out now.",
                ],
                "website": [
                    "I’ve got the website link. Let me take a look.",
                    "I found the page. I’m reading through it now.",
                    "I see the website. I’ll start going through it.",
                ],
                "file": [
                    "I’ve got the file. Let me open it up.",
                    "I see the attachment. I’m starting on it now.",
                    "The file came through. I’ll take a look.",
                ],
            },
            "extracting": {
                "youtube": [
                    "I’m checking the video and pulling out what I can from it first.",
                    "I’m going through the video now and collecting the useful content.",
                    "I’m starting with the video content and seeing what I can extract.",
                ],
                "website": [
                    "I’m reading the page now and pulling together the important parts.",
                    "I’m going through the website content first.",
                    "I’m scanning the page and gathering the useful material.",
                ],
                "file": [
                    "I’m opening the file and pulling out the useful parts now.",
                    "I’m reading through the file first.",
                    "I’m extracting what matters from the file now.",
                ],
            },
            "analyzing": [
                "I have what I need now. Let me put it together clearly.",
                "I’ve got the source content. I’m working through it now.",
                "I’ve collected the material. Let me analyze it properly.",
            ],
            "empty_content": "I couldn't find usable text or visuals in that source.",
            "job_failed": "I ran into a problem: {error}",
            "empty_chat_prompt": "Please introduce yourself and explain what you can help with.",
            "help": (
                "I can analyze websites, YouTube videos, images, and supported files. "
                "Send me a link, upload a file, or just ask naturally."
            ),
        },
        "chinese": {
            "job_received": {
                "youtube": [
                    "我看到这个 YouTube 链接了，我现在开始看。",
                    "这个视频链接我收到了，我先处理它。",
                    "我已经拿到这个 YouTube 视频了，现在开始分析。",
                ],
                "website": [
                    "我看到这个网页了，我先读一下内容。",
                    "这个网站链接我收到了，现在开始看。",
                    "我已经拿到这个网页了，我先整理内容。",
                ],
                "file": [
                    "我收到这个文件了，我先打开看看。",
                    "这个附件我已经拿到了，现在开始处理。",
                    "文件已经收到，我先读一下里面的内容。",
                ],
            },
            "extracting": {
                "youtube": [
                    "我先检查这个视频，并尽量把里面有用的内容提取出来。",
                    "我现在先过一遍这个视频，看看能提取到什么。",
                    "我先从这个视频里整理出可分析的内容。",
                ],
                "website": [
                    "我先读这个网页，把重要内容整理出来。",
                    "我现在先浏览这个网页的内容。",
                    "我先把这个网页里有用的信息提取出来。",
                ],
                "file": [
                    "我先打开这个文件，把里面有用的内容提取出来。",
                    "我现在先读这个文件的内容。",
                    "我先从这个文件里整理出可分析的信息。",
                ],
            },
            "analyzing": [
                "我已经拿到内容了，现在开始认真整理。",
                "我这边已经有材料了，现在开始分析。",
                "内容我已经收到了，我来把它整理清楚。",
            ],
            "empty_content": "我没有在这个来源里找到可用的文字或视觉内容。",
            "job_failed": "处理时遇到问题了：{error}",
            "empty_chat_prompt": "请先简单介绍一下你自己，并告诉我你能帮我做什么。",
            "help": "我可以分析网站、YouTube 视频、图片和支持的文件。你直接发链接、上传文件，或者自然地问我就可以。",
        },
    }
    chosen = templates[language][key]
    if isinstance(chosen, dict):
        value = chosen[kwargs["source_kind"]]
        if isinstance(value, list):
            return random.choice(value)
        return value
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
