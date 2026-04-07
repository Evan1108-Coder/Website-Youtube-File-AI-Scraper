from __future__ import annotations

from dataclasses import dataclass, field
import re
from time import time

from ai_scraper_bot.models import ExtractedContent, VisualInput

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "be",
    "can",
    "do",
    "for",
    "from",
    "give",
    "help",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "show",
    "summarize",
    "summary",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "we",
    "what",
    "with",
    "you",
    "你",
    "我",
    "请",
    "帮",
    "一下",
    "这个",
    "那个",
}

GO_BACK_MARKERS = (
    "go back",
    "back to",
    "earlier",
    "previous",
    "older",
    "before",
    "first one",
    "second one",
    "last one before",
    "the website before",
    "the file before",
    "the image before",
    "the picture before",
    "the video before",
    "回到",
    "之前",
    "前面",
    "上一個",
    "上一个",
    "前一个",
    "刚才那个",
    "刚刚那个",
    "前面的文件",
    "前面的网页",
    "前面的图片",
    "前面的视频",
)


@dataclass(slots=True)
class ConversationTurn:
    user_message: str
    assistant_reply: str
    created_at: float


@dataclass(slots=True)
class StoredArtifact:
    title: str
    source_label: str
    body: str
    chunks: list[str]
    metadata: dict[str, str]
    visual_inputs: list[VisualInput]
    issues: list[str]
    runtime_diary: list[str]
    reviewed_media: list[str]
    video_interval_history: list[str]
    related_urls: list[str]
    user_request: str
    created_at: float


@dataclass(slots=True)
class SessionState:
    turns: list[ConversationTurn] = field(default_factory=list)
    artifacts: list[StoredArtifact] = field(default_factory=list)
    updated_at: float = field(default_factory=time)


class SessionMemoryStore:
    def __init__(
        self,
        *,
        max_turns: int = 8,
        max_artifacts: int | None = None,
        artifact_body_limit: int | None = None,
        ttl_seconds: int = 24 * 60 * 60,
    ) -> None:
        self.max_turns = max_turns
        self.max_artifacts = max_artifacts
        self.artifact_body_limit = artifact_body_limit
        self.ttl_seconds = ttl_seconds
        self.sessions: dict[tuple[int, int], SessionState] = {}

    def add_turn(self, key: tuple[int, int], user_message: str, assistant_reply: str) -> None:
        session = self._get_session(key)
        session.turns.append(
            ConversationTurn(
                user_message=user_message.strip(),
                assistant_reply=assistant_reply.strip(),
                created_at=time(),
            )
        )
        session.turns = session.turns[-self.max_turns :]
        session.updated_at = time()

    def add_artifact(self, key: tuple[int, int], extracted: ExtractedContent, user_request: str) -> None:
        session = self._get_session(key)
        stored_body = extracted.body if self.artifact_body_limit is None else extracted.body[: self.artifact_body_limit]
        session.artifacts.append(
            StoredArtifact(
                title=extracted.title,
                source_label=extracted.source_label,
                body=stored_body,
                chunks=_chunk_text(stored_body),
                metadata=dict(extracted.metadata),
                visual_inputs=list(extracted.visual_inputs),
                issues=list(extracted.issues),
                runtime_diary=list(extracted.runtime_diary),
                reviewed_media=list(extracted.reviewed_media),
                video_interval_history=list(extracted.video_interval_history),
                related_urls=list(extracted.related_urls),
                user_request=user_request.strip(),
                created_at=time(),
            )
        )
        if self.max_artifacts is not None:
            session.artifacts = session.artifacts[-self.max_artifacts :]
        session.updated_at = time()

    def build_context(
        self,
        key: tuple[int, int],
        user_message: str,
        *,
        include_artifacts: bool = True,
    ) -> tuple[str, list[VisualInput]]:
        session = self._prune_and_get(key)
        if not session:
            return "", []

        parts: list[str] = []
        if session.turns:
            lines = []
            for turn in session.turns[-6:]:
                lines.append(f"User: {turn.user_message}")
                lines.append(f"Assistant: {turn.assistant_reply[:1200]}")
            parts.append("Recent conversation:\n" + "\n".join(lines))

        visuals: list[VisualInput] = []
        relevant_artifacts = self._select_relevant_artifacts(session, user_message) if include_artifacts else []
        if relevant_artifacts:
            artifact_blocks = []
            for artifact in relevant_artifacts:
                excerpt = self._excerpt_for_query(artifact, user_message)
                block = (
                    f"Title: {artifact.title}\n"
                    f"Source: {artifact.source_label}\n"
                    f"Original user request: {artifact.user_request or 'None'}\n"
                    f"Metadata: {artifact.metadata}\n"
                    f"Issues: {artifact.issues or ['None']}\n"
                    f"Runtime diary: {artifact.runtime_diary or ['None']}\n"
                    f"Media reviewed: {artifact.reviewed_media or ['None']}\n"
                    f"Video interval history: {artifact.video_interval_history or ['None']}\n"
                    f"Related URLs: {artifact.related_urls or ['None']}\n"
                    f"Relevant content:\n{excerpt}"
                )
                artifact_blocks.append(block)
                visuals.extend(artifact.visual_inputs[:2])
            parts.append("Relevant source memory:\n\n" + "\n\n".join(artifact_blocks))

        return "\n\n".join(parts).strip(), visuals[:4]

    def get_primary_artifact(
        self,
        key: tuple[int, int],
        user_message: str,
    ) -> StoredArtifact | None:
        session = self._prune_and_get(key)
        if not session:
            return None
        relevant_artifacts = self._select_relevant_artifacts(session, user_message)
        return relevant_artifacts[0] if relevant_artifacts else None

    def _get_session(self, key: tuple[int, int]) -> SessionState:
        session = self.sessions.get(key)
        if session is None:
            session = SessionState()
            self.sessions[key] = session
        return session

    def _prune_and_get(self, key: tuple[int, int]) -> SessionState | None:
        session = self.sessions.get(key)
        if session is None:
            return None
        if time() - session.updated_at > self.ttl_seconds:
            self.sessions.pop(key, None)
            return None
        return session

    def _select_relevant_artifacts(
        self,
        session: SessionState,
        user_message: str,
    ) -> list[StoredArtifact]:
        if not session.artifacts:
            return []

        latest_artifact = session.artifacts[-1]
        if not _references_older_source(user_message, latest_artifact):
            return [latest_artifact]

        scored = []
        query_terms = _keywords(user_message)
        for index, artifact in enumerate(session.artifacts):
            score = 0
            haystack = (
                f"{artifact.title} {artifact.source_label} {artifact.user_request} "
                f"{artifact.body[:10000]}"
            ).lower()
            for term in query_terms:
                if term in haystack:
                    score += 3
            if artifact is latest_artifact:
                score -= 3
            score += index
            score += _artifact_reference_bonus(artifact, user_message)
            scored.append((score, artifact))

        scored.sort(key=lambda item: item[0], reverse=True)
        chosen = [artifact for score, artifact in scored[:2] if score > 0]
        if not chosen and session.artifacts:
            return [latest_artifact]
        return chosen

    def _excerpt_for_query(self, artifact: StoredArtifact, user_message: str) -> str:
        body = artifact.body
        if len(body) <= 6000:
            return body
        query_terms = _keywords(user_message)
        scored_chunks: list[tuple[int, str]] = []
        for index, chunk in enumerate(artifact.chunks):
            score = 0
            lowered = chunk.lower()
            for term in query_terms:
                if term in lowered:
                    score += 3
            if "table" in lowered:
                score += 1
            if "page " in lowered:
                score += 1
            if index == 0:
                score += 1
            scored_chunks.append((score, chunk))

        scored_chunks.sort(key=lambda item: item[0], reverse=True)
        selected = [chunk for score, chunk in scored_chunks[:3] if score > 0]
        if not selected:
            selected = artifact.chunks[:3]
        return "\n\n".join(selected)[:9000]


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[\w\u3400-\u9fff]+", text.lower())
    return [token for token in tokens if token not in STOP_WORDS and len(token) > 1]


def _references_older_source(user_message: str, latest_artifact: StoredArtifact) -> bool:
    lowered = user_message.lower()
    if any(marker in lowered or marker in user_message for marker in GO_BACK_MARKERS):
        return True
    return False


def _artifact_reference_bonus(artifact: StoredArtifact, user_message: str) -> int:
    score = 0
    lowered = user_message.lower()
    title_lower = artifact.title.lower()
    source_lower = artifact.source_label.lower()
    if artifact.title and title_lower in lowered:
        score += 8
    if artifact.source_label and source_lower in lowered:
        score += 8
    return score


def _chunk_text(text: str, chunk_size: int = 2500, overlap: int = 350) -> list[str]:
    if not text.strip():
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    if lines:
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > chunk_size:
                chunks.append("\n".join(current))
                carry = "\n".join(current)[-overlap:]
                current = [carry, line] if carry.strip() else [line]
                current_len = sum(len(part) + 1 for part in current)
                continue
            current.append(line)
            current_len += line_len
        if current:
            chunks.append("\n".join(current))
        return chunks[:24]

    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        start = max(end - overlap, start + 1)
    return chunks[:24]
