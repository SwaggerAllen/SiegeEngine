"""Logging handler that streams log entries to connected WebSocket clients."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone


class WebSocketLogHandler(logging.Handler):
    """Buffers log records and broadcasts them via the WS manager.

    Usage::

        handler = WebSocketLogHandler(project_id)
        handler.install()
        try:
            ...  # logs emitted here are streamed
        finally:
            handler.uninstall()

    Because ``emit()`` is synchronous (required by the logging API) we
    schedule the async broadcast on the running event loop via
    ``asyncio.create_task``.  If no loop is running the record is silently
    dropped.
    """

    # Only forward logs from these logger hierarchies to avoid noise.
    _ALLOWED_PREFIXES = (
        "backend.pipeline",
        "backend.cli",
    )

    def __init__(self, project_id: str, *, level: int = logging.INFO):
        super().__init__(level=level)
        self.project_id = project_id

    # ── public helpers ────────────────────────────────────────────────

    def install(self) -> None:
        """Attach this handler to the root logger."""
        logging.getLogger().addHandler(self)

    def uninstall(self) -> None:
        """Detach this handler from the root logger."""
        logging.getLogger().removeHandler(self)

    # ── logging.Handler interface ─────────────────────────────────────

    def emit(self, record: logging.LogRecord) -> None:
        # Filter to relevant loggers
        if not any(record.name.startswith(p) for p in self._ALLOWED_PREFIXES):
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop — skip silently

        event = {
            "type": "log_entry",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": self.format(record) if self.formatter else record.getMessage(),
        }

        loop.create_task(self._broadcast(event))

    async def _broadcast(self, event: dict) -> None:
        from backend.websocket.manager import ws_manager

        try:
            await ws_manager.broadcast(self.project_id, event)
        except Exception:
            pass  # never let WS errors break logging
