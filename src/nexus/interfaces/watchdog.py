"""Ports of the liveness watchdog."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchdogState:
    """Persistent per-check incident state (survives worker restarts)."""

    firing: bool = False
    """An alert was sent and not yet recovered."""
    since_ms: int | None = None
    """First time the current problem was observed (grace period and downtime base)."""
    reason: str | None = None


class IWatchdogState(ABC):
    """Stores one :class:`WatchdogState` per check."""

    @abstractmethod
    async def get(self, check: str) -> WatchdogState:
        """Current state (an empty state when nothing is stored)."""

    @abstractmethod
    async def save(self, check: str, state: WatchdogState) -> None:
        """Replace the stored state."""


class IScannerActivity(ABC):
    """Cheapest reliable sign of life of the scanner."""

    @abstractmethod
    async def last_activity_ms(self) -> int | None:
        """Epoch ms of the latest recorded exchange call, ``None`` if there is none."""


class IBackupStatusSource(ABC):
    """Reads the backup status file."""

    @abstractmethod
    async def read(self) -> str | None:
        """Raw file text, ``None`` when the file does not exist."""


@dataclass(frozen=True, slots=True)
class PaperSetActivity:
    """Freshness of one venue set's data."""

    started_ms: int
    """Start of the set's current run (registry; never purged)."""
    newest_hour_ms: int | None
    """Start of the newest ``paper_cap_stats`` hour, ``None`` when the set has no row."""


class IPaperSetActivity(ABC):
    """Read-only view of the paper venue sets' data freshness."""

    @abstractmethod
    async def read(self) -> dict[str, PaperSetActivity]:
        """Registered venue sets (current run each) with their newest stats hour."""
