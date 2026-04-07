from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


async def sweep_old_temp_files(directory: Path, max_age_hours: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    deleted = 0
    for item in directory.iterdir():
        if not item.is_file():
            continue
        modified_at = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
        if modified_at < cutoff:
            await asyncio.to_thread(item.unlink, True)
            deleted += 1
    return deleted
