# S0b -> tech-lead / security review

Card: `docs/tasks/m3/S0-pre-soak-gates.md` (S0b). Not ticked in todo.md (orchestrator does it).

## What changed
1. **R-02 sweep isolation** (`src/nexus/scanner/service.py`): new `gather_isolated()` used for the
   ticker fetch and the metadata refresh. An unexpected `Exception` from one venue is logged, counted
   as a failed exchange call (feeds the existing down/recovered hysteresis) and yields `None`;
   `BaseException` (`CancelledError`) is re-raised. Failed route evaluations are now logged
   (`route_evaluation_failed`) instead of silently dropped. Tests: `tests/unit/scanner/test_sweep_isolation.py`.
2. **Liveness watchdog**: beat task `nexus.maintenance.watchdog` (maintenance queue, every
   `WATCHDOG_INTERVAL_S`). Logic: `domain/watchdog.py` (pure checks), `services/watchdog.py`
   (de-dup state machine), `infra/redis_store.py::RedisWatchdogState`, `infra/backup_status.py`,
   `persistence/repositories.py::ScannerActivityRepository`, wiring in `container.watchdog_scope`.
   - Scanner signal: newest `exchange_health` row (`ORDER BY id DESC LIMIT 1`, O(1)); the scanner writes
     rows on every sweep even when venues fail. Older than `scanner_stale_min` -> alert.
   - Backup signal: `WATCHDOG_BACKUP_STATUS_PATH` (default `/backups/last_backup.json`, devops contract).
     failed / not copied / older than `backup_max_age_h` (26) -> immediate alert; missing or unreadable
     file or an empty `exchange_health` -> alert only after the grace period (scanner_stale_min resp.
     backup_max_age_h) so a fresh stack does not alarm before the first sweep / first backup.
   - One alert per incident, one recovery message (silent). Incident state: Redis key
     `nexus:watchdog:<check>` in the **broker DB** (`CELERY_BROKER_URL`, db 1; the maintenance worker has
     no `REDIS_URL`). State is saved only after the event was queued; a failed dispatch retries next run.
   - Alerts travel as new system events `watchdog_alert` / `watchdog_recovered` (codes + minutes only,
     Russian text rendered in the alerts worker; no secrets, no paths).
3. **Gap accounting**: digest block "Непрерывность работы сканера" per set from the existing
   `paper_cap_stats.sweeps`; **no schema change, migration b15a7c3e91d2 untouched**. Only complete hours
   after the set's first record are judged; an hour with fewer than `coverage_min_sweeps_per_hour` (60)
   sweeps is a gap; downtime minutes = missing share of that minimum.
4. Settings `[watchdog]` in `config/nexus.toml` + `TOML_ALLOWED` (6 keys); `.env.example` unchanged.

## For devops / soak
- Maintenance worker needs `/backups` mounted read-only (S0a) and `CELERY_BROKER_URL` (already set).
- The alerts worker must run, otherwise watchdog events (max age `TELEGRAM_EVENT_MAX_AGE_S` = 300 s) expire.
- Watchdog is not part of the daily digest cron; both use Telegram via the alerts worker.

## Pitfalls / risks
- `coverage_min_sweeps_per_hour=60` is 1/6 of nominal (360 at 10 s): it detects outages, not slow sweeps.
  Raise it if sweeps are known to be fast. Counters flush every 5 min (<= 5 min lag at hour edges).
- `paper_cap_stats` rows exist only with paper trading enabled (soak: yes).
- If Redis (broker) is down no beat runs at all; a dead maintenance worker also means no alerts
  (external heartbeat still deferred to the VPS stage).
- Integration tests added (`tests/integration/test_watchdog_queries.py`) run only in CI.

## Checks
`make check`: 976 unit tests, branch coverage 91 % (baseline 89 %), ruff 0, mypy --strict 0.
