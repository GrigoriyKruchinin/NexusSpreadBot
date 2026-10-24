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
def test_config_file_is_baked_into_the_image_not_bind_mounted(compose: str) -> None:
    """D-01b: a WSL bind mount is not ready when Docker Desktop restarts containers (Exited 127)."""
    services = _load(compose)["services"]
    for name in APP_SERVICES:
        for volume in services[name].get("volumes", []):
            assert "nexus.toml" not in str(volume), name
    # Only the backup-status dir may remain a host bind mount (worker-maintenance, see its comment).
    binds = {
        name: [
            v
            for v in svc.get("volumes", [])
            if isinstance(v, dict) or v.startswith(("./", "/", "$"))
        ]
        for name, svc in services.items()
    }
    assert {k: v for k, v in binds.items() if v and k != "worker-maintenance"} == {}
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY config/nexus.toml ./config/nexus.toml" in dockerfile.split("AS runtime", 1)[1]


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_postgres_container_matches_toml_db_and_user(compose: str) -> None:
    import tomllib

    toml = tomllib.loads((ROOT / "config" / "nexus.toml").read_text())
    env = _load(compose)["services"]["postgres"]["environment"]
    assert env["POSTGRES_DB"] == toml["postgres"]["db"]
    assert env["POSTGRES_USER"] == toml["postgres"]["user"]


def _wrapper_script(compose: str) -> str:
    command = _load(compose)["services"]["scanner"]["command"]
    assert command[:2] == ["sh", "-c"]
    return str(command[2]).replace("$$", "$")  # compose escapes `$` as `$$`


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_scanner_restart_policy(compose: str) -> None:
    """D-01: restarted after a daemon restart (unless-stopped); exit 3 is handled by parking."""
    assert _load(compose)["services"]["scanner"]["restart"] == "unless-stopped"


def _run_wrapper(
    tmp_path: Path, scanner_body: str, signal_at: str | None = None
) -> tuple[int | None, str]:
    """Run the real wrapper with a fake `nexus`; optionally SIGTERM it while running or parked."""
    import os
    import signal
    import subprocess
    import time

    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "nexus"
    fake.write_text("#!/bin/sh\n" + scanner_body)
    fake.chmod(0o755)
    marker = tmp_path / "events"
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "MARKER": str(marker)}
    proc = subprocess.Popen(  # noqa: S603
        ["/bin/sh", "-c", _wrapper_script(COMPOSE_FILES[0])],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if signal_at is not None:
            deadline = time.monotonic() + 10
            want = "started" if signal_at == "run" else "exit3"
            while time.monotonic() < deadline and want not in (
                marker.read_text() if marker.exists() else ""
            ):
                time.sleep(0.05)
            time.sleep(0.5)  # let the wrapper reach wait/park
            proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=10 if signal_at else 20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None, "TIMEOUT"
    finally:
        if proc.poll() is None:
            os.kill(proc.pid, signal.SIGKILL)
    events = marker.read_text() if marker.exists() else ""
    return proc.returncode, events + out + err


def test_wrapper_exit_codes_propagate(tmp_path: Path) -> None:
    rc, _ = _run_wrapper(tmp_path, "exit 1\n")
    assert rc == 1


def test_wrapper_clean_exit_is_zero(tmp_path: Path) -> None:
    rc, _ = _run_wrapper(tmp_path, "exit 0\n")
    assert rc == 0


def test_wrapper_exit_3_parks_until_sigterm_then_exits_0(tmp_path: Path) -> None:
    body = 'echo exit3 >> "$MARKER"\nexit 3\n'
    rc, out = _run_wrapper(tmp_path, body, signal_at="park")
    assert rc == 0, (
        out
    )  # parked (did not exit by itself within the wait) and ended promptly on TERM
    assert "parked" in out


def test_wrapper_exit_3_does_not_exit_by_itself(tmp_path: Path) -> None:
    import subprocess

    (tmp_path / "bin").mkdir()
    fake = tmp_path / "bin" / "nexus"
    fake.write_text("#!/bin/sh\nexit 3\n")
    fake.chmod(0o755)
    proc = subprocess.Popen(  # noqa: S603
        ["/bin/sh", "-c", _wrapper_script(COMPOSE_FILES[0])],
        env={"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"},
        stderr=subprocess.DEVNULL,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=2)
    finally:
        proc.kill()
        proc.wait()


def test_wrapper_forwards_sigterm_to_the_running_scanner(tmp_path: Path) -> None:
    body = (
        "trap 'echo got-term >> \"$MARKER\"; exit 0' TERM\n"
        'echo started >> "$MARKER"\n'
        "while :; do sleep 0.1; done\n"
    )
    rc, out = _run_wrapper(tmp_path, body, signal_at="run")
    assert rc == 0, out
    assert "got-term" in out


def test_wrapper_propagates_scanner_failure_after_sigterm(tmp_path: Path) -> None:
    body = "trap 'exit 5' TERM\necho started >> \"$MARKER\"\nwhile :; do sleep 0.1; done\n"
    rc, _ = _run_wrapper(tmp_path, body, signal_at="run")
    assert rc == 5


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_maintenance_worker_mounts_backup_status_read_only(compose: str) -> None:
    services = _load(compose)["services"]
    mounts = [
        v
        for v in services["worker-maintenance"]["volumes"]
        if isinstance(v, dict) and v.get("target") == "/backups"
    ]
    assert len(mounts) == 1  # long syntax only: short syntax cannot forbid host-path creation
    mount = mounts[0]
    assert mount["type"] == "bind"
    assert mount["source"].endswith("/nexus-backup-status")  # status dir, never the 0700 dump dir
    assert mount["read_only"] is True
    assert mount["bind"]["create_host_path"] is False  # missing source must fail, not start empty
    for name, svc in services.items():
        if name != "worker-maintenance":
            assert not any("/backups" in str(v) for v in svc.get("volumes", [])), name


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_soak_volumes_are_pinned_fresh_and_distinct_from_old(compose: str) -> None:
    volumes = _load(compose)["volumes"]
    assert volumes["postgres-data"]["name"] == "nexus-local_postgres-data-soak1"
    assert volumes["redis-data"]["name"] == "nexus-local_redis-data-soak1"


def test_bootstrap_roles_target_is_safe() -> None:
    makefile = (ROOT / "Makefile").read_text()
    recipe = makefile.split("\nbootstrap-roles:", 1)[1]
    assert "grep -qx postgres" in recipe  # fails clearly when postgres is not running
    assert "-v ON_ERROR_STOP=1" in recipe
    assert "< scripts/sql/bootstrap_backup_roles.sql" in recipe
    assert "PASSWORD" not in recipe.upper()
    sql = (ROOT / "scripts/sql/bootstrap_backup_roles.sql").read_text()
    assert not re.search(
        r"(?im)^[^-\n]*\bPASSWORD\b", sql
    )  # roles are socket-only, no secret to supply


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_ip_binding_waiver_reaches_only_the_scanner(compose: str) -> None:
    """KP-W / F-1: the env-only waiver is wired to the scanner and to no other service."""
    services = _load(compose)["services"]
    holders = {
        name
        for name, svc in services.items()
        if "KEY_POLICY_IP_BINDING_WAIVED" in (svc.get("environment") or {})
    }
    assert holders == {"scanner"}
