# Tester regression - S0 pre-soak gates

Scope: commits 3bb5746^..cb1c1af (+ docs). Unit tests only; no integration, no docker, no DB.

## Numbers (baseline 999 / 91.3 % / 0 / 0)
| Check | Before | After (2 tests added) |
|---|---|---|
| unit tests | 999 | 1001 |
| branch coverage | 91.31 % | 91.4 % (watchdog.py 98 -> 100 %) |
| ruff / mypy --strict | 0 / 0 | 0 / 0 |

## Criterion -> test
- S0a-1 restart policy: tests/unit/test_compose.py::test_scanner_restart_policy, test_wrapper_exit_3_parks_until_sigterm_then_exits_0, test_wrapper_exit_3_does_not_exit_by_itself, test_wrapper_exit_codes_propagate, test_wrapper_forwards_sigterm_*
- S0a-2 copy + checksum + prune + WARN when unmounted: tests/unit/scripts/test_backup_scripts.py::test_backup_copies_dump_and_counts_and_writes_status, test_backup_copy_unavailable_warns_and_succeeds, test_backup_copy_checksum_mismatch_is_not_copied, test_backup_prunes_the_copy_with_same_retention, test_backup_copy_never_follows_a_planted_symlink (and other copy hardening tests)
- S0a-3 status JSON (fields, atomic, mirror 0644, no leftovers, failure -> ok=false): test_backup_copies_..._writes_status, test_backup_failure_writes_status_not_ok, test_status_dir_* ; compose mount read-only: test_compose.py::test_maintenance_worker_mounts_backup_status_read_only
- S0a-4 guide (Russian): documentation only, not unit-testable.
- S0b-1 sweep isolation / CancelledError: tests/unit/scanner/test_sweep_isolation.py (7 tests)
- S0b-2 watchdog scanner+backup, dedup, recovery once, Russian/escaped text: tests/unit/domain/test_watchdog.py, tests/unit/services/test_watchdog.py, tests/unit/notifications/test_formatting.py::test_watchdog_*
- S0b-2 beat wiring + task: tests/unit/workers/test_watchdog_wiring.py, **new** tests/unit/workers/test_celery.py::test_liveness_watchdog_task_runs_one_check
- S0b-3 coverage/downtime in digest: tests/unit/domain/test_digest_coverage.py, tests/unit/notifications/test_digest.py, test_formatting.py::test_digest_coverage_*, tests/unit/persistence/test_watchdog_queries.py
- S0b-4 TOML + TOML_ALLOWED: tests/unit/config/test_settings.py, test_watchdog_wiring.py::test_backup_status_path_must_be_absolute
- Acceptance (>= 900 tests, >= 89 %, no secrets, ADR 0001): met; no withdrawal code touched.

## Tests added
1. workers/test_celery.py::test_liveness_watchdog_task_runs_one_check (task body was uncovered).
2. services/test_watchdog.py::test_alert_failure_while_check_is_broken_is_swallowed (Redis down while a check errors: no crash).

## Residual risks
- D-01: the exit-3 park behavior is tested via the wrapper script with fakes; a live `restart` check (key-policy refusal does not loop, other failure restarts) needs the real stack - do at soak start.
- Real wiring of watchdog_scope (container), Celery beat firing, and /backups mount readability by the container uid are not unit-verifiable; integration tests/ live smoke needed (tests/integration/test_watchdog_queries.py exists, NOT run here).
- The Windows copy path (/mnt/c/nexus-backups) and sleep settings are only checked with sandbox dirs.
- tasks.py remains 62 % (pre-existing, other tasks).
- No product bugs found.
