"""Telegram Bot API notifier (HTML parse mode)."""

from __future__ import annotations

from typing import Any

import httpx

from nexus.config.groups import TelegramSettings
from nexus.domain.errors import MessageGoneError, NotificationError, NotificationRejectedError
from nexus.interfaces.notifications import DeliveryReceipt, INotifier, OutgoingMessage
from nexus.notifications.rate_limit import SendRateLimiter

_CHANNEL = "telegram"
_NOT_MODIFIED = "message is not modified"
_GONE_MARKERS = (
    "message to edit not found",
    "message can't be edited",
    "message_id_invalid",
    "message identifier is not specified",
)


class TelegramNotifier(INotifier):
    """Sends messages via ``sendMessage`` and edits them via ``editMessageText``.

    The bot token is part of the request URL, so transport exceptions are never chained or
    echoed: only sanitized descriptions leave this class. With a ``limiter`` every call first
    waits for a rate-limit slot, and a 429 ``retry_after`` blocks the limiter for that long.
    """

    def __init__(
        self,
        settings: TelegramSettings,
        *,
        client: httpx.AsyncClient | None = None,
        limiter: SendRateLimiter | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.request_timeout_s)
        self._limiter = limiter

    def _url(self, method: str) -> str:
        token = self._settings.bot_token.get_secret_value()
        return f"{self._settings.api_base_url}/bot{token}/{method}"

    def _payload(self, message: OutgoingMessage) -> dict[str, Any]:
        return {
            "chat_id": self._settings.chat_id,
            "text": message.text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }

    async def send(self, message: OutgoingMessage) -> DeliveryReceipt:
        """Deliver ``message``; raises NotificationError / NotificationRejectedError."""
        payload = self._payload(message)
        payload["disable_notification"] = message.silent or self._settings.disable_notification
        body = await self._call("sendMessage", payload)
        return self._receipt(body)

    async def edit(self, message_id: str, message: OutgoingMessage) -> DeliveryReceipt:
        """Replace the text of ``message_id``; "message is not modified" counts as success."""
        payload = self._payload(message)
        payload["message_id"] = int(message_id)
        try:
            body = await self._call("editMessageText", payload)
        except NotificationRejectedError as exc:
            description = str(exc).lower()
            if _NOT_MODIFIED in description:
                return DeliveryReceipt(channel=_CHANNEL, message_id=message_id)
            if any(marker in description for marker in _GONE_MARKERS):
                raise MessageGoneError(str(exc)) from None
            raise
        return self._receipt(body, fallback_id=message_id)

    @staticmethod
    def _receipt(body: dict[str, Any], fallback_id: str | None = None) -> DeliveryReceipt:
        result = body.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        return DeliveryReceipt(
            channel=_CHANNEL,
            message_id=str(message_id) if message_id is not None else fallback_id,
        )

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._limiter is not None:
            await self._limiter.acquire()
        try:
            response = await self._client.post(self._url(method), json=payload)
        except httpx.TimeoutException:
            raise NotificationError("telegram request timed out") from None
        except httpx.HTTPError as exc:
            raise NotificationError(f"telegram transport error: {type(exc).__name__}") from None

        body = self._json(response)
        if response.status_code == httpx.codes.OK and body.get("ok") is True:
            return body

        description = str(body.get("description") or f"HTTP {response.status_code}")[:300]
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            retry_after = (body.get("parameters") or {}).get("retry_after")
            wait = float(retry_after) if isinstance(retry_after, int | float) else None
            if wait is not None and self._limiter is not None:
                self._limiter.block_for(wait)
            raise NotificationError(f"telegram rate limit: {description}", retry_after_s=wait)
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
