"""Shell-level tests for backup scripts.

Hermetic by construction: every script runs with a minimal explicit environment, HOME and BACKUP_DIR
inside tmp_path, and fake `docker` / `curl` stubs placed FIRST on PATH. The stubs record argv and
never touch a daemon or the network. A stub refuses to run without the sandbox variables, and
`test_sandbox_resolves_fakes_first` fails if the real docker/curl could be picked up.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"

FAKE_DOCKER = """#!/bin/sh
[ -n "$FAKE_LOG" ] || { echo "fake docker used outside the sandbox" >&2; exit 99; }
echo "docker $*" >> "$FAKE_LOG"
cat > /dev/null
case "$*" in
  *rolsuper*) echo "${FAKE_SUPER:-f}" ;;
  *query_to_xml*)
    case "$*" in
      *"-d nexus_test"*) cat "$FAKE_DST" ;;
      *) cat "$FAKE_SRC" ;;
    esac ;;
  *pg_dump*) echo DUMPDATA ;;
esac
exit "${FAKE_DOCKER_EXIT:-0}"
"""
FAKE_CURL = """#!/bin/sh
[ -n "$FAKE_LOG" ] || { echo "fake curl used outside the sandbox" >&2; exit 99; }
echo "curl $*" >> "$FAKE_LOG"
cat >> "$FAKE_LOG.curl-stdin"
exit "${FAKE_CURL_EXIT:-0}"
"""


@dataclass
class Sandbox:
    root: Path
    home: Path
    backups: Path
    log: Path
    fake_bin: Path
    extra: dict[str, str] = field(default_factory=dict)

    def env(self, **more: str) -> dict[str, str]:
        # Minimal explicit env: nothing is inherited from the developer's shell.
        env = {
            "PATH": f"{self.fake_bin}:/usr/bin:/bin",
            "HOME": str(self.home),
            "BACKUP_DIR": str(self.backups),
            "COMPOSE_FILE": str(self.root / "no-such-compose.yml"),
            # Never the real /mnt/c or ~/nexus-backup-status: both live inside the sandbox.
            "BACKUP_COPY_DIR": str(self.root / "copy"),
            "BACKUP_STATUS_DIR": str(self.root / "status"),
            "FAKE_LOG": str(self.log),
            "FAKE_SRC": str(self.root / "src.counts"),
            "FAKE_DST": str(self.root / "dst.counts"),
        }
        env.update(self.extra)
        env.update(more)
        return env

    def run(self, cmd: list[str], **more: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            env=self.env(**more),
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def set_counts(self, src: dict[str, int], dst: dict[str, int]) -> None:
        (self.root / "src.counts").write_text("".join(f"{k}|{v}\n" for k, v in src.items()))
        (self.root / "dst.counts").write_text("".join(f"{k}|{v}\n" for k, v in dst.items()))


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        f = fake_bin / name
        f.write_text(body)
        f.chmod(0o755)
    sandbox = Sandbox(tmp_path, home, tmp_path / "bk", tmp_path / "calls.log", fake_bin)
    sandbox.set_counts({"t1": 5, "t2": 0}, {"t1": 5, "t2": 0})
    return sandbox


def _make_dumps(directory: Path, days: int, end: date, per_day: int = 1) -> list[str]:
    names = []
    for offset in range(days):
        day = end - timedelta(days=offset)
        for k in range(per_day):
            name = f"nexus-{day:%Y%m%d}T0{3 + k}0000Z.dump"
            (directory / name).write_text("x")
            names.append(name)
    return names


def _dump_date(name: str) -> date:
    return date(int(name[6:10]), int(name[10:12]), int(name[12:14]))


# ---------------------------------------------------------------- sandbox guard
def test_sandbox_resolves_fakes_first(sb: Sandbox) -> None:
    path = sb.env()["PATH"]
    assert shutil.which("docker", path=path) == str(sb.fake_bin / "docker")
    assert shutil.which("curl", path=path) == str(sb.fake_bin / "curl")
    env = sb.env()
    for forbidden in (
        "HEARTBEAT_URL",
        "HEARTBEAT_URL_FILE",
        "DOCKER_HOST",
        "TARGET_USER",
        "TARGET_DB",
    ):
        assert forbidden not in env
    assert str(sb.backups).startswith(str(sb.root))


def test_fake_docker_refuses_without_sandbox(sb: Sandbox) -> None:
    result = subprocess.run(  # noqa: S603
        [str(sb.fake_bin / "docker"), "ps"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert result.returncode == 99


# ---------------------------------------------------------------- prune
def test_prune_keeps_7_daily_and_4_weekly(sb: Sandbox) -> None:
    sb.backups.mkdir()
    names = _make_dumps(sb.backups, 60, date(2026, 10, 23))
    (sb.backups / "unrelated.txt").write_text("keep")
    result = sb.run([str(SCRIPTS / "backup_prune.sh"), str(sb.backups)])
    assert result.returncode == 0, result.stderr
    left = sorted(p.name for p in sb.backups.glob("nexus-*.dump"))
    assert set(sorted(names, reverse=True)[:7]) <= set(left)
    assert len(left) == 7 + 4
    assert (sb.backups / "unrelated.txt").exists()
    # dailies: Oct 17-23 (ISO weeks 42+43); weeklies: newest of weeks 41, 40, 39, 38.
    assert _dump_date(left[0]) == date(2026, 9, 20)
    assert {_dump_date(n) for n in left} == {
        *(date(2026, 10, d) for d in range(17, 24)),
        date(2026, 10, 11),
        date(2026, 10, 4),
        date(2026, 9, 27),
        date(2026, 9, 20),
    }


def test_prune_several_dumps_per_day_counts_days(sb: Sandbox) -> None:
    sb.backups.mkdir()
    _make_dumps(sb.backups, 12, date(2026, 10, 23), per_day=3)
    assert sb.run([str(SCRIPTS / "backup_prune.sh"), str(sb.backups)]).returncode == 0
    left = sorted(p.name for p in sb.backups.glob("nexus-*.dump"))
    days = {_dump_date(n) for n in left}
    assert len(left) == len(days)  # one per day/week
    assert all(date(2026, 10, d) in days for d in range(17, 24))
    # the newest dump of the newest day (05:00) survives, not the 03:00 one
    assert "nexus-20261023T050000Z.dump" in left
    assert "nexus-20261023T030000Z.dump" not in left


def test_prune_days_without_dumps_do_not_use_window(sb: Sandbox) -> None:
    sb.backups.mkdir()
    for d in (1, 2, 3, 20, 21, 22, 23):  # a pause between Oct 3 and Oct 20
        (sb.backups / f"nexus-202610{d:02d}T030000Z.dump").write_text("x")
    assert sb.run([str(SCRIPTS / "backup_prune.sh"), str(sb.backups)]).returncode == 0
    assert len(list(sb.backups.glob("nexus-*.dump"))) == 7


def test_prune_small_set_untouched(sb: Sandbox) -> None:
    sb.backups.mkdir()
    _make_dumps(sb.backups, 5, date(2026, 10, 23))
    assert sb.run([str(SCRIPTS / "backup_prune.sh"), str(sb.backups)]).returncode == 0
    assert len(list(sb.backups.glob("nexus-*.dump"))) == 5


@pytest.mark.parametrize("bad", ["abc", "0", "-1", "3x", "1.5", " "])
@pytest.mark.parametrize("which", ["KEEP_DAILY", "KEEP_WEEKLY"])
def test_prune_invalid_retention_deletes_nothing(sb: Sandbox, which: str, bad: str) -> None:
    sb.backups.mkdir()
    _make_dumps(sb.backups, 20, date(2026, 10, 23))
    result = sb.run([str(SCRIPTS / "backup_prune.sh"), str(sb.backups)], **{which: bad})
    assert result.returncode != 0
    assert len(list(sb.backups.glob("nexus-*.dump"))) == 20


@pytest.mark.parametrize("which", ["KEEP_DAILY", "KEEP_WEEKLY"])
def test_prune_oversized_retention_deletes_nothing(sb: Sandbox, which: str) -> None:
    sb.backups.mkdir()
    _make_dumps(sb.backups, 20, date(2026, 10, 23))
    result = sb.run([str(SCRIPTS / "backup_prune.sh"), str(sb.backups)], **{which: "9" * 20})
    assert result.returncode != 0
    assert len(list(sb.backups.glob("nexus-*.dump"))) == 20


def test_prune_newest_survives_even_if_arithmetic_would_delete_it(sb: Sandbox) -> None:
    # Run the script body with `[` failing numerically is not reachable via env any more, so
    # exercise the guard directly: extract remove() and call it on the newest name.
    sb.backups.mkdir()
    names = _make_dumps(sb.backups, 3, date(2026, 10, 23))
    newest = max(names)
    script = (SCRIPTS / "backup_prune.sh").read_text()
    start = script.index("newest=")
    end = script.index("for base in")
    harness = (
        'set -euo pipefail\ndir="$1"\nfiles=("$2")\n'
        + script[start:end]
        + 'remove "$2"\nremove "$3"\n'
    )
    other = min(names)
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", harness, "x", str(sb.backups), newest, other],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (sb.backups / newest).exists()
    assert not (sb.backups / other).exists()


def test_prune_never_deletes_newest(sb: Sandbox) -> None:
    sb.backups.mkdir()
    _make_dumps(sb.backups, 20, date(2026, 10, 23))
    result = sb.run(
        [str(SCRIPTS / "backup_prune.sh"), str(sb.backups)], KEEP_DAILY="1", KEEP_WEEKLY="1"
    )
    assert result.returncode == 0
    left = sorted(p.name for p in sb.backups.glob("nexus-*.dump"))
    assert "nexus-20261023T030000Z.dump" in left
    assert len(left) == 2


def test_prune_ignores_foreign_names_and_removes_sidecars(sb: Sandbox) -> None:
    sb.backups.mkdir()
    _make_dumps(sb.backups, 10, date(2026, 10, 23))
    for n in ("nexus-manual.dump", "nexus-20261013T0300Z.dump", "nexus-20269999T030000Z.dump"):
        (sb.backups / n).write_text("x")
    (sb.backups / "nexus-20261014T030000Z.counts").write_text("t|1|1\n")  # sidecar of a pruned dump
    (sb.backups / "nexus-20261023T030000Z.counts").write_text("t|1|1\n")
    result = sb.run([str(SCRIPTS / "backup_prune.sh"), str(sb.backups)], KEEP_WEEKLY="1")
    assert result.returncode == 0, result.stderr
    assert (sb.backups / "nexus-manual.dump").exists()
    assert (sb.backups / "nexus-20261013T0300Z.dump").exists()
    assert (sb.backups / "nexus-20269999T030000Z.dump").exists()  # unparsable date: kept, warned
    assert "unparsable" in result.stderr
    assert (sb.backups / "nexus-20261023T030000Z.counts").exists()
    assert not (sb.backups / "nexus-20261014T030000Z.counts").exists()


# ---------------------------------------------------------------- backup dir safety
def test_backup_refuses_dir_inside_repo(sb: Sandbox) -> None:
    target = ROOT / "backups-unit-test-never-created"
    result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_DIR=str(target))
    assert result.returncode != 0
    assert "outside the repository" in result.stderr
    assert not target.exists()
    assert sb.calls() == []


def test_backup_refuses_symlink_into_repo(sb: Sandbox) -> None:
    link = sb.root / "link"
    link.symlink_to(ROOT)
    target = link / "backups-unit-test-never-created"
    result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_DIR=str(target))
    assert result.returncode != 0
    assert "outside the repository" in result.stderr
    assert not (ROOT / "backups-unit-test-never-created").exists()


def test_backup_refuses_home_and_parent_of_home(sb: Sandbox) -> None:
    sb.home.chmod(0o755)
    for target in (sb.home, sb.root):
        before = target.stat().st_mode
        result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_DIR=str(target))
        assert result.returncode != 0
        assert "HOME" in result.stderr
        assert target.stat().st_mode == before
    assert sb.calls() == []


def test_backup_refuses_existing_dir_with_wrong_mode(sb: Sandbox) -> None:
    sb.backups.mkdir(mode=0o755)
    sb.backups.chmod(0o755)
    result = sb.run([str(SCRIPTS / "backup.sh")])
    assert result.returncode != 0
    assert "0700" in result.stderr
    assert oct(sb.backups.stat().st_mode & 0o777) == "0o755"
    assert sb.calls() == []


def test_backup_refuses_dotdot(sb: Sandbox) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_DIR=f"{sb.root}/new/../../x")
    assert result.returncode != 0
    assert sb.calls() == []


# ---------------------------------------------------------------- backup happy path + heartbeat
def test_backup_writes_0600_dump_and_counts_sidecar(sb: Sandbox) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")])
    assert result.returncode == 0, result.stderr
    assert oct(sb.backups.stat().st_mode & 0o777) == "0o700"
    dumps = list(sb.backups.glob("nexus-*.dump"))
    counts = list(sb.backups.glob("nexus-*.counts"))
    assert len(dumps) == 1
    assert len(counts) == 1
    assert oct(dumps[0].stat().st_mode & 0o777) == "0o600"
    assert oct(counts[0].stat().st_mode & 0o777) == "0o600"
    assert counts[0].read_text() == "t1|5|5\nt2|0|0\n"
    assert not list(sb.backups.glob("*.partial"))
    calls = sb.calls()
    assert calls
    assert all(c.startswith("docker ") for c in calls)
    assert any("pg_dump -U nexus_ro -d nexus" in c for c in calls)
    assert "heartbeat" in result.stderr
    assert not (sb.log.parent / "calls.log.curl-stdin").exists()


def test_backup_failure_leaves_no_partial(sb: Sandbox) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")], FAKE_DOCKER_EXIT="1")
    assert result.returncode != 0
    assert not list(sb.backups.glob("nexus-*"))
    assert sb.backups.is_dir()


# ---------------------------------------------------------------- off-machine copy + status (S0a)
def _status(directory: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads((directory / "last_backup.json").read_text())
    return data


def test_backup_copies_dump_and_counts_and_writes_status(sb: Sandbox) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")])
    assert result.returncode == 0, result.stderr
    dump = next(sb.backups.glob("nexus-*.dump"))
    copy = sb.root / "copy"
    assert (copy / dump.name).read_bytes() == dump.read_bytes()
    assert (copy / dump.with_suffix(".counts").name).exists()
    assert not list(copy.glob(".*partial"))
    for directory, mode in ((sb.backups, 0o600), (sb.root / "status", 0o644)):
        status = _status(directory)
        assert set(status) == {"finished_at", "ok", "dump", "copied"}
        assert status["ok"] is True
        assert status["copied"] is True
        assert status["dump"] == dump.name
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(status["finished_at"]))
        assert (directory / "last_backup.json").stat().st_mode & 0o777 == mode
        assert not list(directory.glob(".last_backup.*"))


def test_backup_copy_unavailable_warns_and_succeeds(sb: Sandbox) -> None:
    # Parent of the copy dir does not exist -> "drive not mounted".
    result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_COPY_DIR=str(sb.root / "nodrive" / "x"))
    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stderr
    assert not (sb.root / "nodrive").exists()
    status = _status(sb.backups)
    assert status["ok"] is True
    assert status["copied"] is False
    assert len(list(sb.backups.glob("nexus-*.dump"))) == 1


@pytest.mark.parametrize("value", ["", "relative/dir", "/var/../x"])
def test_backup_copy_disabled_or_invalid_value(sb: Sandbox, value: str) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_COPY_DIR=value)
    assert result.returncode == 0, result.stderr
    assert _status(sb.backups)["copied"] is False


def test_backup_copy_dir_equal_to_backup_dir_is_refused(sb: Sandbox) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_COPY_DIR=str(sb.backups))
    assert result.returncode == 0
    assert _status(sb.backups)["copied"] is False


def test_backup_copy_checksum_mismatch_is_not_copied(sb: Sandbox) -> None:
    cp = sb.fake_bin / "cp"
    cp.write_text('#!/bin/sh\n[ "$1" = "--" ] && shift\nprintf corrupted > "$2"\n')
    cp.chmod(0o755)
    result = sb.run([str(SCRIPTS / "backup.sh")])
    assert result.returncode == 0
    assert "checksum mismatch" in result.stderr
    assert not list((sb.root / "copy").glob("nexus-*"))
    assert not list((sb.root / "copy").glob(".*partial"))
    assert _status(sb.backups)["copied"] is False


def test_backup_prunes_the_copy_with_same_retention(sb: Sandbox) -> None:
    copy = sb.root / "copy"
    copy.mkdir()
    for d in range(1, 21):
        (copy / f"nexus-202609{d:02d}T030000Z.dump").write_text("x")
        (copy / f"nexus-202609{d:02d}T030000Z.counts").write_text("t|1|1\n")
    assert sb.run([str(SCRIPTS / "backup.sh")]).returncode == 0
    new = next(sb.backups.glob("nexus-*.dump")).name
    dumps = {p.name for p in copy.glob("nexus-*.dump")}
    assert new in dumps
    assert len(dumps) <= 7 + 4  # 21 files before; same KEEP_DAILY/KEEP_WEEKLY as local
    assert {p.name for p in copy.glob("nexus-*.counts")} == {n[:-5] + ".counts" for n in dumps}
    assert (
        len(list(sb.backups.glob("nexus-*.dump"))) == 1
    )  # the local dir was not touched by copy prune


def test_copy_failure_of_dump_leaves_no_sidecar_less_or_orphan_files(sb: Sandbox) -> None:
    # cp works for the .counts sidecar, fails for the dump: nothing may remain in the copy dir.
    cp = sb.fake_bin / "cp"
    cp.write_text(
        '#!/bin/sh\n[ "$1" = "--" ] && shift\ncase "$1" in *.dump) exit 1;; esac\n'
        '/bin/cp "$1" "$2"\n'
    )
    cp.chmod(0o755)
    result = sb.run([str(SCRIPTS / "backup.sh")])
    assert result.returncode == 0, result.stderr
    copy = sb.root / "copy"
    assert not list(copy.glob("nexus-*"))
    assert not list(copy.glob(".*partial"))
    assert _status(sb.backups)["copied"] is False


def test_copy_never_follows_a_planted_symlink(sb: Sandbox) -> None:
    copy = sb.root / "copy"
    copy.mkdir()
    victim = sb.root / "victim"
    victim.write_text("keep")
    for name in (".nexus-x.dump.partial", ".nexus-x.counts.partial"):
        (copy / name).symlink_to(victim)
    assert sb.run([str(SCRIPTS / "backup.sh")]).returncode == 0
    assert victim.read_text() == "keep"


@pytest.mark.parametrize("where", ["same", "inside"])
def test_status_dir_in_backup_dir_is_refused(sb: Sandbox, where: str) -> None:
    target = sb.backups if where == "same" else sb.backups / "pub"
    result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_STATUS_DIR=str(target))
    assert result.returncode == 0, result.stderr
    assert "BACKUP_STATUS_DIR" in result.stderr
    if where == "same":
        assert (sb.backups / "last_backup.json").stat().st_mode & 0o777 == 0o600  # not widened
    else:
        assert not (sb.backups / "pub" / "last_backup.json").exists()


def test_status_dir_holding_dumps_is_refused(sb: Sandbox) -> None:
    status = sb.root / "status"
    status.mkdir()
    (status / "nexus-20200101T000000Z.dump").write_text("x")
    result = sb.run([str(SCRIPTS / "backup.sh")])
    assert result.returncode == 0
    assert "contains dumps" in result.stderr
    assert not (status / "last_backup.json").exists()


def test_archive_dump_is_never_pruned_and_leaves_status_alone(sb: Sandbox) -> None:
    assert sb.run([str(SCRIPTS / "backup.sh")], BACKUP_ARCHIVE="1").returncode == 0
    archive = list((sb.backups / "archive").glob("nexus-archive-*.dump"))
    assert len(archive) == 1
    assert archive[0].with_suffix(".counts").exists()
    assert not (sb.backups / "last_backup.json").exists()
    assert not (sb.root / "status").exists()
    assert (sb.root / "copy" / archive[0].name).exists()
    # Years of daily dumps later: prune of both dirs keeps the archive.
    _make_dumps(sb.backups, 30, date(2026, 10, 1))
    assert sb.run([str(SCRIPTS / "backup.sh")]).returncode == 0
    assert archive[0].exists()
    assert (sb.root / "copy" / archive[0].name).exists()


def test_backup_failure_writes_status_not_ok(sb: Sandbox) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")], FAKE_DOCKER_EXIT="1")
    assert result.returncode != 0
    status = _status(sb.backups)
    assert status["ok"] is False
    assert status["copied"] is False
    assert status["dump"] == ""
    assert _status(sb.root / "status")["ok"] is False
    assert not (sb.root / "copy").exists()


def test_backup_refused_dir_writes_no_status(sb: Sandbox) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")], BACKUP_DIR=str(ROOT / "bk"))
    assert result.returncode != 0
    assert not (ROOT / "bk").exists()
    assert not (sb.root / "status").exists()


def _hb_file(sb: Sandbox, mode: int, content: str = "https://hc.example/ping/abc-123\n") -> Path:
    f = sb.root / "hb-url"
    f.write_text(content)
    f.chmod(mode)
    return f


def test_heartbeat_sent_from_0600_file_without_leaking_url(sb: Sandbox) -> None:
    f = _hb_file(sb, 0o600)
    result = sb.run([str(SCRIPTS / "backup.sh")], HEARTBEAT_URL_FILE=str(f))
    assert result.returncode == 0, result.stderr
    assert "heartbeat sent" in result.stderr
    assert "hc.example" not in result.stderr + result.stdout
    curl_calls = [c for c in sb.calls() if c.startswith("curl ")]
    assert len(curl_calls) == 1
    assert "hc.example" not in curl_calls[0]  # not in argv
    assert curl_calls[0].split()[1] == "-q"  # first argument: ignore ~/.curlrc
    assert "hc.example/ping/abc-123" in (sb.root / "calls.log.curl-stdin").read_text()


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o660])
def test_heartbeat_refused_for_loose_file_mode(sb: Sandbox, mode: int) -> None:
    f = _hb_file(sb, mode)
    result = sb.run([str(SCRIPTS / "backup.sh")], HEARTBEAT_URL_FILE=str(f))
    assert result.returncode == 0
    assert "mode 0600" in result.stderr
    assert not any(c.startswith("curl ") for c in sb.calls())
    assert "hc.example" not in result.stderr


def test_heartbeat_missing_file_warns(sb: Sandbox) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")], HEARTBEAT_URL_FILE=str(sb.root / "nope"))
    assert result.returncode == 0
    assert "WARNING" in result.stderr
    assert "not a readable file" in result.stderr
    assert not any(c.startswith("curl ") for c in sb.calls())


@pytest.mark.parametrize(
    "url",
    [
        'https://x.example/a"b',
        "https://x.example/a\\b",
        "http://x.example/p",
        "https://x.example/a b",
    ],
)
def test_heartbeat_rejects_unsafe_url(sb: Sandbox, url: str) -> None:
    result = sb.run([str(SCRIPTS / "backup.sh")], HEARTBEAT_URL=url)
    assert result.returncode == 0
    assert "not a plain https URL" in result.stderr
    assert "x.example" not in result.stderr
    assert not any(c.startswith("curl ") for c in sb.calls())


def test_heartbeat_failure_does_not_fail_backup(sb: Sandbox) -> None:
    f = _hb_file(sb, 0o600)
    result = sb.run([str(SCRIPTS / "backup.sh")], HEARTBEAT_URL_FILE=str(f), FAKE_CURL_EXIT="22")
    assert result.returncode == 0
    assert "heartbeat ping failed" in result.stderr
    assert "hc.example" not in result.stderr


# ---------------------------------------------------------------- restore drill
def _good_dump(sb: Sandbox, counts: str = "t1|4|6\nt2|0|0\n") -> Path:
    sb.backups.mkdir(mode=0o700)
    dump = sb.backups / "nexus-20261023T030000Z.dump"
    dump.write_text("x")
    dump.with_suffix(".counts").write_text(counts)
    return dump


@pytest.mark.parametrize("target", ["nexus", "postgres", "nexus_test2", "Nexus_test", ""])
def test_restore_refuses_other_targets(sb: Sandbox, target: str) -> None:
    dump = _good_dump(sb)
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)], TARGET_DB=target)
    assert result.returncode != 0
    assert "refusing" in result.stderr
    assert sb.calls() == []


def test_restore_guard_passes_for_nexus_test(sb: Sandbox) -> None:
    dump = _good_dump(sb)
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)], TARGET_DB="nexus_test")
    assert result.returncode == 0, result.stderr
    assert "drill PASSED" in result.stderr
    assert any("pg_restore -U nexus_test_owner -d nexus_test" in c for c in sb.calls())
    report = sb.backups / "restore-drill-last.txt"
    assert oct(report.stat().st_mode & 0o777) == "0o600"
    assert "t1" in report.read_text()


def test_restore_user_is_pinned(sb: Sandbox) -> None:
    dump = _good_dump(sb)
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)], TARGET_USER="nexus")
    assert result.returncode == 0, result.stderr
    calls = sb.calls()
    assert calls
    assert all("-U nexus " not in c for c in calls)
    assert any("-U nexus_test_owner" in c for c in calls)


def test_restore_aborts_if_role_is_superuser(sb: Sandbox) -> None:
    dump = _good_dump(sb)
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)], FAKE_SUPER="t")
    assert result.returncode != 0
    assert "non-superuser" in result.stderr
    assert not any("pg_restore" in c for c in sb.calls())


@pytest.mark.parametrize("restored", [1, 3, 7, 11062])
def test_restore_count_outside_range_fails(sb: Sandbox, restored: int) -> None:
    dump = _good_dump(sb)  # t1 must be within [4, 6]
    sb.set_counts({}, {"t1": restored, "t2": 0})
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)])
    assert result.returncode != 0
    assert "MISMATCH" in result.stderr
    assert "drill FAILED" in result.stderr


@pytest.mark.parametrize("restored", [4, 5, 6])
def test_restore_count_inside_range_passes(sb: Sandbox, restored: int) -> None:
    dump = _good_dump(sb)
    sb.set_counts({}, {"t1": restored, "t2": 0})
    assert sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)]).returncode == 0


def test_restore_static_table_must_match_exactly(sb: Sandbox) -> None:
    dump = _good_dump(sb, "t1|5|5\nt2|0|0\n")
    sb.set_counts({}, {"t1": 4, "t2": 0})
    assert sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)]).returncode != 0


def test_restore_missing_table_is_failed_verdict(sb: Sandbox) -> None:
    dump = _good_dump(sb)
    sb.set_counts({}, {"t1": 5})
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)])
    assert result.returncode != 0
    assert "MISSING" in result.stderr
    assert "drill FAILED" in result.stderr


def test_restore_without_sidecar_fails(sb: Sandbox) -> None:
    dump = _good_dump(sb)
    dump.with_suffix(".counts").unlink()
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)])
    assert result.returncode != 0
    assert "no counts sidecar" in result.stderr
    assert not any("pg_restore" in c for c in sb.calls())


def test_restore_default_picks_latest_exact_name(sb: Sandbox) -> None:
    _good_dump(sb)
    (sb.backups / "nexus-manual.dump").write_text("x")
    result = sb.run([str(SCRIPTS / "restore_drill.sh")])
    assert result.returncode == 0, result.stderr
    assert "nexus-20261023T030000Z.dump" in result.stderr


# ---------------------------------------------------------------- bootstrap SQL
def test_bootstrap_sql_has_no_secrets_or_destructive_statements() -> None:
    # Text heuristic only (a guard, not proof of idempotency; that was verified by the real run).
    sql = (SCRIPTS / "sql" / "bootstrap_backup_roles.sql").read_text()
    assert "PASSWORD " not in sql.upper().replace("NO PASSWORD", "")
    assert sql.count("WHERE NOT EXISTS") == 3
    assert "TRUNCATE" not in sql.upper()
    assert "DROP " not in sql.upper()


@pytest.mark.parametrize("counts", ["", "table|before|after\n", "\n\n"])
def test_restore_empty_or_header_only_sidecar_fails(sb: Sandbox, counts: str) -> None:
    dump = _good_dump(sb, counts)
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)])
    assert result.returncode != 0
    assert "drill FAILED" in result.stderr
    assert "PASSED" not in result.stderr
    assert not any("pg_restore" in c for c in sb.calls())


def test_restore_ignores_stale_passed_report(sb: Sandbox) -> None:
    dump = _good_dump(sb)
    report = sb.backups / "restore-drill-last.txt"
    report.write_text("t1 5 4 6 ok\n")
    sb.set_counts({}, {"t1": 99, "t2": 0})
    result = sb.run([str(SCRIPTS / "restore_drill.sh"), str(dump)])
    assert result.returncode != 0
    assert "MISMATCH" in report.read_text()
    assert " ok" not in report.read_text().splitlines()[0]
