"""Telegram Bot API notifier (HTML parse mode)."""

from __future__ import annotations

from typing import Any

import httpx

from nexus.config.groups import TelegramSettings
from nexus.domain.errors import NotificationError, NotificationRejectedError
from nexus.interfaces.notifications import DeliveryReceipt, INotifier, OutgoingMessage

_CHANNEL = "telegram"


class TelegramNotifier(INotifier):
    """Sends messages via ``sendMessage``.

    The bot token is part of the request URL, so transport exceptions are never chained or
    echoed: only sanitized descriptions leave this class.
    """

    def __init__(
        self, settings: TelegramSettings, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.request_timeout_s)

    @property
    def _url(self) -> str:
        token = self._settings.bot_token.get_secret_value()
        return f"{self._settings.api_base_url}/bot{token}/sendMessage"

    async def send(self, message: OutgoingMessage) -> DeliveryReceipt:
        """Deliver ``message``; raises NotificationError / NotificationRejectedError."""
        payload: dict[str, Any] = {
            "chat_id": self._settings.chat_id,
            "text": message.text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "disable_notification": message.silent or self._settings.disable_notification,
        }
        try:
            response = await self._client.post(self._url, json=payload)
        except httpx.TimeoutException:
            raise NotificationError("telegram request timed out") from None
        except httpx.HTTPError as exc:
            raise NotificationError(f"telegram transport error: {type(exc).__name__}") from None

        body = self._json(response)
        if response.status_code == httpx.codes.OK and body.get("ok") is True:
            message_id = (body.get("result") or {}).get("message_id")
            return DeliveryReceipt(channel=_CHANNEL, message_id=str(message_id))

        description = str(body.get("description") or f"HTTP {response.status_code}")[:300]
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            retry_after = (body.get("parameters") or {}).get("retry_after")
            raise NotificationError(
                f"telegram rate limit: {description}",
                retry_after_s=float(retry_after) if isinstance(retry_after, int | float) else None,
            )
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise NotificationError(f"telegram server error: {description}")
        raise NotificationRejectedError(f"telegram rejected message: {description}")

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
