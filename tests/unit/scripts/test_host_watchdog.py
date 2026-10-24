"""Shell-level tests for scripts/host_watchdog.sh (D-01b).

Hermetic like the backup script tests: minimal explicit env, HOME and state inside tmp_path,
fake `docker` / `curl` first on PATH. The fakes record argv and stdin; no daemon, no network.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "host_watchdog.sh"

# `ps` output is served from $FAKE_PS; after a `start` call from $FAKE_PS_AFTER (when present).
FAKE_DOCKER = """#!/bin/sh
[ -n "$FAKE_LOG" ] || { echo "fake docker used outside the sandbox" >&2; exit 99; }
echo "docker $*" >> "$FAKE_LOG"
case "$*" in
  info*) exit "${FAKE_INFO_EXIT:-0}" ;;
  *" start "*) touch "$FAKE_LOG.started"; exit "${FAKE_START_EXIT:-0}" ;;
  *" ps "*)
    if [ -f "$FAKE_LOG.started" ] && [ -f "$FAKE_PS_AFTER" ]; then
      cat "$FAKE_PS_AFTER"
    else
      cat "$FAKE_PS"
    fi ;;
esac
exit 0
"""
FAKE_CURL = """#!/bin/sh
[ -n "$FAKE_LOG" ] || { echo "fake curl used outside the sandbox" >&2; exit 99; }
echo "curl $*" >> "$FAKE_LOG"
cat >> "$FAKE_LOG.curl-stdin"
printf '%s' "${FAKE_HTTP:-200}"
exit "${FAKE_CURL_EXIT:-0}"
"""

# Records only the duration it was given, then runs the wrapped command.
FAKE_TIMEOUT = """#!/bin/sh
echo "timeout-arg $1" >> "$FAKE_LOG"
shift
exec "$@"
"""

HEALTHY = """beat running healthy
migrator exited
postgres running healthy
redis running healthy
scanner running healthy
worker-alerts running healthy
worker-maintenance running healthy
"""
TOKEN = "123456:SECRETtoken_value-xyz"
HB_URL = "https://hc-ping.example/uuid-SECRET"


@dataclass
class Sb:
    root: Path

    @property
    def log(self) -> Path:
        return self.root / "calls.log"

    @property
    def state(self) -> Path:
        return self.root / "home" / ".local" / "state" / "nexus-host-watchdog" / "state"

    def set_ps(self, text: str, after: str | None = None) -> None:
        (self.root / "ps").write_text(text)
        if after is not None:
            (self.root / "ps_after").write_text(after)

    def run(self, **more: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.root / 'bin'}:/usr/bin:/bin",
            "HOME": str(self.root / "home"),
            "COMPOSE_FILE": str(self.root / "no-such-compose.yml"),
            "WATCHDOG_ENV_FILE": str(self.root / "env"),
            "WATCHDOG_SETTLE_S": "0",
            "FAKE_LOG": str(self.log),
            "FAKE_PS": str(self.root / "ps"),
            "FAKE_PS_AFTER": str(self.root / "ps_after"),
        }
        env.update(more)
        return subprocess.run(  # noqa: S603
            ["/bin/bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def telegram_texts(self) -> list[str]:
        return [
            c
            for c in self.calls()
            if c.startswith("curl") and "api.telegram" not in c and "text=" in c
        ]


@pytest.fixture
def sb(tmp_path: Path) -> Sb:
    (tmp_path / "home").mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL), ("timeout", FAKE_TIMEOUT)):
        f = bindir / name
        f.write_text(body)
        f.chmod(0o755)
    (tmp_path / "env").write_text(
        f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=-100123\nOTHER=1\n"
    )
    box = Sb(tmp_path)
    box.set_ps(HEALTHY)
    return box


def _no_secret_leak(sb: Sb, proc: subprocess.CompletedProcess[str]) -> None:
    assert "SECRETtoken" not in proc.stdout + proc.stderr
    assert "SECRETtoken" not in "\n".join(sb.calls())  # never in argv
    assert "SECRET" not in proc.stdout + proc.stderr


def test_sandbox_resolves_fakes_first(sb: Sb) -> None:
    proc = subprocess.run(
        ["/bin/sh", "-c", "command -v docker; command -v curl"],
        capture_output=True,
        text=True,
        env={"PATH": f"{sb.root / 'bin'}:/usr/bin:/bin"},
        check=False,
    )
    assert proc.stdout.split() == [str(sb.root / "bin" / "docker"), str(sb.root / "bin" / "curl")]


def test_healthy_stack_is_silent(sb: Sb) -> None:
    proc = sb.run()
    assert proc.returncode == 0
    assert not any(c.startswith("curl") for c in sb.calls())
    assert sb.state.read_text().split() == ["0", "0", "0"]


def test_stopped_service_is_started_without_recreate_and_reported_on_success(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("scanner running healthy", "scanner exited"), after=HEALTHY)
    proc = sb.run()
    assert proc.returncode == 0
    starts = [c for c in sb.calls() if " start " in c]
    assert len(starts) == 1
    assert starts[0].endswith("start scanner")
    docker_calls = [c for c in sb.calls() if c.startswith("docker")]
    assert not any(
        w in c.split() for c in docker_calls for w in ("up", "down", "rm", "build", "create")
    )
    texts = sb.telegram_texts()
    assert len(texts) == 1
    assert "restarted" in texts[0]
    _no_secret_leak(sb, proc)
    assert sb.state.read_text().split() == ["0", "0", "0"]


def test_token_goes_through_stdin_config_not_argv(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("scanner running healthy", "scanner exited"), after=HEALTHY)
    sb.run()
    stdin = (sb.root / "calls.log.curl-stdin").read_text()
    assert f"bot{TOKEN}/sendMessage" in stdin
    assert TOKEN not in "\n".join(sb.calls())


def test_missing_container_is_reported_not_started(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("beat running healthy\n", ""))
    proc = sb.run(WATCHDOG_FAIL_THRESHOLD="1")
    assert not any(" start " in c for c in sb.calls())
    assert "beat: missing" in "\n".join(sb.calls()) + proc.stderr
    assert sb.state.read_text().split()[:2] == ["1", "1"]


def test_unhealthy_scanner_alerts_only_after_threshold(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("scanner running healthy", "scanner running unhealthy"))
    first = sb.run()
    assert not sb.telegram_texts()
    assert sb.state.read_text().split()[:2] == ["1", "0"]
    second = sb.run()
    texts = sb.telegram_texts()
    assert len(texts) == 1
    assert "scanner: unhealthy" in texts[0]
    assert not any(" start " in c for c in sb.calls())  # a hung container is a human decision
    _no_secret_leak(sb, first)
    _no_secret_leak(sb, second)
    sb.run()  # third bad run: within REPEAT_S, no repeat
    assert len(sb.telegram_texts()) == 1


def test_alert_repeats_after_interval_then_recovery_message(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("redis running healthy", "redis running unhealthy"))
    sb.run(WATCHDOG_FAIL_THRESHOLD="1", WATCHDOG_REPEAT_S="0")
    sb.run(WATCHDOG_FAIL_THRESHOLD="1", WATCHDOG_REPEAT_S="0")
    assert len(sb.telegram_texts()) == 2
    sb.set_ps(HEALTHY)
    sb.run()
    texts = sb.telegram_texts()
    assert len(texts) == 3
    assert "healthy again" in texts[-1]
    assert sb.state.read_text().split()[:2] == ["0", "0"]


def test_docker_unreachable_alerts_and_skips_heartbeat(sb: Sb) -> None:
    hb = sb.root / "hb"
    hb.write_text(HB_URL + "\n")
    hb.chmod(0o600)
    proc = sb.run(FAKE_INFO_EXIT="1", WATCHDOG_FAIL_THRESHOLD="1", HEARTBEAT_URL_FILE=str(hb))
    texts = sb.telegram_texts()
    assert len(texts) == 1
    assert "docker daemon unreachable" in texts[0]
    assert "hc-ping" not in (sb.root / "calls.log.curl-stdin").read_text().replace(
        f"bot{TOKEN}", ""
    )
    _no_secret_leak(sb, proc)


def test_failed_send_is_retried_next_run(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("redis running healthy", "redis exited"))
    sb.run(WATCHDOG_FAIL_THRESHOLD="1", FAKE_HTTP="500")
    assert sb.state.read_text().split()[:2] == ["1", "0"]  # not marked alerted
    sb.run(WATCHDOG_FAIL_THRESHOLD="1", FAKE_HTTP="200")
    assert sb.state.read_text().split()[:2] == ["2", "1"]


def test_malformed_telegram_credentials_never_reach_curl(sb: Sb) -> None:
    (sb.root / "env").write_text("TELEGRAM_BOT_TOKEN=bad token with spaces\nTELEGRAM_CHAT_ID=-1\n")
    sb.set_ps(HEALTHY.replace("redis running healthy", "redis running unhealthy"))
    proc = sb.run(WATCHDOG_FAIL_THRESHOLD="1")
    assert proc.returncode == 0
    assert not any(c.startswith("curl") for c in sb.calls())
    assert "bad token" not in proc.stderr


def test_heartbeat_is_pinged_only_when_healthy_and_file_is_private(sb: Sb) -> None:
    hb = sb.root / "hb"
    hb.write_text(HB_URL + "\n")
    hb.chmod(0o644)
    proc = sb.run(HEARTBEAT_URL_FILE=str(hb))
    assert "mode 0600" in proc.stderr
    assert not any(c.startswith("curl") for c in sb.calls())
    hb.chmod(0o600)
    proc = sb.run(HEARTBEAT_URL_FILE=str(hb))
    assert "uuid-SECRET" not in "\n".join(sb.calls()) + proc.stderr + proc.stdout
    assert HB_URL in (sb.root / "calls.log.curl-stdin").read_text()


def test_pause_file_disables_everything(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("scanner running healthy", "scanner exited"))
    (sb.root / "home" / ".nexus-watchdog-pause").write_text("")
    proc = sb.run()
    assert proc.returncode == 0
    assert sb.calls() == []


def test_start_uses_its_own_longer_timeout(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("scanner running healthy", "scanner exited"), after=HEALTHY)
    sb.run()
    args = [c.split()[1] for c in sb.calls() if c.startswith("timeout-arg")]
    assert args == ["20", "60", "240", "20", "60"]  # info, ps, start, info, ps


def test_failed_start_does_not_claim_success(sb: Sb) -> None:
    still_down = HEALTHY.replace("scanner running healthy", "scanner exited")
    sb.set_ps(still_down, after=still_down)
    proc = sb.run(FAKE_START_EXIT="1")
    assert proc.returncode == 0
    assert any(" start " in c for c in sb.calls())
    assert not sb.telegram_texts()  # below the alert threshold, and no "restarted" message
    assert sb.state.read_text().split()[:2] == ["1", "0"]


def test_concurrent_run_is_skipped_by_the_lock(sb: Sb) -> None:
    sb.set_ps(HEALTHY.replace("scanner running healthy", "scanner exited"))
    state_dir = sb.state.parent
    state_dir.mkdir(parents=True, mode=0o700)
    with (state_dir / "lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = sb.run()
    assert proc.returncode == 0
    assert "another run is active" in proc.stderr
    assert sb.calls() == []


def test_single_message_when_recovery_follows_an_alert(sb: Sb) -> None:
    down = HEALTHY.replace("scanner running healthy", "scanner exited")
    sb.set_ps(down, after=down)
    sb.run(WATCHDOG_FAIL_THRESHOLD="1")
    assert len(sb.telegram_texts()) == 1  # ALERT
    sb.set_ps(down, after=HEALTHY)
    (sb.root / "calls.log.started").unlink()  # fake docker: `ps` serves "before" again
    sb.run(WATCHDOG_FAIL_THRESHOLD="1")
    texts = sb.telegram_texts()
    assert len(texts) == 2
    assert "restarted" in texts[-1]
    assert sb.state.read_text().split()[:2] == ["0", "0"]


def test_old_pause_file_sends_one_reminder(sb: Sb) -> None:
    pause = sb.root / "home" / ".nexus-watchdog-pause"
    pause.write_text("")
    old = time.time() - 13 * 3600
    os.utime(pause, (old, old))
    sb.run()
    sb.run()  # second run inside the reminder period: silent
    texts = sb.telegram_texts()
    assert len(texts) == 1
    assert "PAUSED" in texts[0]
    assert not any(c.startswith("docker") for c in sb.calls())


def test_fresh_pause_file_sends_no_reminder(sb: Sb) -> None:
    (sb.root / "home" / ".nexus-watchdog-pause").write_text("")
    sb.run()
    assert sb.calls() == []


def test_state_dir_and_log_are_tightened_and_log_is_capped(sb: Sb) -> None:
    state_dir = sb.state.parent
    state_dir.mkdir(parents=True, mode=0o755)
    state_dir.chmod(0o755)
    log = state_dir / "watchdog.log"
    log.write_text("x" * 2000)
    log.chmod(0o644)
    sb.run(WATCHDOG_LOG_MAX_BYTES="1000")
    assert (state_dir.stat().st_mode & 0o777) == 0o700
    assert not log.exists()  # rotated away (cron's `>>` re-creates it)
    rotated = state_dir / "watchdog.log.1"
    assert rotated.exists()
    assert (rotated.stat().st_mode & 0o777) == 0o600
    log.write_text("small")
    log.chmod(0o644)
    sb.run(WATCHDOG_LOG_MAX_BYTES="1000")
    assert (log.stat().st_mode & 0o777) == 0o600
