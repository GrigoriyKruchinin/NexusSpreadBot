"""Notification delivery interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """A pre-rendered message ready for delivery."""

    text: str
    silent: bool = False


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Result of a successful delivery."""

    channel: str
    message_id: str


class INotifier(ABC):
    """Delivers pre-rendered messages to a channel (Telegram, e-mail, ...)."""

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> DeliveryReceipt:
        """Deliver ``message``; raises :class:`~nexus.domain.errors.NexusError` on failure."""

    @abstractmethod
    async def close(self) -> None:
        """Release network resources."""
