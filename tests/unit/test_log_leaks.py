"""Leak proofs for log scrubbing (A4, S-04, S-07). All secrets here are synthetic."""

import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from nexus.config.groups import LoggingSettings
from nexus.log import configure_logging, scrub

# Assembled at runtime so no literal token-shaped string sits in the source.
FAKE_TOKEN = "123456789" + ":" + "FAKE" * 10
FAKE_PASS = "fakepass-not-real"


def _setup() -> None:
    configure_logging(LoggingSettings(level="INFO", json_format=True), service="test")


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"redis://user:{FAKE_PASS}@redis:6379/1", "redis://***@redis:6379/1"),
        (f"redis://:{FAKE_PASS}@redis", "redis://***@redis"),
        (
            f"postgresql+asyncpg://u:{FAKE_PASS}@db:5432/nexus",
            "postgresql+asyncpg://***@db:5432/nexus",
        ),
        (f"amqp://guest:{FAKE_PASS}@mq//", "amqp://***@mq//"),
    ],
)
def test_url_credentials_scrubbed(url: str, expected: str) -> None:
    out = scrub(f"connecting to {url} now")
    assert FAKE_PASS not in out
    assert expected in out


@pytest.mark.parametrize(
    "text",
    [
        "redis://redis:6379/1",
        "postgresql+asyncpg://db:5432/nexus",
        "listening on host:6379 and 127.0.0.1:5432",
        "https://api.binance.com/api/v3/ticker?symbol=BTCUSDT",
        "user@example.com wrote at 10:30: ok",
    ],
)
def test_url_scrub_no_false_positive(text: str) -> None:
    assert scrub(text) == text


def test_httpx_info_telegram_url_not_leaked(capsys: pytest.CaptureFixture[str]) -> None:
    _setup()
    url = f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
    logging.getLogger("httpx").info('HTTP Request: POST %s "HTTP/1.1 200 OK"', url)
    logging.getLogger("httpx").warning('HTTP Request: POST %s "HTTP/1.1 500"', url)
    assert FAKE_TOKEN not in _out(capsys)


@pytest.mark.parametrize(
    "name", ["httpx", "httpcore", "ccxt", "celery", "celery.worker.strategy", "root"]
)
def test_stdlib_loggers_scrub_message_and_args(
    capsys: pytest.CaptureFixture[str], name: str
) -> None:
    _setup()
    logger = logging.getLogger() if name == "root" else logging.getLogger(name)
    logger.error(f"msg /bot{FAKE_TOKEN}/x redis://:{FAKE_PASS}@h signature=zzfakesig1")
    logger.error("arg %s and %s", f"/bot{FAKE_TOKEN}/y", f"redis://u:{FAKE_PASS}@h")
    out = _out(capsys)
    assert len(out.strip().splitlines()) == 2
    for leak in (FAKE_TOKEN, FAKE_PASS, "zzfakesig1"):
        assert leak not in out


def test_celery_task_received_line_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    _setup()
    # Payloads must never carry secrets (target.md section 10); this proves the safety net.
    logging.getLogger("celery.worker.strategy").error(
        "Task nexus.send_alert[abc] received: args=(%r,) kwargs=%r",
        f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage",
        {"dsn": f"redis://:{FAKE_PASS}@redis:6379/1", "api_key": "k"},
    )
    out = _out(capsys)
    assert FAKE_TOKEN not in out
    assert FAKE_PASS not in out


def test_ccxt_auth_error_repr_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    _setup()
    exc = RuntimeError(
        f"binance {{'code':-2015}} headers {{'X-MBX-APIKEY': 'FAKEKEYFAKEKEY1'}} "
        f"https://x/y?signature=fakesig12345&apikey=FAKEKEYFAKEKEY1 redis://:{FAKE_PASS}@r"
    )
    structlog.get_logger("t").error("auth_failed", error=exc)
    try:
        raise exc
    except RuntimeError:
        structlog.get_logger("t").exception("auth_failed_tb")
        logging.getLogger("ccxt").exception("ccxt failed")
    out = _out(capsys)
    lines = [json.loads(line) for line in out.strip().splitlines()]
    assert len(lines) == 3
    for leak in ("FAKEKEYFAKEKEY1", "fakesig12345", FAKE_PASS):
        assert leak not in out
