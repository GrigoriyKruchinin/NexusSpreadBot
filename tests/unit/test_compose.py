"""Container isolation: each service receives only the variables of its own domain."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from nexus.config.file import TOML_ALLOWED

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ["docker-compose.local.yml"]
APP_SERVICES = {"migrator", "scanner", "worker-alerts", "worker-maintenance", "beat"}

EXCHANGE_SECRET = re.compile(r"^(BYBIT|BINANCE|OKX|GATEIO|KUCOIN|MEXC|BITGET)_API_")
FORBIDDEN: dict[str, list[re.Pattern[str]]] = {
    "migrator": [
        re.compile(r"^(TELEGRAM|REDIS|CELERY|SCANNER|SPREAD|EPISODE|PAPER|ALERT|QUARANTINE)_"),
        EXCHANGE_SECRET,
    ],
    "scanner": [re.compile(r"^TELEGRAM_")],
    "worker-alerts": [
        EXCHANGE_SECRET,
        re.compile(r"^(REDIS|SCANNER|SPREAD|EXCHANGES|EPISODE|PAPER|ALERT|QUARANTINE)_"),
    ],
    "worker-maintenance": [
        EXCHANGE_SECRET,
        re.compile(r"^(TELEGRAM|REDIS|SCANNER|SPREAD|EPISODE|PAPER|ALERT|QUARANTINE)_"),
    ],
    "beat": [
        EXCHANGE_SECRET,
        re.compile(r"^(TELEGRAM|POSTGRES|REDIS|SCANNER|SPREAD|EPISODE|PAPER|ALERT|QUARANTINE)_"),
    ],
}


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((ROOT / name).read_text())
    return data


@pytest.mark.parametrize("compose", COMPOSE_FILES)
@pytest.mark.parametrize("service", sorted(FORBIDDEN))
def test_services_receive_only_their_domain(compose: str, service: str) -> None:
    env = _load(compose)["services"][service].get("environment", {})
    leaked = [k for k in env for pattern in FORBIDDEN[service] if pattern.match(k)]
    assert not leaked, f"{service} must not receive {leaked}"


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_every_documented_variable_reaches_a_service(compose: str) -> None:
    documented = set(
        re.findall(r"^([A-Z][A-Z0-9_]*)=", (ROOT / ".env.example").read_text(), re.MULTILINE)
    )
    services = _load(compose)["services"]
    passed = {key for svc in services.values() for key in (svc.get("environment") or {})}
    # Host-side connection defaults are replaced by compose service names.
    missing = documented - passed
    assert not missing, f"not wired into {compose}: {sorted(missing)}"


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_healthchecks_and_startup_order(compose: str) -> None:
    services = _load(compose)["services"]
    for name, svc in services.items():
        if name != "migrator":
            assert "healthcheck" in svc, f"{name} has no healthcheck"
    for name in APP_SERVICES:
        for dependency, spec in (services[name].get("depends_on") or {}).items():
            assert spec["condition"] in {"service_healthy", "service_completed_successfully"}, (
                name,
                dependency,
            )
    assert services["scanner"]["depends_on"]["migrator"]["condition"] == (
        "service_completed_successfully"
    )


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_containers_are_hardened(compose: str) -> None:
    services = _load(compose)["services"]
    for name in APP_SERVICES:
        svc = services[name]
        assert svc.get("read_only") is True, name
        assert "no-new-privileges:true" in svc.get("security_opt", []), name
    for name in ("postgres",):
        for port in services[name].get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} port exposed publicly: {port}"
    assert "ports" not in services["redis"]


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_extension_venue_keys_not_wired_by_default(compose: str) -> None:
    """B1a: MEXC_*/BITGET_* are absent from compose env and .env.example (ADR 0002)."""
    pattern = re.compile(r"^(MEXC|BITGET)_")
    for name, service in _load(compose)["services"].items():
        env = service.get("environment", {}) or {}
        keys = env.keys() if isinstance(env, dict) else [e.split("=", 1)[0] for e in env]
        assert not [k for k in keys if pattern.match(k)], f"{name} wires extension venue keys"
    example = (ROOT / ".env.example").read_text().splitlines()
    assert not [
        ln for ln in example if pattern.match(ln.lstrip("# ").strip()) and not ln.startswith("#")
    ], "extension keys present in .env.example"


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_settings_are_not_wired_through_compose(compose: str) -> None:
    """A7: tunables come from config/nexus.toml; only the host differs inside the stack."""
    services = _load(compose)["services"]
    wired = {key for svc in services.values() for key in (svc.get("environment") or {})}
    assert wired & TOML_ALLOWED == {"POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER"}
    for name in APP_SERVICES:
        env = services[name].get("environment", {})
        assert not ({"POSTGRES_DB", "POSTGRES_USER"} & set(env)), name


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_config_file_mounted_read_only_into_app_services(compose: str) -> None:
    services = _load(compose)["services"]
    for name in APP_SERVICES:
        assert "./config/nexus.toml:/app/config/nexus.toml:ro" in services[name]["volumes"], name


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_postgres_container_matches_toml_db_and_user(compose: str) -> None:
    import tomllib

    toml = tomllib.loads((ROOT / "config" / "nexus.toml").read_text())
    env = _load(compose)["services"]["postgres"]["environment"]
    assert env["POSTGRES_DB"] == toml["postgres"]["db"]
    assert env["POSTGRES_USER"] == toml["postgres"]["user"]
