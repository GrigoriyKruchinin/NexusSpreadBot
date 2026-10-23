"""Structured logging configuration with secret scrubbing.

Both structlog events and stdlib records (ccxt, httpx, celery) go through the same processor
chain, which masks sensitive keys and scrubs secret-looking substrings from every string.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, Final

import structlog
from structlog.typing import EventDict, Processor

from nexus.config.groups import LoggingSettings

_SENSITIVE_KEYS: Final = frozenset(
    {"api_key", "apikey", "secret", "api_secret", "password", "passphrase", "token", "bot_token"}
)
_SECRET_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # Telegram bot token, also inside API URLs (/bot<token>/sendMessage)
    (re.compile(r"(?<!\d)\d{6,}:[A-Za-z0-9_-]{30,}"), "<telegram-token>"),
    # URL credentials (redis/postgres/amqp DSNs): scheme://user:pass@host -> scheme://***@host
    (re.compile(r"://[^:/@\s]*:[^@\s]+@"), "://***@"),
    # Signed query parameters
    (re.compile(r"(?i)\b(signature|sign|apikey|api_key|passphrase)=([^&\s\"']+)"), r"\1=***"),
    # Exchange auth headers rendered in error messages
    (
        re.compile(
            r"(?i)\b(X-MBX-APIKEY|X-BAPI-API-KEY|X-BAPI-SIGN|OK-ACCESS-[A-Z]+|KC-API-[A-Z-]+|"
            r"KEY|SIGN)(['\"]?\s*[:=]\s*['\"]?)([A-Za-z0-9+/=_-]{8,})"
        ),
        r"\1\2***",
    ),
)


def scrub(text: str) -> str:
    """Remove secret-looking substrings from ``text``."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, BaseException):
        return scrub(repr(value))
    return value


def redact_processor(_logger: object, _method: str, event_dict: EventDict) -> EventDict:
    """Mask sensitive keys and scrub every string value (incl. rendered exceptions)."""
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***"
        else:
            event_dict[key] = _scrub_value(event_dict[key])
    return event_dict


def configure_logging(settings: LoggingSettings, *, service: str) -> None:
    """Configure structlog and route stdlib logging through the same processors."""
    level = getattr(logging, settings.level)
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.json_format
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_processor,  # after format_exc_info so tracebacks are scrubbed too
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("ccxt", "httpx", "httpcore", "asyncio", "aiohttp"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
    structlog.contextvars.bind_contextvars(service=service)
