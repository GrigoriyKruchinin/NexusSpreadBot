# Restore drill report (A5a)

Status: PASSED (2026-10-23, 17:18-17:19 UTC). Counts only, no row data.

- Roles bootstrapped once by devops with user approval (U4, 2026-10-23): `nexus_ro`, `nexus_test_owner`, DB `nexus_test`.
- Dump: `nexus-20261023T171853Z.dump`, 549226 bytes, taken as `nexus_ro` (`make backup`).
- Restore: into `nexus_test` as `nexus_test_owner` (`make restore-drill`), duration about 9 s. `nexus` was never written.
- Source counts were read after the dump finished while the scanner keeps writing, so for append-only
  tables source >= restored is expected (the drill script treats this as ok). Static tables match exactly.

| table | restored | source | verdict |
|---|---|---|---|
| alembic_version | 1 | 1 | ok |
| alert_log | 11 | 11 | ok |
| exchange_health | 2192 | 2196 | ok (live growth) |
| exchange_metadata_stats | 12 | 12 | ok |
| market_pairs | 2193 | 2193 | ok |
| opportunity_episodes | 10 | 10 | ok |
| paper_balance_snapshots | 135 | 135 | ok |
| paper_rebalances | 0 | 0 | ok |
| paper_trades | 11 | 11 | ok |
| route_quarantine | 1 | 1 | ok |
| spread_evaluations | 2819 | 2829 | ok (live growth) |
| spread_snapshots | 11042 | 11062 | ok (live growth) |

Role checks (read-only): both roles NOSUPER/NOCREATEDB/NOCREATEROLE/NOREPLICATION; `nexus_ro` has
`default_transaction_read_only=on`, statement_timeout 30min, SELECT on 12/12 public tables, 0 write
privileges, no CREATE on schema; `nexus_test_owner` gets "permission denied for database nexus".
Services scanner, worker-alerts, worker-maintenance, beat, redis, postgres stayed healthy; no DB auth/connection errors in the last 10 min of logs.
