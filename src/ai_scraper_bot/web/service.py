from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import UploadFile

from ai_scraper_bot.shared import (
    SUMMARY_TIMEOUT_SECONDS,
    WEBSITE_EXTRACT_TIMEOUT_SECONDS,
    _build_source_fallback_summary,
    _extract_first_url,
    _file_parse_timeout_seconds,
    _language_label,
    _local_fast_reply,
    _preferred_language,
    _prepend_extraction_status,
    _runtime_diary_for_prompt,
    _should_treat_message_as_source,
    _should_treat_user_message_as_quoted_text,
    _should_use_source_follow_up,
    classify_source,
)
from ai_scraper_bot.config import Settings
from ai_scraper_bot.models import ExtractedContent, JobSource
from ai_scraper_bot.parsers.file_parser import FileParser, SUPPORTED_FILE_TYPES
from ai_scraper_bot.services.music_analysis import LocalMusicAnalyzer
from ai_scraper_bot.services.summarizer import MiniMaxHTTPSummarizer
from ai_scraper_bot.services.transcription import TranscriptionService
from ai_scraper_bot.services.video_analysis import LocalVideoAnalyzer
from ai_scraper_bot.services.vision import LocalVisionAnalyzer
from ai_scraper_bot.services.website import extract_website_text
from ai_scraper_bot.services.youtube import YouTubeService
from ai_scraper_bot.utils.files import ensure_directory
from ai_scraper_bot.utils.runtime_diary import get_recent_runtime_diary
from ai_scraper_bot.utils.session_memory import SessionMemoryStore
from ai_scraper_bot.web.store import ChatRecord, WebChatStore


CHAT_REPLY_TIMEOUT_SECONDS = 150
MAX_ACTIVE_JOBS = 1


@dataclass(slots=True)
class ActiveJob:
    id: str
    chat_id: int
    user_message_id: int
    user_text: str
    attachment_name: str | None
    source_kind: str | None
    stage: str
    status: str
    created_at: str
    task: asyncio.Task | None = field(default=None, repr=False)
    assistant_message: dict[str, Any] | None = None
    chat: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "user_message_id": self.user_message_id,
            "user_text": self.user_text,
            "attachment_name": self.attachment_name,
            "source_kind": self.source_kind,
            "stage": self.stage,
            "status": self.status,
            "created_at": self.created_at,
            "assistant_message": self.assistant_message,
            "chat": self.chat,
            "error": self.error,
        }


class WebChatService:
    def __init__(self, settings: Settings, store: WebChatStore) -> None:
        self.settings = settings
        self.store = store
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
        self.memory = SessionMemoryStore(
            max_turns=6,
            max_artifacts=6,
            artifact_body_limit=32000,
            ttl_seconds=7 * 24 * 60 * 60,
        )
        self._hydrated_chat_ids: set[int] = set()
        self._jobs_by_id: dict[str, ActiveJob] = {}
        self._active_job_id_by_chat: dict[int, str] = {}

    async def startup(self) -> None:
        ensure_directory(self.settings.downloads_dir)

    async def list_chats(self) -> list[dict[str, Any]]:
        return [chat.to_dict() for chat in self.store.list_chats()]

    async def create_chat(self) -> dict[str, Any]:
        if self.store.count_chats() >= 10:
            raise RuntimeError("You can have at most 10 chats at a time.")
        return self.store.create_chat().to_dict()

    async def rename_chat(self, chat_id: int, title: str) -> dict[str, Any]:
        chat = self.store.update_chat_title(chat_id, title)
        self._attach_chat_to_active_job(chat_id, chat)
        return chat.to_dict()

    async def clear_chat(self, chat_id: int) -> dict[str, Any]:
        active = self._active_job_for_chat(chat_id)
        if active and active.status == "running":
            await self.cancel_job(active.id)
        chat = self.store.clear_chat_messages(chat_id)
        self.store.clear_memory_for_chat(self.memory, chat_id)
        self.store.hydrate_chat_memory(self.memory, chat_id)
        self._hydrated_chat_ids.add(chat_id)
        return chat.to_dict()

    async def clear_all_chats(self) -> None:
        running_jobs = [job for job in self._jobs_by_id.values() if job.status == "running"]
        for job in running_jobs:
            await self.cancel_job(job.id)
        self.memory.sessions.clear()
        self._hydrated_chat_ids.clear()
        self._active_job_id_by_chat.clear()
        self.store.clear_all_chats()

    async def delete_chat(self, chat_id: int) -> None:
        active = self._active_job_for_chat(chat_id)
        if active and active.status == "running":
            await self.cancel_job(active.id)
        self.store.delete_chat(chat_id)
        self.store.clear_memory_for_chat(self.memory, chat_id)
        self._hydrated_chat_ids.discard(chat_id)
        self._active_job_id_by_chat.pop(chat_id, None)

    async def get_chat_bundle(self, chat_id: int) -> dict[str, Any]:
        await self._ensure_chat_memory(chat_id)
        chat = self.store.get_chat(chat_id)
        messages = self.store.list_messages(chat_id)
        active_job = self._active_job_for_chat(chat_id)
        return {
            "chat": chat.to_dict(),
            "messages": [message.to_dict() for message in messages],
            "active_job": active_job.to_dict() if active_job and active_job.status == "running" else None,
        }

    async def start_message(
        self,
        *,
        chat_id: int,
        text: str,
        uploaded_file: UploadFile | None = None,
    ) -> dict[str, Any]:
        await self.startup()
        self.store.get_chat(chat_id)
        await self._ensure_chat_memory(chat_id)

        cleaned_text = " ".join((text or "").split()).strip()
        if not cleaned_text and uploaded_file is None:
            raise RuntimeError("Send a message, a link, or a supported file first.")

        if self._running_jobs_count() >= MAX_ACTIVE_JOBS:
            raise RuntimeError("The AI is already working on another chat. Please wait or pause that job first.")

        source = await self._build_source(cleaned_text, uploaded_file)
        attachment_name = uploaded_file.filename if uploaded_file else None
        user_message = self.store.add_message(
            chat_id=chat_id,
            role="user",
            content=cleaned_text,
            attachment_name=attachment_name,
            source_kind=source.kind if source else None,
            metadata={"has_attachment": bool(uploaded_file)},
        )
        job = ActiveJob(
            id=uuid4().hex,
            chat_id=chat_id,
            user_message_id=user_message.id,
            user_text=cleaned_text,
            attachment_name=attachment_name,
            source_kind=source.kind if source else None,
            stage=_initial_stage(cleaned_text, attachment_name, source.kind if source else None),
            status="running",
            created_at=_utc_now(),
        )
        task = asyncio.create_task(
            self._run_job(
                job=job,
                source=source,
                language=_preferred_language(cleaned_text),
                user_request=cleaned_text,
            )
        )
        job.task = task
        self._jobs_by_id[job.id] = job
        self._active_job_id_by_chat[chat_id] = job.id
        return {
            "chat": self.store.get_chat(chat_id).to_dict(),
            "user_message": user_message.to_dict(),
            "job": job.to_dict(),
        }

    async def get_job(self, job_id: str) -> dict[str, Any]:
        job = self._jobs_by_id.get(job_id)
        if job is None:
            raise KeyError(f"Job {job_id} was not found.")
        return job.to_dict()

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self._jobs_by_id.get(job_id)
        if job is None:
            raise KeyError(f"Job {job_id} was not found.")
        if job.status == "running":
            job.status = "cancelled"
            job.stage = "Stopped."
            self._active_job_id_by_chat.pop(job.chat_id, None)
            if job.task is not None:
                job.task.cancel()
                with suppress(asyncio.CancelledError):
                    await job.task
        return job.to_dict()

    async def list_active_jobs(self) -> list[dict[str, Any]]:
        return [job.to_dict() for job in self._jobs_by_id.values() if job.status == "running"]

    async def _run_job(
        self,
        *,
        job: ActiveJob,
        source: JobSource | None,
        language: str,
        user_request: str,
    ) -> None:
        try:
            async with self.semaphore:
                if source is not None:
                    assistant_text, extracted = await self._process_source_message(
                        job=job,
                        chat_id=job.chat_id,
                        source=source,
                        language=language,
                        user_request=user_request,
                    )
                    title_seed = extracted.title
                else:
                    assistant_text = await self._process_chat_message(
                        job=job,
                        chat_id=job.chat_id,
                        prompt=user_request,
                        language=language,
                    )
                    title_seed = user_request

            if job.status == "cancelled":
                return

            assistant_message = self.store.add_message(
                chat_id=job.chat_id,
                role="assistant",
                content=assistant_text,
                source_kind=source.kind if source else None,
                metadata={"generated_at": _utc_now()},
            )
            updated_chat = self._refresh_chat_title(job.chat_id, title_seed)
            job.assistant_message = assistant_message.to_dict()
            job.chat = updated_chat.to_dict()
            job.stage = "Completed."
            job.status = "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "Stopped."
        except Exception as exc:
            job.error = str(exc).strip() or exc.__class__.__name__
            error_message = self.store.add_message(
                chat_id=job.chat_id,
                role="assistant",
                content=f"I ran into a problem while generating the reply: {job.error}",
                source_kind=source.kind if source else None,
                metadata={"generated_at": _utc_now()},
            )
            job.assistant_message = error_message.to_dict()
            job.chat = self.store.get_chat(job.chat_id).to_dict()
            job.stage = "Failed."
            job.status = "failed"
        finally:
            if self._active_job_id_by_chat.get(job.chat_id) == job.id:
                self._active_job_id_by_chat.pop(job.chat_id, None)

    async def _process_source_message(
        self,
        *,
        job: ActiveJob,
        chat_id: int,
        source: JobSource,
        language: str,
        user_request: str,
    ) -> tuple[str, ExtractedContent]:
        temp_file: Path | None = None
        try:
            self._set_job_stage(job, _extraction_stage_text(source.kind))
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
                if source.local_path is None:
                    raise RuntimeError("The uploaded file was not saved correctly before parsing.")
                temp_file = source.local_path
                extracted = await asyncio.wait_for(
                    self.file_parser.parse(source.local_path),
                    timeout=_file_parse_timeout_seconds(source.attachment_name or source.local_path.name),
                )

            extracted = self._attach_runtime_diary(
                extracted=extracted,
                source=source,
                attachment_name=source.attachment_name,
            )
            if not extracted.body.strip() and not extracted.visual_inputs:
                raise RuntimeError("I couldn't find usable text or visuals in that source.")

            recent_context, _ = self.memory.build_context(
                self._context_key(chat_id),
                user_request,
                include_artifacts=False,
            )
            self._set_job_stage(job, _summary_stage_text(source.kind))
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
                    language=language,  # type: ignore[arg-type]
                    extracted=extracted,
                    reason=str(summary_exc),
                )
            summary = _prepend_extraction_status(summary, extracted, language)  # type: ignore[arg-type]
            self.memory.add_artifact(self._context_key(chat_id), extracted, user_request)
            self.memory.add_turn(self._context_key(chat_id), user_request or source.value, summary)
            self.store.add_artifact(chat_id=chat_id, extracted=extracted, user_request=user_request)
            return summary, extracted
        except Exception as exc:
            error_text = self._build_processing_failure_message(
                source=source,
                error=exc,
                attachment_name=source.attachment_name,
            )
            return error_text, ExtractedContent(
                title=source.attachment_name or source.value,
                body="",
                source_label=source.value,
                metadata={"type": source.kind},
            )
        finally:
            if temp_file and temp_file.exists():
                await asyncio.to_thread(temp_file.unlink, True)

    async def _process_chat_message(
        self,
        *,
        job: ActiveJob,
        chat_id: int,
        prompt: str,
        language: str,
    ) -> str:
        if not prompt.strip():
            return "Send me a link, upload a file, or ask a question to get started."

        local_reply = _local_fast_reply(prompt, language)  # type: ignore[arg-type]
        if local_reply:
            self.memory.add_turn(self._context_key(chat_id), prompt, local_reply)
            return local_reply

        quoted_input_mode = _should_treat_user_message_as_quoted_text(prompt)
        use_source_follow_up = _should_use_source_follow_up(prompt) and not quoted_input_mode
        recent_context, visual_inputs = self.memory.build_context(
            self._context_key(chat_id),
            prompt,
            include_artifacts=use_source_follow_up,
        )
        primary_artifact = (
            self.memory.get_primary_artifact(self._context_key(chat_id), prompt)
            if use_source_follow_up
            else None
        )
        runtime_diary = (
            primary_artifact.runtime_diary
            if primary_artifact and use_source_follow_up
            else _runtime_diary_for_prompt(prompt)
        )
        try:
            if primary_artifact and use_source_follow_up:
                self._set_job_stage(job, "I have the source information now and I’m working on the summary.")
                reply = await asyncio.wait_for(
                    self.summarizer.analyze_source(
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
                    ),
                    timeout=CHAT_REPLY_TIMEOUT_SECONDS,
                )
            else:
                self._set_job_stage(job, "I’m thinking through the details.")
                reply = await asyncio.wait_for(
                    self.summarizer.chat(
                        user_message=prompt,
                        response_language=_language_label(language),
                        recent_context=recent_context,
                        visual_inputs=visual_inputs,
                        runtime_diary=runtime_diary,
                        quoted_input_mode=quoted_input_mode,
                    ),
                    timeout=CHAT_REPLY_TIMEOUT_SECONDS,
                )
        except asyncio.TimeoutError:
            reply = (
                "I took too long to answer that, so the request was stopped before it could hang forever. "
                "Please try again, or narrow the request a bit."
            )
        except Exception as exc:
            reply = f"I ran into a problem while generating the reply: {exc}"
        if not _looks_like_ephemeral_failure(reply):
            self.memory.add_turn(self._context_key(chat_id), prompt, reply)
        return reply

    async def _build_source(
        self,
        cleaned_text: str,
        uploaded_file: UploadFile | None,
    ) -> JobSource | None:
        if uploaded_file is not None:
            local_path = await self._save_upload(uploaded_file)
            return JobSource(
                kind="file",
                value=uploaded_file.filename or local_path.name,
                attachment_name=uploaded_file.filename or local_path.name,
                local_path=local_path,
            )

        detected_url = _extract_first_url(cleaned_text)
        url = detected_url if _should_treat_message_as_source(cleaned_text, detected_url) else None
        if url:
            return classify_source(url)
        return None

    async def _save_upload(self, uploaded_file: UploadFile) -> Path:
        filename = uploaded_file.filename or "uploaded-file"
        extension = Path(filename).suffix.lower()
        if extension not in SUPPORTED_FILE_TYPES:
            raise RuntimeError(
                "I can't read that file type yet. Supported types: "
                + ", ".join(sorted(SUPPORTED_FILE_TYPES))
            )

        output_path = self.settings.downloads_dir / f"{uuid4().hex}_{Path(filename).name}"
        max_bytes = self.settings.max_file_size_mb * 1024 * 1024
        total_bytes = 0
        with output_path.open("wb") as handle:
            while True:
                chunk = await uploaded_file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    output_path.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"`{filename}` is too large. The current limit is {self.settings.max_file_size_mb} MB."
                    )
                handle.write(chunk)
        await uploaded_file.close()
        return output_path

    async def _ensure_chat_memory(self, chat_id: int) -> None:
        if chat_id in self._hydrated_chat_ids:
            return
        self.store.clear_memory_for_chat(self.memory, chat_id)
        self.store.hydrate_chat_memory(self.memory, chat_id)
        self._hydrated_chat_ids.add(chat_id)

    def _context_key(self, chat_id: int) -> tuple[int, int]:
        return (chat_id, 0)

    def _refresh_chat_title(self, chat_id: int, title_seed: str) -> ChatRecord:
        chat = self.store.get_chat(chat_id)
        if not _is_placeholder_title(chat.title):
            return chat
        updated_title = _suggest_chat_title(title_seed)
        if not updated_title:
            return chat
        updated_chat = self.store.update_chat_title(chat_id, updated_title)
        self._attach_chat_to_active_job(chat_id, updated_chat)
        return updated_chat

    def _attach_chat_to_active_job(self, chat_id: int, chat: ChatRecord) -> None:
        active = self._active_job_for_chat(chat_id)
        if active is not None:
            active.chat = chat.to_dict()

    def _attach_runtime_diary(
        self,
        *,
        extracted: ExtractedContent,
        source: JobSource,
        attachment_name: str | None = None,
    ) -> ExtractedContent:
        diary_lines = _runtime_diary_for_source(source, attachment_name=attachment_name)
        if not diary_lines:
            return extracted
        merged = list(dict.fromkeys([*extracted.runtime_diary, *diary_lines]))
        return replace(extracted, runtime_diary=merged)

    def _build_processing_failure_message(
        self,
        *,
        source: JobSource,
        error: Exception,
        attachment_name: str | None = None,
    ) -> str:
        detail = str(error).strip() or error.__class__.__name__
        diary_lines = _runtime_diary_for_source(source, attachment_name=attachment_name)[:6]
        if source.kind == "file":
            lines = [
                "I couldn't fully process that file, but here is what I do know so far:",
                f"- Filename: `{attachment_name or source.value}`",
                f"- Type: `{Path(attachment_name or source.value).suffix.lower() or 'unknown'}`",
                f"- What happened while processing it: {detail}",
            ]
            if diary_lines:
                lines.append("- Recent terminal diary:")
                lines.extend(f"  - {line}" for line in diary_lines)
            return "\n".join(lines)
        if source.kind == "youtube":
            lines = [
                "This YouTube request did not complete cleanly, but I did try the available extraction paths.",
                f"- URL: {source.value}",
                f"- Current issue: {detail}",
            ]
            if diary_lines:
                lines.append("- Recent terminal diary:")
                lines.extend(f"  - {line}" for line in diary_lines)
            return "\n".join(lines)
        lines = [
            "This website request did not complete cleanly, but I processed as much as I safely could.",
            f"- URL: {source.value}",
            f"- Current issue: {detail}",
        ]
        if diary_lines:
            lines.append("- Recent terminal diary:")
            lines.extend(f"  - {line}" for line in diary_lines)
        return "\n".join(lines)

    def _set_job_stage(self, job: ActiveJob, stage: str) -> None:
        if job.status == "running":
            job.stage = stage

    def _running_jobs_count(self) -> int:
        return sum(1 for job in self._jobs_by_id.values() if job.status == "running")

    def _active_job_for_chat(self, chat_id: int) -> ActiveJob | None:
        job_id = self._active_job_id_by_chat.get(chat_id)
        if not job_id:
            return None
        return self._jobs_by_id.get(job_id)


def _runtime_diary_for_source(source: JobSource, *, attachment_name: str | None = None) -> list[str]:
    keywords: list[str] = [source.value]
    if source.local_path is not None:
        keywords.append(source.local_path.name)
    if attachment_name:
        keywords.append(attachment_name)
    parsed = urlparse(source.value)
    if parsed.hostname:
        keywords.append(parsed.hostname)
    if source.kind == "youtube":
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", source.value)
        if match:
            keywords.append(match.group(1))
    return get_recent_runtime_diary(
        limit=10,
        keywords=keywords,
        logger_prefixes=("ai_scraper_bot", "httpx"),
    )


def _is_placeholder_title(title: str) -> bool:
    lowered = title.strip().lower()
    return lowered in {"new chat", "untitled chat", ""}


def _suggest_chat_title(seed: str) -> str:
    cleaned = re.sub(r"\s+", " ", (seed or "").strip())
    if not cleaned:
        return "New chat"
    cleaned = re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned[:80].strip(" -_:|")
    if len(cleaned) > 46:
        cleaned = cleaned[:43].rstrip() + "..."
    return cleaned or "New chat"


def _looks_like_ephemeral_failure(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "i took too long to answer",
        "i ran into a problem while generating the reply",
        "i couldn't fully process that file",
        "did not complete cleanly",
        "**temporary fallback result**",
    )
    return any(marker in lowered for marker in markers)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _initial_stage(text: str, attachment_name: str | None, source_kind: str | None) -> str:
    if attachment_name:
        return "Got your file. Working on it now."
    if source_kind == "youtube" or source_kind == "website" or re.search(r"https?://", text or "", flags=re.IGNORECASE):
        return "Got your link. Working on it now."
    return "Got your message. Working on it now."


def _extraction_stage_text(source_kind: str) -> str:
    if source_kind == "file":
        return "I’m extracting important details from the file."
    return "I’m extracting important details from the source."


def _summary_stage_text(source_kind: str) -> str:
    if source_kind == "file":
        return "I have the file information now and I’m working on the summary."
    return "I have the source information now and I’m working on the summary."
