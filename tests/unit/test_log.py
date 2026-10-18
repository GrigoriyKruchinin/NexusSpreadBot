import json
import logging

import pytest
import structlog

from nexus.config.groups import LoggingSettings
from nexus.log import configure_logging, scrub

TOKEN = "123456789:AAHabcdefghijklmnopqrstuvwxyz0123456"


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        (f"POST https://api.telegram.org/bot{TOKEN}/sendMessage failed", TOKEN),
        (
            "binance GET https://api.binance.com/sapi/v1/x?timestamp=1&signature=deadbeef01",
            "deadbeef01",
        ),
        ("headers {'X-MBX-APIKEY': 'AbCdEf0123456789'}", "AbCdEf0123456789"),
        ("OK-ACCESS-KEY: 0123456789abcdef", "0123456789abcdef"),
        ("KC-API-PASSPHRASE=supersecretpass", "supersecretpass"),
    ],
)
def test_scrub_removes_secrets(raw: str, leak: str) -> None:
    assert leak not in scrub(raw)


def test_scrub_keeps_normal_text() -> None:
    text = "fetch_tickers ok in 120 ms for BTC/USDT"
    assert scrub(text) == text


def test_structlog_and_stdlib_are_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LoggingSettings(level="INFO", json_format=True), service="test")
    structlog.get_logger("t").warning("send_failed", url=f"/bot{TOKEN}/x", api_key="k1")
    logging.getLogger("ccxt.test").warning("GET /x?signature=abcdef123456 failed")
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert lines[0]["event"] == "send_failed"
    assert lines[0]["service"] == "test"
    assert lines[0]["api_key"] == "***"
    assert TOKEN not in json.dumps(lines)
    assert "abcdef123456" not in json.dumps(lines)
    structlog.reset_defaults()
