from __future__ import annotations

class TypingIndicator:
    def __init__(self, channel, interval_seconds: float = 8.0) -> None:
        self.channel = channel
        self.interval_seconds = interval_seconds
        self._context_manager = None

    async def __aenter__(self):
        self._context_manager = self.channel.typing()
        await self._context_manager.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._context_manager is not None:
            await self._context_manager.__aexit__(exc_type, exc, tb)
        return False
