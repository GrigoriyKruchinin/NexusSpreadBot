"""Shell-level tests for backup scripts (no Docker, no DB)."""

from __future__ import annotations

import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"


def _run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, env=full_env, check=False
    )


def _make_dumps(directory: Path, days: int, end: date) -> list[str]:
    names = []
    for offset in range(days):
        day = end - timedelta(days=offset)
        name = f"nexus-{day:%Y%m%d}T030000Z.dump"
        (directory / name).write_text("x")
        names.append(name)
    return names


def test_prune_keeps_7_daily_and_4_weekly(tmp_path: Path) -> None:
    names = _make_dumps(tmp_path, 60, date(2026, 10, 23))
    (tmp_path / "unrelated.txt").write_text("keep")
    result = _run([str(SCRIPTS / "backup_prune.sh"), str(tmp_path)])
    assert result.returncode == 0, result.stderr
    left = sorted(p.name for p in tmp_path.glob("nexus-*.dump"))
    daily = sorted(names, reverse=True)[:7]
    assert set(daily) <= set(left)
    assert len(left) == 7 + 4
    assert (tmp_path / "unrelated.txt").exists()
    # the weekly keepers are the newest file of four distinct ISO weeks older than the dailies
    weeks = {
        date.fromisoformat(n[6:14][:4] + "-" + n[10:12] + "-" + n[12:14]).isocalendar()[:2]
        for n in left
        if n not in daily
    }
    assert len(weeks) == 4


def test_prune_small_set_untouched(tmp_path: Path) -> None:
    _make_dumps(tmp_path, 5, date(2026, 10, 23))
    assert _run([str(SCRIPTS / "backup_prune.sh"), str(tmp_path)]).returncode == 0
    assert len(list(tmp_path.glob("nexus-*.dump"))) == 5


@pytest.mark.parametrize("target", ["nexus", "postgres", "nexus_test2", "Nexus_test", ""])
def test_restore_refuses_other_targets(target: str, tmp_path: Path) -> None:
    dump = tmp_path / "nexus-20261023T030000Z.dump"
    dump.write_text("x")
    # A fake docker on PATH proves nothing reaches Docker when the guard trips.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "docker-called"
    docker = fake_bin / "docker"
    docker.write_text(f"#!/bin/sh\ntouch {marker}\n")
    docker.chmod(0o755)
    result = _run(
        [str(SCRIPTS / "restore_drill.sh"), str(dump)],
        env={"TARGET_DB": target, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "refusing" in result.stderr
    assert not marker.exists()


def test_backup_refuses_dir_inside_repo() -> None:
    result = _run([str(SCRIPTS / "backup.sh")], env={"BACKUP_DIR": str(ROOT / "backups")})
    assert result.returncode != 0
    assert "outside the repository" in result.stderr
    assert not (ROOT / "backups" / "x").exists()
    (ROOT / "backups").rmdir()


def test_backup_dir_created_0700(tmp_path: Path) -> None:
    target = tmp_path / "b"
    # no docker available in PATH -> script fails after dir creation; we only check the mode
    _run([str(SCRIPTS / "backup.sh")], env={"BACKUP_DIR": str(target), "PATH": "/usr/bin:/bin"})
    assert target.is_dir()
    assert oct(target.stat().st_mode & 0o777) == "0o700"


def test_bootstrap_sql_is_idempotent_and_has_no_secrets() -> None:
    sql = (SCRIPTS / "sql" / "bootstrap_backup_roles.sql").read_text()
    assert "PASSWORD " not in sql.upper().replace("NO PASSWORD", "")
    assert sql.count("WHERE NOT EXISTS") == 3
    assert "TRUNCATE" not in sql.upper()
    assert "DROP " not in sql.upper()
