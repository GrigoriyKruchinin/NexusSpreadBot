# Delta audit — Track 0 + B14

- Date: 2026-10-23. Auditor: analyzer (read-only on code). Branch `chore/agent-pipeline-adoption`,
  HEAD `4c7fd70`. Baseline: audit commit `0f596e3` (`docs/audit/00-16`, risks R-01..R-13 in `13-risk-register.md`).
- Scope: B1, A2, A2a, A4, B1a, A6, A5a (Track 0) and B14, plus all reviews `docs/audit/*review*.md`.
- Code delta since baseline (`git diff --stat 0f596e3 HEAD`, code/config only): 50 files, +2859 / -44.
  `src/nexus/scanner/service.py`, `engine/*`, `simulation/*`, `migrations/*` are **unchanged**.
- Method: re-ran `make lint`, `make typecheck`, `make test-cov` (unit only, hermetic). Not run on purpose:
  integration tests, backup/restore scripts, psql, docker. `.env` not read.

## 1. Quality ratchet (baseline `05-quality-baseline.md`)

| Metric | Baseline | Now | Delta |
|---|---|---|---|
| Unit tests | 481 passed, 12 deselected | **720 passed**, 16 deselected, 23.2 s | better (+239; +4 integration) |
| Branch coverage (unit) | 89 % (4386 stmts / 444 miss, 862 br / 68 partial) | **90.55 %** (4711 / 416, 962 / 72) | better |
| Coverage floor enforced | none | `fail_under = 89` (`pyproject.toml:110`), "Required test coverage of 89.0% reached" | better |
| ruff format / check | 0 / 0 (120 files) | 0 / 0 (131 files) | same |
| mypy --strict | 0 (126 files) | 0 (137 files) | same |
| CI | none | `.github/workflows/ci.yml`: lint, typecheck, unit, integration (`nexus_test` asserted, :105), secret-scan, dependency-audit (pip-audit, all groups, :130-145), docker-build; first run green (todo.md:19) | better |

Weak spots unchanged in kind: `persistence/repositories.py` 35 % (was 31 %, integration-only),
`container.py` 57 % (46), `workers/tasks.py` 60 % (62, -2 pts: new B14 lines in tasks), `cli.py` 47 % (0),
`interfaces/dex.py` 0 %. New modules: `adapters/key_policy.py` 97 %, `domain/conditional.py` 100 %.
No regression on any ratchet metric. New ratchet floor: **720 tests**, coverage >= 89 % (actual 90.5 %).

## 2. Baseline risks

| ID | Status | Evidence |
|---|---|---|
| R-01 test DB wipe | **Closed** (code) | `tests/db_guard.py:11-19` exact-match `nexus_test`; `tests/integration/conftest.py` calls it twice (pytest.exit before migration + before TRUNCATE), commit 3d5441f; CI asserts DB name (`ci.yml:105`); restore drill writes only to `nexus_test` (`scripts/restore_drill.sh`, guard probes in `security-review-A5a.md`). Residual: process lesson (STATE "Lessons") — agent attempted a live write, blocked by harness. |
| R-02 sweep abort via gather | Unchanged | `scanner/service.py:308` plain `asyncio.gather` (file untouched). Tracked: todo.md:39, B3 todo.md:47. |
| R-03 net profit overstated | Unchanged | engine untouched. todo.md:40. |
| R-04 evaluations growth / timeouts | Unchanged | todo.md:41. |
| R-05 no CI / no floor | **Closed** | f6b5abb, bea6e76; `pyproject.toml:110`; todo.md:19. Branch protection on `main` still being configured by user (unverified). |
| R-06 vulnerable deps | **Reduced → effectively closed, not ticked** | Fixed in f6b5abb: `uv.lock` certifi 2026.10.18→2026.10.23, protobuf 5.29.5→5.29.6 (`pyproject.toml:13`, still hard-pinned `==`, pin not justified in writing); pip-audit in CI incl. dev group, green. A2 card:74-75 records it. **Drift:** todo.md:21 and STATE.md:34 still list R-06 as open. |
| R-07 Telegram token in httpx log | **Closed** | 37de0fa: `src/nexus/log.py:26` URL-credential scrub; `tests/unit/test_log_leaks.py` (117 lines) proves stdlib/httpx loggers do not leak. Known limit: bare non-regex secrets (A4 card:39). |
| R-08 clock drift / `_until_stopped` | Unchanged | todo.md:42, B4 todo.md:48. |
| R-09 backups / bot-down / Redis auth / one DB role | **Reduced** | Backups: A5a (5ccf1b6, adfeee0, 1674089), drill PASSED (`docs/reports/restore-drill.md:3`), daily cron 03:15. Roles `nexus_ro` (SELECT, no password, socket only), `nexus_test_owner` (`scripts/sql/bootstrap_backup_roles.sql`). Still open: heartbeat / missed-backup alert (deferred to VPS, A5d), Redis without auth (no `requirepass` in `docker-compose.local.yml`; A5b), app/migrator role split (A5c), off-host copy of dumps (none; dumps on same WSL disk). |
| R-10 scope drift, unverified parsers | **Reduced** | B1 `CORE_EXCHANGES` (`config/groups.py:121,129`), B1a removed MEXC/BITGET key vars, ADR 0002; A6 refuses keys for venues without a policy. Open: transfer-status parsers (todo.md:35), 1.5.6/1.5.11 verdict (todo.md:34). |
| R-11 LICENSE / ToS / legal | **Reduced** | Legal docs added (`docs/legal/go-gates-checklist.md`, `expansion-venues-review.md`, preliminary review). No `LICENSE` file (todo.md:31, user decision). Gate ToS restricted-location finding is a new legal exposure for gateio (handled as conditional venue, B14). |
| R-12 bus factor / direct-to-main | **Reduced** | Work on a branch, CI gate, gitleaks pre-commit (A2a). Bus factor 1 unchanged. |
| R-13 alert at-most-once | Unchanged | B12 todo.md:49. |

Summary: closed 3 (R-01, R-05, R-07), effectively closed 1 (R-06, bookkeeping open), reduced 4
(R-09, R-10, R-11, R-12), unchanged 5 (R-02, R-03, R-04, R-08, R-13 — all M2 code items, by plan).

## 3. New risks introduced

| ID | Risk | Sev | Conf | Evidence / note |
|---|---|---|---|---|
| D-01 | Scanner restart policy `on-failure:5` (was `unless-stopped`): any repeated non-zero exit (e.g. Postgres not ready, R-02-type crash) stops the scanner for good after 5 tries, and no external alert exists until the VPS heartbeat. During a multi-day soak this can silently lose days of data. | Med | High (policy), Med (likelihood) | `docker-compose.local.yml:163`. Intended for A6 exit 3. Mitigate before soak: distinct handling of exit 3 vs others, or a daily "scanner alive" check / digest gap alarm. |
| D-02 | Backups have no missed-run signal and no off-host copy; cron runs only while WSL is up. | Med | High | `docs/guides/backups.md:37-38`; heartbeat deferred to A5d (user decision). First cron run with `.counts` sidecar not yet verified (STATE "In flight" 1). |
| D-03 | Restore drill evidence predates the `.counts` sidecar; drill now refuses the only verified dump. B15 gate "one verified restore drill" is formally met by the 2026-10-23 drill but not on the current tool version. | Low-Med | High | `restore-drill.md:6`; tech-lead A5a N5. |
| D-04 | `nexus_test` holds a full copy of live data after each drill; CI-only integration tests mitigate local TRUNCATE collisions. | Info | High | S-A5a-7 (carried in A5c card:57). |
| D-05 | Key policy rests on user attestation for kucoin IP and gateio permissions; CIDR threshold /8 is a judgment call. | Low | High | `security-review-A6.md` residual risks; F-4. Before U3. |
| D-06 | Until B15 runs, B14 "excluding conditional venues" totals are filters over a shared inventory (estimates, labelled `≈ ... (оценка)`), not independent portfolios — not valid GO numbers. | Med (for GO) | High | B14 card impl. notes + quant review; B15 card Gates. |
| D-07 | Tracking drift: todo.md:13 "Phase 5 tail" unchecked though STATE says done; todo.md:21 R-06 open though fixed; A5a card status line (`A5a-...md:9`) says "pending round-2 re-review" though accepted; B15 card "propose $15k" vs user decision $10,000 per set (STATE); B15 AC8 floor "≥ 646 tests" stale (now 720). | Low | High | Docs only; fix in the stage-end commit. |

No new secrets exposure found: diffs reviewed by security (A6, A5a, B14 all ACCEPT); gitleaks in CI and pre-commit.
No withdrawal/transfer/order code added; A6 introspection endpoints are GET-only behind the read-only guard
(`ccxt_base.py:212`, `max_attempts=1`).

## 4. Open follow-ups from reviews

| Item | What | Where tracked | Status |
|---|---|---|---|
| A6 F-1 | Verify venues concurrently (isolated gather) | todo.md:29 | open |
| A6 F-2 | `IKeyIntrospection` Protocol instead of `getattr` | todo.md:29 | open |
| A6 F-3 | Guard test: `_ws` / transfer fallback carry no `apiKey` | todo.md:29 | open |
| A6 F-4 | CIDR width threshold (now ≤ /8 = unbound), decide at U3 | todo.md:29 | open, U3 |
| A6 F-5 | `.env.example:65-66` wording vs README (MEXC/Bitget keys refused) | todo.md:29 | open |
| A6 sec F4 (Telegram "key policy refused" event) | optional | not tracked | partially covered by restart change; see D-01 |
| A5a N3 | `ensure_backup_dir` explicit refusal of `/` | **not tracked** | open (not fixed in 1674089) |
| A5a N4 | `[min,max]` count check vs concurrent batched purges (B7) → false MISMATCH | **not tracked** (B7 has no card; migration-plan only) | open |
| A5a N5 / STATE 1 | Re-run drill on first sidecar dump (U4) | STATE.md "In flight" 1 | open, after 2026-10-24 03:15 |
| A5a R2-1, R2-2, N1, N2 | prune bounds, curl `-q`, empty `.counts`, stale verdict | — | **fixed** in 1674089 (`backup_prune.sh:15,24`, `backup.sh:61`) |
| S-A5a-5(c), S-A5a-6 (VPS) | heartbeat URL as secret file; no published PG port | A5d card:43-46 | open |
| S-A5a-6 | default privileges for future roles; TCP-login check | A5c card:51-56 | open |
| S-A5a-7 | `nexus_test` holds live copy | A5c card:57 | accepted, revisit |
| S-A5a-8 | filter "Command was:" if dump ever uses `--inserts` | A5c card:59 | conditional |
| B14 R2-1 | `_episodes` returns bare `EpisodeStats()` on empty window (`repositories.py:724`) → "н/д" instead of 0 | B15 card "Carried over" | open |
| B14 tech-lead 6 / sec N3 | validate conditional names against adapter registry | B14 card (deferred) | open, needed before ~20 venues (B16) |

Recommendation: add N3 to the A5c card and N4 to the migration-plan B7 entry (or todo.md:41 R-04 line).

## 5. Readiness

**B15 (shadow portfolios + migration): READY to implement**, conditions:
1. Code work may start now (ratchet green, no blockers in Track 0 reviews; R2-1 is in the card).
2. Before the migration touches live `nexus` (U4): take a fresh dump with `.counts` sidecar and re-run the
   drill on it (D-03), then user OK. Agents never apply it.
3. Fix card drift first: capital $10,000 per set (not $15k), test floor ≥ 720.

**Soak: NOT READY.** Blocked by B15 running on live (D-06), first verified cron backup with sidecar (D-02/D-03).
Strongly recommended before start: an alive signal for scanner/backups or a daily manual check (D-01, D-02),
and R-02 (sweep isolation) since a single crash now ends in a stopped scanner after 5 restarts.
Keyed soak additionally needs U3 with A6 F-4 decided; R-03 bias stays documented for the quant.
