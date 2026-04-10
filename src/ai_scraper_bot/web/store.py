from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_scraper_bot.models import ExtractedContent, VisualInput
from ai_scraper_bot.utils.files import ensure_directory
from ai_scraper_bot.utils.session_memory import SessionMemoryStore


@dataclass(slots=True)
class ChatRecord:
    id: int
    title: str
    created_at: str
    updated_at: str
    message_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
        }


@dataclass(slots=True)
class MessageRecord:
    id: int
    chat_id: int
    role: str
    content: str
    status: str
    attachment_name: str | None
    source_kind: str | None
    metadata: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "role": self.role,
            "content": self.content,
            "status": self.status,
            "attachment_name": self.attachment_name,
            "source_kind": self.source_kind,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class WebChatStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        ensure_directory(db_path.parent)
        self._initialize()

    def list_chats(self) -> list[ChatRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COALESCE(SUM(CASE WHEN m.hidden = 0 THEN 1 ELSE 0 END), 0) AS message_count
                FROM chats AS c
                LEFT JOIN messages AS m ON m.chat_id = c.id
                GROUP BY c.id
                ORDER BY c.updated_at DESC, c.id DESC
                """
            ).fetchall()
        return [self._chat_from_row(row) for row in rows]

    def count_chats(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM chats").fetchone()
        return int(row["count"]) if row is not None else 0

    def create_chat(self, title: str | None = None) -> ChatRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM chats").fetchone()
            chat_count = int(row["count"]) if row is not None else 0
        if chat_count >= 10:
            raise RuntimeError("You can have at most 10 chats at a time.")
        now = _utc_now()
        with self._connect() as connection:
            resolved_title = (title or "").strip()
            if not resolved_title:
                resolved_title = self._next_default_chat_title(connection)
            cursor = connection.execute(
                """
                INSERT INTO chats (title, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (resolved_title, now, now),
            )
            chat_id = int(cursor.lastrowid)
            connection.commit()
        return self.get_chat(chat_id)

    def get_chat(self, chat_id: int) -> ChatRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COALESCE(SUM(CASE WHEN m.hidden = 0 THEN 1 ELSE 0 END), 0) AS message_count
                FROM chats AS c
                LEFT JOIN messages AS m ON m.chat_id = c.id
                WHERE c.id = ?
                GROUP BY c.id
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Chat {chat_id} was not found.")
        return self._chat_from_row(row)

    def update_chat_title(self, chat_id: int, title: str) -> ChatRecord:
        current = self.get_chat(chat_id)
        cleaned = title.strip() or current.title
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE chats
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (cleaned, _utc_now(), chat_id),
            )
            connection.commit()
        return self.get_chat(chat_id)

    def clear_all_chats(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM chats")
            connection.execute(
                """
                INSERT INTO app_meta (key, value)
                VALUES ('next_agent_chat_number', '1')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )
            connection.commit()

    def add_message(
        self,
        *,
        chat_id: int,
        role: str,
        content: str,
        status: str = "completed",
        attachment_name: str | None = None,
        source_kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MessageRecord:
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages (
                    chat_id,
                    role,
                    content,
                    status,
                    attachment_name,
                    source_kind,
                    metadata_json,
                    created_at,
                    hidden
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    chat_id,
                    role,
                    content,
                    status,
                    attachment_name,
                    source_kind,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                ),
            )
            connection.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (now, chat_id),
            )
            connection.commit()
            message_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, chat_id, role, content, status, attachment_name, source_kind, metadata_json, created_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Message {message_id} was not found after insert.")
        return self._message_from_row(row)

    def list_messages(self, chat_id: int) -> list[MessageRecord]:
        return self._select_messages(chat_id, include_hidden=False)

    def list_all_messages(self, chat_id: int) -> list[MessageRecord]:
        return self._select_messages(chat_id, include_hidden=True)

    def clear_chat_messages(self, chat_id: int) -> ChatRecord:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE messages
                SET hidden = 1
                WHERE chat_id = ?
                """,
                (chat_id,),
            )
            connection.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (_utc_now(), chat_id),
            )
            connection.commit()
        return self.get_chat(chat_id)

    def delete_chat(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            connection.commit()

    def add_artifact(
        self,
        *,
        chat_id: int,
        extracted: ExtractedContent,
        user_request: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts (
                    chat_id,
                    title,
                    source_label,
                    body,
                    metadata_json,
                    visual_inputs_json,
                    issues_json,
                    runtime_diary_json,
                    reviewed_media_json,
                    video_interval_history_json,
                    related_urls_json,
                    user_request,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    extracted.title,
                    extracted.source_label,
                    extracted.body,
                    json.dumps(extracted.metadata, ensure_ascii=False),
                    json.dumps(
                        [
                            {"kind": item.kind, "value": item.value, "label": item.label}
                            for item in extracted.visual_inputs
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(extracted.issues, ensure_ascii=False),
                    json.dumps(extracted.runtime_diary, ensure_ascii=False),
                    json.dumps(extracted.reviewed_media, ensure_ascii=False),
                    json.dumps(extracted.video_interval_history, ensure_ascii=False),
                    json.dumps(extracted.related_urls, ensure_ascii=False),
                    user_request,
                    _utc_now(),
                ),
            )
            connection.commit()

    def hydrate_memory(self, memory: SessionMemoryStore) -> None:
        for chat in self.list_chats():
            self.hydrate_chat_memory(memory, chat.id)

    def hydrate_chat_memory(self, memory: SessionMemoryStore, chat_id: int) -> None:
        chat = self.get_chat(chat_id)
        key = (chat.id, 0)
        user_prompt: str | None = None
        for message in self.list_all_messages(chat.id):
            if message.role == "user":
                user_prompt = message.content or (message.attachment_name or "")
                continue
            if message.role == "assistant" and user_prompt is not None:
                if not _looks_like_memory_polluting_reply(message.content):
                    memory.add_turn(key, user_prompt, message.content)
                user_prompt = None

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    title,
                    source_label,
                    body,
                    metadata_json,
                    visual_inputs_json,
                    issues_json,
                    runtime_diary_json,
                    reviewed_media_json,
                    video_interval_history_json,
                    related_urls_json,
                    user_request
                FROM artifacts
                WHERE chat_id = ?
                ORDER BY id ASC
                """,
                (chat.id,),
            ).fetchall()
        for row in rows:
            extracted = ExtractedContent(
                title=row["title"],
                body=row["body"],
                source_label=row["source_label"],
                metadata=_json_object(row["metadata_json"]),
                visual_inputs=[
                    VisualInput(
                        kind=item.get("kind", "image_data"),
                        value=item.get("value", ""),
                        label=item.get("label", ""),
                    )
                    for item in _json_list(row["visual_inputs_json"])
                    if item.get("value")
                ],
                issues=[str(item) for item in _json_list(row["issues_json"])],
                runtime_diary=[str(item) for item in _json_list(row["runtime_diary_json"])],
                reviewed_media=[str(item) for item in _json_list(row["reviewed_media_json"])],
                video_interval_history=[
                    str(item) for item in _json_list(row["video_interval_history_json"])
                ],
                related_urls=[str(item) for item in _json_list(row["related_urls_json"])],
            )
            memory.add_artifact(key, extracted, str(row["user_request"] or ""))

    def list_artifacts_for_chat(self, chat_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT title, source_label, body, metadata_json, issues_json, reviewed_media_json, created_at
                FROM artifacts
                WHERE chat_id = ?
                ORDER BY id DESC
                """,
                (chat_id,),
            ).fetchall()
        return [
            {
                "title": str(row["title"]),
                "source_label": str(row["source_label"]),
                "body_preview": str(row["body"])[:1200],
                "metadata": _json_object(row["metadata_json"]),
                "issues": [str(item) for item in _json_list(row["issues_json"])],
                "reviewed_media": [str(item) for item in _json_list(row["reviewed_media_json"])],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def clear_memory_for_chat(self, memory: SessionMemoryStore, chat_id: int) -> None:
        memory.sessions.pop((chat_id, 0), None)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;
                PRAGMA temp_store = MEMORY;

                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attachment_name TEXT,
                    source_kind TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    source_label TEXT NOT NULL,
                    body TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    visual_inputs_json TEXT NOT NULL DEFAULT '[]',
                    issues_json TEXT NOT NULL DEFAULT '[]',
                    runtime_diary_json TEXT NOT NULL DEFAULT '[]',
                    reviewed_media_json TEXT NOT NULL DEFAULT '[]',
                    video_interval_history_json TEXT NOT NULL DEFAULT '[]',
                    related_urls_json TEXT NOT NULL DEFAULT '[]',
                    user_request TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id, id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_chat_id ON artifacts(chat_id, id);
                """
            )
            message_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "hidden" not in message_columns:
                connection.execute(
                    "ALTER TABLE messages ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"
                )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _next_default_chat_title(self, connection: sqlite3.Connection) -> str:
        count_row = connection.execute("SELECT COUNT(*) AS count FROM chats").fetchone()
        chat_count = int(count_row["count"]) if count_row is not None else 0
        if chat_count == 0:
            next_number = 1
        else:
            stored = self._meta_int(connection, "next_agent_chat_number")
            if stored is None:
                max_row = connection.execute(
                    """
                    SELECT MAX(CAST(SUBSTR(title, 13) AS INTEGER)) AS max_number
                    FROM chats
                    WHERE title GLOB 'Agent Chat #[0-9]*'
                    """
                ).fetchone()
                max_number = int(max_row["max_number"]) if max_row and max_row["max_number"] else chat_count
                next_number = max_number + 1
            else:
                next_number = stored
        connection.execute(
            """
            INSERT INTO app_meta (key, value)
            VALUES ('next_agent_chat_number', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(next_number + 1),),
        )
        return f"Agent Chat #{next_number}"

    def _meta_int(self, connection: sqlite3.Connection, key: str) -> int | None:
        row = connection.execute(
            "SELECT value FROM app_meta WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return None

    def _select_messages(self, chat_id: int, *, include_hidden: bool) -> list[MessageRecord]:
        query = """
            SELECT id, chat_id, role, content, status, attachment_name, source_kind, metadata_json, created_at
            FROM messages
            WHERE chat_id = ?
        """
        params: list[object] = [chat_id]
        if not include_hidden:
            query += " AND hidden = 0"
        query += " ORDER BY id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._message_from_row(row) for row in rows]

    def _chat_from_row(self, row: sqlite3.Row) -> ChatRecord:
        return ChatRecord(
            id=int(row["id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            message_count=int(row["message_count"]),
        )

    def _message_from_row(self, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            status=str(row["status"]),
            attachment_name=row["attachment_name"],
            source_kind=row["source_kind"],
            metadata=_json_object(row["metadata_json"]),
            created_at=str(row["created_at"]),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(raw: str | None) -> list[dict[str, Any] | str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _looks_like_memory_polluting_reply(text: str) -> bool:
    lowered = (text or "").lower()
    markers = (
        "**temporary fallback result**",
        "i couldn't fully process that file",
        "did not complete cleanly",
        "i took too long to answer",
        "i ran into a problem while generating the reply",
    )
    return any(marker in lowered for marker in markers)
