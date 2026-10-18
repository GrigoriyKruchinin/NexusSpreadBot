"""Container isolation: each service receives only the variables of its own domain."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ["docker-compose.local.yml"]
APP_SERVICES = {"migrator", "scanner", "worker-alerts", "worker-maintenance", "beat"}

EXCHANGE_SECRET = re.compile(r"^(BYBIT|BINANCE|OKX|GATEIO|KUCOIN)_API_")
FORBIDDEN: dict[str, list[re.Pattern[str]]] = {
    "migrator": [re.compile(r"^(TELEGRAM|REDIS|CELERY|SCANNER|SPREAD)_"), EXCHANGE_SECRET],
    "scanner": [re.compile(r"^TELEGRAM_")],
    "worker-alerts": [EXCHANGE_SECRET, re.compile(r"^(REDIS|SCANNER|SPREAD|EXCHANGES)_")],
    "worker-maintenance": [EXCHANGE_SECRET, re.compile(r"^(TELEGRAM|REDIS|SCANNER|SPREAD)_")],
    "beat": [EXCHANGE_SECRET, re.compile(r"^(TELEGRAM|POSTGRES|REDIS|SCANNER|SPREAD)_")],
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
    missing = documented - passed - {"POSTGRES_HOST", "POSTGRES_PORT"}
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
