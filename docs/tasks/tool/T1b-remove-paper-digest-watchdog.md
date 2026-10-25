# T1b - Remove paper parts of digest, watchdog (D-08) and maintenance

- id: T1b
- stage: S1-tool
- owner: backend-lead
- complexity: medium (focused on 5-6 modules, existing tests as safety net)
- size: M
- depends_on: T1a
- status: done

## Goal
Digest and watchdog keep working for the scanner only; per-set paper freshness (D-08) and paper retention are gone.

## Context docs
`docs/audit/delta-02-S0.md` (D-08), `docs/audit/tech-lead-review-D08.md`

## Scope
1. `services/digest.py`, `notifications/digest.py`, `domain/digest.py`: drop paper sections; keep scanner summary (decide in T5 whether the periodic digest stays; default: keep, short)
2. `services/watchdog.py`, `domain/watchdog.py`, `interfaces/watchdog.py`: remove `PaperSetActivityRepository` / per-set check; KEEP liveness (scanner heartbeat), exchange health, backup status check only if backups remain (see T10)
3. `services/maintenance.py`: remove paper snapshot thinning; KEEP retention for `evaluations`, `spreads`, `episodes`, `exchange_metadata_stats` and others (list them in the card)
4. Update `tests/integration/test_watchdog_queries.py`, `test_digest*.py`, unit tests

## Acceptance criteria
- No import of paper symbols remains; watchdog still alerts on a stalled scanner (test)
- Maintenance purge still runs for every remaining table (unit + integration on `nexus_test` in CI)
- `make check` green

## Out of scope
Changing alert format (T4-T6).

## Files likely touched
src/nexus/services/, src/nexus/domain/, src/nexus/notifications/digest.py, tests/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
