"""Reads the backup status file written by ``scripts/backup.sh`` (read-only mount)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nexus.interfaces.watchdog import IBackupStatusSource

MAX_STATUS_BYTES = 4_096
"""The file holds four small fields; anything larger is not ours and reads as unreadable."""


class FileBackupStatus(IBackupStatusSource):
    """Status file on a mounted volume."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    async def read(self) -> str | None:
        """File text, ``None`` if absent; other I/O errors propagate (the check logs them)."""
        return await asyncio.to_thread(self._read)

    def _read(self) -> str | None:
        try:
            with self._path.open("rb") as handle:
                data = handle.read(MAX_STATUS_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(data) > MAX_STATUS_BYTES:
            return "{}"  # parsed as unreadable
        return data.decode("utf-8", errors="replace")
