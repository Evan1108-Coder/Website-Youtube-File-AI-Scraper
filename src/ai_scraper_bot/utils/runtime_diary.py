from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import threading
from time import time
from typing import Iterable


@dataclass(slots=True)
class DiaryEntry:
    created_at: float
    logger_name: str
    level_name: str
    rendered: str


_LOCK = threading.Lock()
_ENTRIES: deque[DiaryEntry] = deque(maxlen=400)


class RuntimeDiaryHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            rendered = self.format(record)
        except Exception:
            rendered = f"{record.levelname} {record.name}: {record.getMessage()}"
        with _LOCK:
            _ENTRIES.append(
                DiaryEntry(
                    created_at=time(),
                    logger_name=record.name,
                    level_name=record.levelname,
                    rendered=rendered,
                )
            )


def install_runtime_diary_handler() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RuntimeDiaryHandler):
            return

    handler = RuntimeDiaryHandler()
    formatter = None
    for existing in root.handlers:
        if existing.formatter is not None:
            formatter = existing.formatter
            break
    if formatter is None:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_recent_runtime_diary(
    *,
    limit: int = 12,
    keywords: Iterable[str] | None = None,
    logger_prefixes: Iterable[str] | None = None,
) -> list[str]:
    normalized_keywords = [value.strip().lower() for value in (keywords or []) if value and value.strip()]
    normalized_prefixes = tuple(value.strip() for value in (logger_prefixes or ()) if value and value.strip())
    with _LOCK:
        entries = list(_ENTRIES)
    if not entries:
        return []

    matched: list[str] = []
    for entry in entries:
        if normalized_prefixes and not any(entry.logger_name.startswith(prefix) for prefix in normalized_prefixes):
            continue
        rendered_lower = entry.rendered.lower()
        if normalized_keywords and not any(keyword in rendered_lower for keyword in normalized_keywords):
            continue
        matched.append(entry.rendered)
    if matched:
        return matched[-limit:]

    fallback = [
        entry.rendered
        for entry in entries
        if not normalized_prefixes or any(entry.logger_name.startswith(prefix) for prefix in normalized_prefixes)
    ]
    return fallback[-limit:]
