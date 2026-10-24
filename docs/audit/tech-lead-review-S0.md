# Tech-lead review S0 (pre-soak gates) — round 1

- Scope: S0a `3bb5746` (devops), S0b `110fb91`, `46456e4`, `21897bf` (backend-lead). Card
  `docs/tasks/m3/S0-pre-soak-gates.md`, handoffs `docs/handoffs/S0a-to-review.md`, `S0b-to-review.md`.
- Checks: `make check` green locally (976 unit tests, ruff 0, mypy --strict 0; branch coverage per
  handoff 91 %, floor 89 %). No stack, DB, integration run or `.env` access.

## Verdict: RETURN (1 major, 3 medium, minors optional)

### Verified OK
- Wrapper logic: exit 3 -> 0, other codes propagate; `init: true` (tini is PID 1) forwards SIGTERM to
  `sh`, the trap forwards to the scanner, the `kill -0` loop re-waits after the trap interrupts `wait`;
  the scanner exits 0 on SIGTERM (cli.py), `compose stop` = manual stop, never restarted; no loop on exit 3.
- Copy: temp `.name.partial` in the target dir, sha256 compared before rename, failures -> WARN, dump
  never fails. Prune cannot leave the copy dir: `find -maxdepth 1 -type f`, strict
  `^nexus-[0-9]{8}T[0-9]{6}Z\.(dump|counts)$`, newest never deleted; target guarded (absolute, no `..`,
  not BACKUP_DIR, not in repo, `/mnt/<x>` must be a mountpoint before mkdir).
- Status contract: writer (`write_status_file`) and reader (`check_backup`) agree on
  `{finished_at Z, ok, dump, copied}`; atomic same-dir rename; mirror 0644 in a 0755 dir, mounted `:ro`
  only in worker-maintenance (test asserts no other service gets `/backups`); reader caps 4 KiB, type-
  checks bools, Python >= 3.12 parses `Z`. Deviation (BACKUP_STATUS_DIR instead of mounting the 0700
  BACKUP_DIR) is ACCEPTED: it is the safer design.
- R-02: `gather_isolated` uses `return_exceptions=True`, re-raises non-`Exception` BaseException, outer
  cancellation propagates; inner `except Exception` records via `_as_exchange_error` (counted once, feeds
  hysteresis); route failures now logged. Tests cover all paths.
- Watchdog: per-check de-dup, grace only for fresh-start reasons, recovery once (silent), state saved
  after dispatch, one check's error does not skip the other. Redis db 1 (broker) has AOF; no TTL is right;
  maintenance worker `--concurrency 1` excludes a get/save race. Scanner signal (`exchange_health`
  newest id) is written on every ticker call, success or failure.
- 60 sweeps/hour as a "dark hour" flag is fine (1/6 of nominal 360 at 10 s).

### Points to fix
1. **Major — D-01: scanner may not come back after a Docker daemon / WSL restart.** All other services
   are `unless-stopped`; the scanner is `on-failure`. On a clean daemon shutdown the scanner gets
   SIGTERM and exits 0, so `on-failure` will not restart it when the daemon starts again (Windows
   update reboot during the soak). Fix: `restart: unless-stopped` and on exit 3 the wrapper *parks*
   (log the refusal, then `while :; do sleep 3600 & wait $!; done` with a TERM/INT trap that exits 0).
   The container never exits, so no loop and no signed re-calls; the watchdog reports `scanner_stale`.
   Alternatively prove `on-failure` restarts on this host after `wsl --shutdown` and a clean
   `systemctl restart docker` (record in the guide). Also set the trap before `nexus scanner &` (nit).
   Add an executable test: run the script with `sh` and a fake `nexus` on PATH (exit 3 -> parks/0,
   exit 1 -> 1, TERM forwarded and child exit code returned); the regex test alone proves nothing.
2. **Medium — watchdog is silent when a check keeps erroring.** If Postgres is down (scanner cannot
   write, watchdog query raises) or the status file read raises (PermissionError, stale mount), every
   run returns `error` and only logs. Add a reason `check_error` that alerts once after it persists
   for the check's stale window (e.g. scanner_stale_min), de-duplicated like the others; tests.
3. **Medium — one-shot alerts can expire.** `WatchdogAlert`/`WatchdogRecovered` go through
   `AlertService.send_event`, which drops events older than `TELEGRAM_EVENT_MAX_AGE_S` (300 s). The
   watchdog already marked the incident `firing`, so an alerts-worker outage/backlog > 5 min loses the
   alert for the whole incident. Exempt watchdog events from expiry (they are state-gated, never
   stale-misleading) or give them their own TTL >= several hours; test.
4. **Medium — digest downtime under-reports.** `downtime_min` is measured against the 60 minimum, so a
   45-min outage inside one hour (~90 sweeps) or a 90-min outage split across a boundary shows 0 min,
   while the watchdog alerted. Keep 60 for the gap-hour flag but compute downtime against the expected
   rate (3600 / `ticker_interval_s`, or the set's median full-hour count in the window, whichever is
   lower), skip the last hour if it closed less than the cap-stats flush interval ago (5-min lag), and
   state in the card that the B15 part 2 GO report recomputes from raw `paper_cap_stats.sweeps`. Test a
   partial-hour outage.
5. Minor — a firing incident swallows escalation (`backup_not_copied` -> `backup_failed`/`stale`). The
   user may have accepted "drive unplugged" and miss that backups stopped. Re-alert when severity rises.
6. Minor (doc) — prune in BACKUP_DIR and the copy dir deletes any standard-named dump past retention,
   including the planned final archive dump of the old DB. Guide/STATE: store the archive under another
   name or directory.
7. Minor (doc) — card S0 item 3 still says "mount `$BACKUP_DIR`"; record the accepted deviation.
8. Nit — `gather_isolated` re-raises a job's *own* `CancelledError` even when the sweep is not being
   cancelled (e.g. a library cancelling internally); it would abort the sweep. Acceptable; optionally
   treat it as a failure when `asyncio.current_task().cancelling() == 0`.
9. Nit — if the dump copies but the `.counts` copy fails, a sidecar-less dump stays in the copy dir
   (restore drill refuses it). Copy the sidecar first, or remove the dump copy on sidecar failure.

Round 2 needs 1-4 (+ tests); 5-9 may be fixed or carried to todo with an owner.

## Round 2 (2026-10-24)

- Scope: `2c528c6` (devops, S0a r2), `cb1c1af` (backend-lead, S0b r2); security follow-ups S-3/S-4 from
  `docs/audit/security-review-S0.md`.
- Checks (`make check` + `make test-cov`): **999 passed** (27 integration deselected), branch coverage
  **91.31 %** (floor 89 %), ruff 0 (156 files formatted), mypy --strict 0 (163 files). Equal to baseline
  (999 / 91.3 / 0 / 0), not worse. No stack, DB, integration run or `.env` access.

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 1 | D-01 scanner after daemon/WSL restart | FIXED | `docker-compose.local.yml:107-123` `restart: unless-stopped`, trap set before fork (`:108`), exit 3 parks (`sleep` + TERM/INT trap -> exit 0), a TERM during start is honoured (`stop` flag). Executable tests with fake `nexus` under `/bin/sh`: `tests/unit/test_compose.py` `test_wrapper_*` (exit 1 -> 1, 0 -> 0, exit 3 parks and does not exit by itself, TERM in park -> 0, TERM forwarded, child code after TERM propagated). Guide `docs/guides/backups.md` "Перезапуски сканера" updated. |
| 2 | Watchdog silent on persistent check errors | FIXED | `src/nexus/services/watchdog.py:70-89` probe failure -> `Finding(check, CHECK_ERROR)` through `_apply` (grace = check's stale window, de-dup, recovery); `domain/watchdog.py:25-29` in `GRACE_REASONS`; RU text `notifications/formatting.py:65`. Tests: `test_persistent_check_error_alerts_once_after_the_grace_period`, `test_check_error_recovery_is_announced_once`, `test_short_error_burst_is_forgotten`, `test_unreadable_backup_file_error_alerts_after_grace`. |
| 3 | One-shot watchdog alerts can expire | FIXED | `src/nexus/services/alerts.py:111-115` expiry skipped for `WatchdogAlert`/`WatchdogRecovered`; test `test_watchdog_events_never_expire`. |
| 4 | Digest downtime under-reports | FIXED (doc nit R2-3) | `src/nexus/domain/digest.py:141-184`: gap-hour flag keeps the 60 minimum; downtime vs `min(expected_sweeps_per_hour=360, healthy-hour median)` floored at the minimum, hours < 90 % add their share; newest hour skipped until `FLUSH_LAG_MS` (5 min). Wired via `config/nexus.toml`, `config/groups.py:486`, `container.py:282`, `repositories.py:785-849`. Tests: partial-hour 45 min, split boundary, slow-steady, jitter, flush lag (`tests/unit/domain/test_digest_coverage.py`). "GO report recomputes from raw sweeps" is in the docstring and `docs/handoffs/S0b-to-review.md:60`, not in the card. |
| 5 | Escalation swallowed while firing | FIXED | `domain/watchdog.py:31-41` `SEVERITY`; `services/watchdog.py:113-118` re-alerts once on a higher rank, downgrade silent; test `test_escalation_realerts_once_but_downgrade_does_not`. |
| 6 | Prune may delete the archive dump | FIXED | `scripts/backup.sh:17-29,64-69` `BACKUP_ARCHIVE=1` -> `archive/nexus-archive-<stamp>.dump`, no prune, no status; `make backup-archive`; guide section "Архивный дамп"; test `test_archive_dump_is_never_pruned_and_leaves_status_alone` (local + copy dir). |
| 7 | Card still says "mount `$BACKUP_DIR`" | FIXED | `docs/tasks/m3/S0-pre-soak-gates.md:24` records the accepted deviation. |
| 8 | Job's own `CancelledError` aborts the sweep | FIXED | `src/nexus/scanner/service.py:98-125` `_is_job_failure` (`current.cancelling() == 0` -> failure, logged, `None`); `tests/unit/scanner/test_sweep_isolation.py`. |
| 9 | Sidecar-less dump in copy dir | FIXED | `scripts/_backup_common.sh:129-144` `.counts` copied first, dump last, any failure removes the copied sidecar; test `test_copy_failure_of_dump_leaves_no_sidecar_less_or_orphan_files`. |
| S-3 | Fixed temp name follows a planted symlink | FIXED | `scripts/_backup_common.sh:133` `mktemp` in the copy dir; test `test_copy_never_follows_a_planted_symlink`. |
| S-4 | Status dir guard / `.env` vs shell mismatch | FIXED | `scripts/_backup_common.sh:93-103` refuses status dir == / inside `BACKUP_DIR` or holding `nexus-*.dump` (physical path); compose mounts fixed `${HOME}/nexus-backup-status` (`docker-compose.local.yml:167`), Makefile `up-local` fixed path; guide forbids setting it in `.env`/crontab; tests `test_status_dir_in_backup_dir_is_refused[same,inside]`, `test_status_dir_holding_dumps_is_refused`. |

### Residual notes (non-blocking, no fix round needed)
- R2-1 (nit) Wrapper: a SIGTERM arriving in the tiny window after the `rc -eq 3` test and before the
  park trap is installed is consumed by the first trap; the wrapper then parks and Docker SIGKILLs it
  after `stop_grace_period` (30 s). Only delays a manual stop; no restart, no API calls. Accept.
- R2-2 (info) `check_error` on the backup check inherits the 26 h backup window, so an unreadable mount
  alerts after ~26 h, the same horizon as `backup_stale`. Consistent with round-1 ask; accept.
- R2-3 (doc) Add one line to the S0 card (or the B15 part 2 card): "digest downtime is an estimate; the
  GO report recomputes from raw `paper_cap_stats.sweeps`". Orchestrator can do it in the S0 commit.
- R2-4 (info) `write_status` creates a missing status dir before the guard, so a misconfigured path
  inside BACKUP_DIR is created (0755, empty) and then refused. Harmless (parent is 0700).
- Confirm D-01 on the first real Docker/WSL restart of the soak (security S-8): scanner container comes
  back `Up` without manual action.

## Verdict round 2: ACCEPT

Items 1-4 fixed with executable tests, 5-9 and S-3/S-4 fixed; quality ratchet held (999 tests,
91.31 % branch coverage, ruff 0, mypy 0). Next: tester -> security re-check of S-3/S-4 -> delta audit.
