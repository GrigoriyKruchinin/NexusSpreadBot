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
