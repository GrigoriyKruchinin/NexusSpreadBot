# Delta audit 03 — stage S1-tool (self-hosted spread-alert tool)

- Date: 2026-10-30. Auditor: analyzer (read-only on code). Branch `chore/agent-pipeline-adoption`, HEAD `e1f8e7f`.
- Previous: `delta-02-S0.md` (commit `2881986`), baseline `05-quality-baseline.md`, stage baseline
  `baseline-S1-tool.md` (T11, 2026-10-25). Stage range `f603178~1..e1f8e7f` = 43 commits.
- Inputs: `tech-lead-review-S1-tool.md` (round 3 ACCEPT), `security-review-S1-tool.md` (follow-up ACCEPT; R5b, I1
  backlog), `tester-regression-S1-tool.md` (unit PASS; N-2/N-3 PENDING USER), cards `docs/tasks/tool/`, ADR 0010.
- Method: re-ran `make check` and `make test-cov` (evidence `evidence/delta-S1-tool-make-{check,test-cov}.txt`);
  LOC/file counts via `git ls-tree` + `git show` at three refs; grep checks (ADR 0001, leftovers); `gh run list`.
  Not run on purpose: integration tests, docker / image build, DB, live Telegram. `.env` not read.

## 1. What changed in S1-tool

Authority: ADR 0010 (pivot after UF NO-GO 2026-10-25: analytical alert tool, no paper trading).

| Area | Card | Change | Review status |
|---|---|---|---|
| Paper core removal | T1a, T1b | Paper portfolios, venue-set shadow runs, GO report, HT1 hedged-transfer code, paper digest/watchdog parts (D-08) removed. Leftover grep `paper\|go_report\|hedge\|perp\|portfolio\|soak` over `src/ config/ .env.example` = empty (only ccxt flag `enablePortfolioMarginTrading`). | TL ACCEPT |
| Migrations squash | T2 | 8 revisions -> `8e1f4a7c2b90_initial_schema` + `b7d2c4e6a1f3_alert_edit_in_place`. One-head + `alembic check` no-drift integration test (CI). DBs from before 2026-10-25 need a one-time reset (README wording fixed, TL #4). | TL ACCEPT |
| Alert data model | T3 | Volume, transfer net/fee/time, withdraw/deposit flags, lifetime on the episode. Network time table: crypto-specialist review still pending (card status line). | TL ACCEPT |
| Templates | T4 | NEW / UPDATE / CLOSED, `[alert] language = en\|ru` via `alert_catalog`; system events and digest also catalog-driven (TL #3 fixed). `nexus pin-text` prints the pinned disclaimer. | TL ACCEPT |
| Anti-spam / edit-in-place | T5 | Claim-before-send, atomic hourly budget, refund on failure, stale-SENDING reaper, edit of stored message; close/UPDATE without a stored message is dropped (TL #1 blocking, #2 fixed); `truncate()` keeps HTML valid. | TL ACCEPT |
| `.env.example` | T6 | Commented, consistency test `test_env_example.py`. | done |
| Startup validation | T7 | `nexus check`: bilingual errors, placeholder-token regex (fullmatch), bad key -> public mode for that venue, exit 3 on fatal config, key check retries transient errors 3x. Sentinel-secret tests. | TL + security ACCEPT |
| One-command start | T8 | `make up` / `scripts/start.sh`, migrator on every start, `.env` permission warning; Postgres port opt-in on 127.0.0.1, Redis not published; images digest-pinned. | security ACCEPT (R5b open) |
| Key policy | T9 | Human attestations dropped for third parties; optional `KEY_POLICY_STRICT`; `nexus check` and scanner share one decision function (`adapters/key_policy.py`, public fallback logged `key_policy_public_fallback`). | security ACCEPT |
| README / quickstart | T10 | EN README + RU `docs/guides/quickstart.md`; example alert matches golden template; residual-risk text per venue fixed. User walk-through pending. | TL ACCEPT |
| Tests / CI | T11 | Autouse isolation fixture (empty cwd, no Nexus env, pinned config file); CI `unit` job with hostile env + hostile `.env`; `bash -n` on scripts. | done |
| Config overlay | T5 fix r1 #16, R2-1 | Optional gitignored `config/local.toml`, per-key merge over `config/nexus.toml` (same guard, settings only), Dockerfile `COPY config/nexus.toml config/local.tom[l] ./config/`; repo-toml tests made hermetic. Real build with/without the file not proven (N-2). | TL ACCEPT, tester PENDING USER |
| Legal / license | T13 | Apache-2.0 `LICENSE` + `NOTICE`, `pyproject` `license`; owner-private channel only (public channels breach OKX/KuCoin ToS). | done |
| Guard rails | TL #6 | `.claude/settings.json` (b76f3f4, user OK): `make up/down/doctor`, `start.sh` in ask; `make reset-data` and raw compose variants denied. | closed |

## 2. Metrics

| Metric | 05 baseline | delta-02 (S0) | baseline-S1-tool (T11) | **Now** | vs T11 / vs CLAUDE.md |
|---|---|---|---|---|---|
| Unit tests | 481 | 1001 | 1059 | **1085 passed**, 19 deselected (integration) | better (+26) / better (CLAUDE.md 1028) |
| Branch coverage (total) | 89 % | 91.41 % | 91.90 % | **92.08 %** (5506 stmts / 407 miss; 1182 br / 79 partial) | better / better (CLAUDE.md 91.5) |
| Coverage floor | 89 | 89 | 89 | 89 (reached) | same |
| ruff format / check | 0 / 0 | 0 / 0 (156) | 0 / 0 (160) | **0 / 0** (160 files) | same |
| mypy --strict | 0 | 0 (163) | 0 (162) | **0** (162 files) | same |
| CI | — | 7 jobs green | green | green on last code commit `80af9b8`; later docs-only runs cancelled by newer pushes, last one in progress at audit time | same |

Code size (Python files / lines, `git ls-tree` at each ref):

| Ref | src files | src LOC | tests files | tests LOC | migrations |
|---|---|---|---|---|---|
| `2881986` (delta-02) | 86 | 12 661 | 77 | 11 917 | 7 |
| `f603178~1` (S1-tool start, after HT1) | 110 | 19 527 | 97 | 17 359 | 8 |
| `e1f8e7f` (now) | **84** | **12 025** | **78** | **11 905** | **2** |

Stage diff on src/tests/config/scripts/compose/Makefile/Dockerfile/CI: 181 files, +5 630 / −28 742.
Net vs delta-02: src −2 files, −636 lines (paper core out, alert/startup code in).
`scanner/service.py` 1 073 lines (was 1 169 at delta-02); `except Exception` in `src/`: 32 (was 35).

Weakest modules (unchanged pattern, integration/manual-only paths): `interfaces/dex.py` 0 % (seam, ADR 0006),
`persistence/repositories.py` 41 %, `persistence/db.py` 56 %, `cli.py` 58 % (was 47), `container.py` 62 %,
`workers/tasks.py` 62 %. No regression.

## 3. Architecture / hard-rule checks

- ADR 0001 / rule 1: held. `grep withdraw|create_order|cancel_order|transfer(` in `src/` finds only read-only
  fee/status metadata (`adapters/cex/ccxt_base.py:371-435`), the key-scope rule check (`startup_check/checks.py:180-212`,
  rejects withdraw-enabled keys) and texts. No order/withdraw endpoint.
- ADR 0010: paper/HT removal verified by grep (§1). ADR 0006 DEX seam untouched.
- Rule 4 (secrets): security ACCEPT; sentinel-secret tests for startup messages; tokens never echoed.
- Rule 5: integration guard unchanged (`tests/db_guard.py`, CI asserts `nexus_test`).

## 4. Risks and open items

| ID | Item | Sev | Conf | Owner / action |
|---|---|---|---|---|
| N-2 | Image build with and without `config/local.toml` not proven by a real `docker build` (only text test of the glob). | Med | High | User, guide `docs/guides/s1-tool-e2e-check.md` steps 1-2 |
| N-3 | Live E2E (test bot + private channel: `nexus check`, NEW/UPDATE/CLOSED edit-in-place, ru, pin-text, system event) not run. Alert state machine is unit-tested with fake Telegram only. | Med | High | User, guide steps 3-8. Blocks the final release tag. |
| R5b | `no-new-privileges` missing on `postgres` / `redis` (internal network, no published port). | Low | High | S2 backlog (todo) |
| I1 | `ExchangeDown` sends `str(ExchangeError)[:500]` to Telegram; with keys a ccxt error may embed a signed request URL (no secret). | Low-Med | Med | S2 backlog: class + HTTP status only, or log redaction |
| N-3b | `make pin-text` starts a container, not in the `ask` list (prints text only). | Info | High | none |
| T3-net | Network transfer-time table not reviewed by crypto-specialist (T3 card). Alert "transfer time" may be off. | Low | Med | crypto-specialist, S2 |
| T10-u | README / quickstart not walked through by a user on a clean machine (T8, T10 cards). | Med | Med | User, together with N-3 |
| D-09 | Single-host watchdog: whole-host outage is silent (carried from delta-02). | Low (tool, no money) | High | accepted |

Closed since delta-02: D-08 (paper watchdog gone with paper code), D-06 (no GO numbers), D-10 (squash replaces
`b15a7c3e91d2`), R-02 (closed earlier). Live-stack items D-01/D-03 are moot while the stack is stopped (STATE
2026-10-25); re-check on the next real start.

## 5. Docs vs code drift (for T12 hygiene / orchestrator)

| Item | Where | Fix |
|---|---|---|
| Ratchet line 1028 / 91.5 % | `CLAUDE.md` (user-owned) | 1085 / 92.1 % (§6) |
| "Quality ratchet: 1041 ..."; "Stage S1-tool planned" | `docs/pipeline/STATE.md:6, 54` | update to stage-close state |
| T7 status "scanner-side public fallback deferred" | `docs/tasks/tool/T7-startup-validation.md:9,45` | stale: T9 implemented it (`adapters/key_policy.py:5,406`); set done |
| T9 "security review ACCEPT pending" | `docs/tasks/tool/T9-key-policy-simplification.md:9` | ACCEPT given; set done |
| T13 "LICENSE choice pending user"; todo "LICENSE decision (user)" unchecked | T13 card:9, `todo.md:26` | Apache-2.0 chosen and committed; tick |
| `baseline-S1-tool.md` numbers 1059 / 91.90 % | `docs/audit/baseline-S1-tool.md` | superseded by this file |

## 6. New ratchet baseline

> **1085 unit tests green, branch coverage 92.08 % (floor 89 %), ruff 0, mypy --strict 0. Never get worse.**
> (baseline `docs/audit/delta-03-S1-tool.md`)

`CLAUDE.md` is user-owned: orchestrator proposes the line to the user (T12 handoff). Floor in `pyproject`
stays 89 % (raising it to 91 % is possible, not required).

## 7. Tag proposal (not created)

- Now: `s1-tool-rc1` (or `v0.1.0-rc1`) on `e1f8e7f` or on the stage-close commit — code accepted by tech-lead,
  security and unit regression.
- After N-2 + N-3 pass (user reports on the E2E guide): annotated `v0.1.0` (matches `pyproject` `version = "0.1.0"`)
  on that commit, message "S1-tool: self-hosted spread-alert tool". Tag push and any merge to `main` only with user
  consent (rule 6). Existing tags: `pre-agents-baseline` only.

## 8. Verdict

Better on every quality metric vs T11 baseline and CLAUDE.md; no regression; src is smaller than at delta-02 despite
new features. Stage S1-tool: **code-complete, gates ACCEPT**; release-ready **conditional on N-2 and N-3 (user)**.
