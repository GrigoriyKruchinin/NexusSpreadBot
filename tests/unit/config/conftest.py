from pathlib import Path

import pytest

_PREFIXES = (
    "POSTGRES_",
    "REDIS_",
    "CELERY_",
    "TELEGRAM_",
    "LOG_",
    "EXCHANGES_",
    "CONDITIONAL_",
    "SCANNER_",
    "SPREAD_",
    "MAINTENANCE_",
    "EPISODE_",
    "ALERT_",
    "DIGEST_",
    "QUARANTINE_",
    "MEXC_",
    "BITGET_",
    "BYBIT_",
    "BINANCE_",
    "OKX_",
    "GATEIO_",
    "KUCOIN_",
    "KEY_POLICY_",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run each settings test in an empty dir (no .env) with no inherited Nexus variables."""
    import os

    for key in list(os.environ):
        if key.startswith(_PREFIXES):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NEXUS_RUNTIME", raising=False)
    monkeypatch.delenv("NEXUS_WORKER_ROLE", raising=False)
    monkeypatch.delenv("NEXUS_CONFIG_FILE", raising=False)  # default path, relative to tmp cwd
    monkeypatch.chdir(tmp_path)
