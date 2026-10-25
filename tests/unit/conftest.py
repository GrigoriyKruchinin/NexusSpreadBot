"""Unit tests are hermetic: no implicit use of the repo ``config/nexus.toml`` (A7, risk R2)."""

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def _empty_config_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("nexus-config") / "empty.toml"
    path.write_text("# hermetic unit-test settings file: no keys, code defaults apply\n")
    return path


@pytest.fixture(autouse=True)
def _hermetic_config_file(monkeypatch: pytest.MonkeyPatch, _empty_config_file: Path) -> None:
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(_empty_config_file))


# Variable prefixes of every settings group (kept broad on purpose: a hostile local environment
# must never change a unit-test outcome).
_NEXUS_ENV_PREFIXES = (
    "POSTGRES_", "REDIS_", "CELERY_", "TELEGRAM_", "LOG_", "EXCHANGES_", "CONDITIONAL_",
    "SCANNER_", "SPREAD_", "MAINTENANCE_", "EPISODE_", "ALERT_", "DIGEST_", "QUARANTINE_",
    "MEXC_", "BITGET_", "BYBIT_", "BINANCE_", "OKX_", "GATEIO_", "KUCOIN_", "KEY_POLICY_",
    "NEXUS_",
)  # fmt: skip


@pytest.fixture(autouse=True)
def _hermetic_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _empty_config_file: Path
) -> None:
    """No developer ``.env`` (cwd is an empty tmp dir) and no inherited Nexus variables (T11)."""
    for key in list(os.environ):
        if key.startswith(_NEXUS_ENV_PREFIXES):
            monkeypatch.delenv(key)
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(_empty_config_file))
    monkeypatch.chdir(tmp_path)
