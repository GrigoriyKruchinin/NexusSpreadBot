# Delta audit 02 — B15 part 1, A7, S0 (pre-soak gates)

- Date: 2026-10-24. Auditor: analyzer (read-only on code). Branch `chore/agent-pipeline-adoption`,
  HEAD `1fb8d60` (CI green on it and on `79326fa`, 7 jobs; `gh run list`).
- Previous delta: `delta-track0-B14.md` (commit `e30fdad`, code at `4c7fd70`). Range `e30fdad..HEAD` = 44 commits.
- Scope: B15 part 1 (shadow portfolios per venue set, run registry, coin-slot recycle, cap stats, migration
  `b15a7c3e91d2`), A7 (`config/nexus.toml` vs `.env`), key-leak incident follow-up (deny rules), S0a (restart
  policy, off-machine copy, status file), S0b (R-02 sweep isolation, liveness watchdog, digest coverage), tester
  regression. Reviews read: `tech-lead-review-{B15,A7,S0}.md`, `security-review-{A7,S0}.md`, `tester-regression-S0.md`.
- Code delta (`git diff --stat e30fdad HEAD` on src/tests/config/scripts/compose/Makefile/settings): 71 files,
  +6851 / -328. New modules: `config/{file,provenance,venue_sets}.py`, `domain/watchdog.py`,
  `services/watchdog.py`, `scanner/capstats.py`, `infra/backup_status.py`, `interfaces/watchdog.py`,
  `scripts/_backup_common.sh`. One new migration.
- Method: re-ran `make check`, `make lint`, `make typecheck`, unit `--cov` (evidence `evidence/delta-S0-*.txt`).
  Not run on purpose: integration tests, docker, DB, backup scripts against real dirs. `.env` not read.

## 1. Quality ratchet

| Metric | Baseline (05) | Delta B14 | Now | vs B14 |
|---|---|---|---|---|
| Unit tests | 481 | 720 (16 desel.) | **1001 passed**, 27 deselected (integration), 47 s | better (+281) |
| Branch coverage | 89 % | 90.55 % (4711/416, 962/72) | **91.41 %** (5834 stmts / 471 miss, 1252 br / 80 partial) | better |
| Floor | — | `fail_under = 89` | same, "Required test coverage of 89.0% reached" | same |
| ruff format / check | 0 / 0 | 0 / 0 (131 files) | 0 / 0 (156 files) | same |
| mypy --strict | 0 | 0 (137 files) | 0 (163 files) | same |
| CI | — | 7 jobs green | 7 jobs green on HEAD | same |

Weak spots: `persistence/repositories.py` 36 % (integration-only; new watchdog/coverage/paper-set queries are
covered by `tests/integration/test_{watchdog_queries,paper_portfolios,migration_b15}.py`, run in CI only),
`container.py` 65 % (was 57), `workers/tasks.py` 62 % (60), `cli.py` 47 %, `interfaces/dex.py` 0 %.
New modules all >= 95 % (`services/watchdog.py`, `domain/watchdog.py` 100 %). No regression.
**New ratchet floor: 1001 unit tests, branch >= 89 % (actual 91.4 %).** `CLAUDE.md` "Quality ratchet" still
states 481 / 89 % (baseline text) — recommend orchestrator updates it to 1001 / 91.4 % (user-owned file).

## 2. Architecture drift vs ADRs

- ADR 0001 (no withdrawal/order code): held. `grep withdraw|create_order|cancel_order|transfer(` in `src/` finds
  only read-only fee/status metadata (`adapters/cex/ccxt_base.py:371-426`) and docstrings. No new endpoints.
- ADR 0003 (modular monolith + Celery): held. Watchdog is a Celery beat task in the existing maintenance worker
  (`workers/app.py`, `workers/tasks.py`), use case in `services/`, pure rules in `domain/`, ports in
  `interfaces/watchdog.py` — follows the layering. No new service/container.
- ADR 0005 (clock domains): watchdog uses the injected `Clock` (`services/watchdog.py:62`); digest downtime
  works on stored ms timestamps. No direct `time.time()` added in domain code (spot check).
- ADR 0006 (DEX seam only): untouched (`interfaces/dex.py` unchanged).
- A7 split: compose now passes only secrets + ENV-ONLY (`docker-compose.local.yml:24-55`); settings come from the
  read-only mounted `config/nexus.toml`; Postgres db/user fixed and cross-checked by `tests/unit/test_compose.py`.
- Debt growing: `scanner/service.py` 1169 lines (was 1048 in todo M2 line), 20 `except Exception` in it (35 in
  `src/`). Expected (R-02 isolation added code); the split (C0 + M2 item) stays planned, not blocking the soak.

## 3. Risk statuses (register `13-risk-register.md`, status section updated)

| ID | Status now | Evidence |
|---|---|---|
| R-01 test DB wipe | Closed (unchanged) | `tests/db_guard.py`; CI asserts `nexus_test`. Fresh-stack plan keeps the old volume (no `down -v`). |
| R-02 sweep abort via gather | **Closed (code)** | `110fb91` + r2 `cb1c1af`: `gather_isolated` (`scanner/service.py:96-125`, `return_exceptions=True`, outer cancel propagates, job's own `CancelledError` = failure); 7 tests `tests/unit/scanner/test_sweep_isolation.py`. **Drift:** `todo.md` M2 line "R-02 Isolate exchange failures" still unchecked. B3 (`SweepResult.failed` counter) still open: failures are logged, not counted (`SweepResult`, `service.py:164`). |
| D-01 scanner restart policy | **Closed (config), live check pending** | `docker-compose.local.yml:96-123` `unless-stopped` + wrapper parks on exit 3 (no restart loop, no signed calls); executable wrapper tests in `test_compose.py`. Must be confirmed on the first real Docker/WSL restart (security S-8). |
| D-02 no missed-backup signal / no off-host copy | **Reduced** | Copy to `/mnt/c/nexus-backups` with sha256 check, sidecar-first, mktemp (`scripts/_backup_common.sh`); status file mirrored to `~/nexus-backup-status` and read by the watchdog (alert on missing / `ok=false` / `copied=false` / > 26 h, escalation re-alert). Residual: watchdog runs on the same host — a dead WSL/PC produces silence, not an alert (external heartbeat deferred to A5d/VPS). Copy is on the same physical disk (C:), protects against WSL/volume loss, not disk loss. |
| D-03 drill not re-run on a `.counts` dump | **Open** | Planned in the fresh-stack plan (first nightly dump + drill on the new DB). Note: `~/nexus-backup-status` and `/mnt/c/nexus-backups` do not exist yet (checked with `ls`); `make up-local` creates the first, `backup.sh` the second (`/mnt/c` is a mountpoint). |
| D-06 B14 "excluding" totals are estimates | **Reduced** | B15 part 1 gives independent per-set portfolios (4 sets in TOML). Valid GO numbers only once the soak runs on the new stack + B15 part 2 report. |
| D-07 tracking drift | Partly fixed, new drift below (§5) | B15 card now $10,000 per set. |

## 4. New risks

| ID | Risk | Sev | Conf | Evidence / recommendation |
|---|---|---|---|---|
| D-08 | A paper set that fails to resume is disabled for the run with only a log line (`scanner/paper.py:506` `paper_set_resume_failed_disabled`; all paper off: `service.py:265-269`); persistent `paper_sweep_failed` / `paper_cap_stats_failed` (`service.py:446-453`) are log-only too. The watchdog checks scanner liveness (`exchange_health`), not paper data, so GO data for a set can stop accruing for days unnoticed except via the digest per-set downtime line. | Med (for GO) | Med (digest visibility unverified live) | Before/early in the soak: verify on the first digest that a disabled set shows as downtime; preferably add a watchdog check "per-set `paper_cap_stats` newest hour older than N h" (small S0 follow-up for backend-lead). |
| D-09 | Single-host watchdog: alerts depend on the same Postgres/Redis/alerts worker/WSL; a full stack or PC outage is silent. | Med | High | Accepted residual until A5d. Mitigation now: user treats a missing daily digest as an alarm (write into the soak guide). |
| D-10 | Migration `b15a7c3e91d2` applied only in CI; first real application is the migrator-from-zero on the fresh DB. | Low | High | Low risk on an empty DB; downgrade exists. Check migrator exit 0 and `alembic current` = head at stack start. |
| D-11 | Watchdog state (firing/since) lives in the unauthenticated broker Redis (security S-6). | Low | High | A5b. Not reachable from host. |
| D-12 | Scanner "alive" signal = newest `exchange_health` row, written on every ticker call; a scanner stuck after the ticker phase (evaluation/paper) still looks alive. | Low | Med | Acceptable for the soak; digest per-set coverage (cap stats) is the second signal. |

No secrets exposure in the diffs (security A7/S0 ACCEPT; gitleaks CI green). Key-leak incident 2026-10-23 was a
transcript leak, not repo; keys rotated by the user; deny list widened (`.claude/settings.json`, S-7).

## 5. Docs vs code consistency

| Item | Where | Fix |
|---|---|---|
| S0 card `status: todo` though ticked in todo and accepted (TL r2, security r2) | `docs/tasks/m3/S0-pre-soak-gates.md:9` | set done + review refs; add TL R2-3 line "digest downtime is an estimate, GO report recomputes from raw `paper_cap_stats.sweeps`" (already at card:38-39 — OK) |
| Stale card statuses: A7 "review", A6 "review ... awaiting re-review", B14 "review ... not committed", B1 "uncommitted, awaiting review" | card line 9 each | set done (all accepted, committed) |
| `todo.md` M2 "R-02 Isolate exchange failures" unchecked | `todo.md` M2 | tick (done in S0b) or reword to "B3 counters" remainder |
| `todo.md` M3 soak line still lists "D-01 `on-failure:5` + no alert ... R-02" as gates | `todo.md` M3 | replace with: D-03 drill on new DB, D-01 live restart check, fresh-stack U4 steps |
| `todo.md` M2 "Split `scanner/service.py` (1048 lines)" | `todo.md` M2 | 1169 lines now |
| `CLAUDE.md` quality ratchet 481 / 89 % | `CLAUDE.md` | 1001 / 91.4 % (user-owned file; orchestrator) |
| README has no mention of venue-set shadow portfolios, watchdog, backup targets (`make backup`, `backup-archive`, `restore-drill`, `check-env-settings`); `make test-integration` line says "POSTGRES_* env" without "only `nexus_test`" | `README.md:107-140` | add 3-4 lines; state integration tests run in CI / `nexus_test` only (rule 5) |

## 6. Recommendations before the soak on a fresh stack

1. Execute the fresh-stack plan with U4 at each data step; `make backup-archive` first (archive dir is never
   pruned, `scripts/backup.sh:17-29`); keep the old volume.
2. After `make up-local`: migrator exit 0, all services healthy, `alembic current` = `b15a7c3e91d2` (D-10);
   `~/nexus-backup-status` exists and is 0755.
3. Run `make backup` manually once on the new DB, then `make restore-drill` (D-03), check
   `last_backup.json` has `ok=true, copied=true` and the copy in `C:\nexus-backups` (+ optional `icacls`, S-2).
4. Restart test (D-01, S-8): restart Docker/WSL once early, confirm the scanner returns `Up` with no action and
   the watchdog sends at most one stale alert + one recovery.
5. First digest: confirm all 4 sets show coverage; a set with downtime 100 % = disabled set (D-08). Consider the
   per-set freshness watchdog check before the 24 h checkpoint.
6. Tell the user: no digest by the expected time = outage (D-09).
7. Fix the §5 drift in the stage-end / repo-hygiene commit.

Readiness: **soak on the fresh stack: READY (code side)**, conditional on steps 1-4 (U4) and D-03 passing.
GO numbers additionally need B15 part 2 (report generator) — runs in parallel with the soak.
