# B15 — Shadow paper portfolios per venue set

- id: B15
- stage: M2 (analysis tooling; must land BEFORE the multi-day keyed soak)
- owner: backend-lead + quant-analyst (quant: scenario semantics, GO report fields)
- reviewers: tech-lead (diff), quant-analyst (semantics, report), architect (schema/migration)
- complexity: high (paper-simulation state per set, DB migration, concurrency of N portfolios, report math)
- depends_on: B14 (done, returned fixes must be closed), A5a (backups + verified restore drill into `nexus_test`), user OK (U4) before the migration touches the live DB
- status: todo

## Goal
Run N independent paper portfolios ("venue sets") fed by the same evaluation stream, so GO numbers
"with / without Bybit / without gateio ..." are real counterfactual simulations instead of the B14
filter estimate (user decision 2026-10-23; quant review section 5).

## Context docs
`docs/quant/b14-conditional-totals-review.md` (bias B1-B7, section 5), `docs/product/vision.md` (GO after
tax, GO-HOLD), `docs/pipeline/STATE.md` (decisions 2026-10-23), `docs/architecture/target.md`,
`docs/architecture/migration-plan.md` (A5a gate for migrations), `docs/legal/go-gates-checklist.md` (G1.7),
`docs/tasks/m2/B14-conditional-venues-reporting.md`, `src/nexus/simulation/portfolio.py`,
`src/nexus/scanner/paper.py`, `src/nexus/engine/candidates.py`, `src/nexus/config/groups.py`.

## Scope
1. Config: `PAPER_VENUE_SETS` (env). Each set = name + list of venues. Default two sets:
   `all` (= every enabled venue) and `excl_conditional` (= enabled minus `CONDITIONAL_VENUES`).
   Adding a set is one config line, e.g. `excl_gateio=-gateio` (exact syntax decided by backend-lead,
   documented in `.env.example`, `docker-compose.local.yml`). Validation at startup (fail closed, error names
   the set/venue): set names lowercase `[a-z0-9_]`, unique; every venue is in `EXCHANGES_ENABLED`; a set has
   >= 2 venues; `all` always present.
2. Simulation: each set owns its own `PaperPortfolio`: own inventory, own rebalancing (sources restricted to
   the set's venues), own top-N route cap (`SCANNER_MAX_CANDIDATES_PER_SWEEP` applied after restricting
   routes to the set, so crowd-out bias disappears), and the SAME fixed capital budget for every set
   (`PAPER_CAPITAL_USD`, split over the set's venues; replaces seed-per-venue growth). A route is in a set
   only if BOTH legs are in the set.
3. Persistence: add `portfolio_id` (set name) to paper trades, rebalances and equity snapshots.
   One Alembic migration, backfill existing rows with `all`, indexes reviewed by architect. Existing
   B14 digest queries keep working (filter on `all`).
4. Accrual rule (document in config docs, digest footer and the quant report): data for a set exists only
   from the moment the set is added; no backfill, no retroactive history. Report shows per-set `since`.
   Removing a set stops accrual; its rows stay.
5. Reporting: quant GO report generator reads per-set results: net $/month and % of fixed capital, before
   and after tax (tax rate = config input, value agreed with the user), hedged / MTM / total P&L,
   tuning-vs-holdout split, stability across >= 2 periods, top-route and top-coin concentration, cap-binding
   count. Digest keeps B14 lines; labels them "filter"/"estimate" and adds a per-set line once sets exist.
6. Safety: paper only; no orders, no transfers, no keys involved (ADR 0001 unchanged).

## Gates (hard)
- Migration is NOT applied to the live `nexus` DB until: A5a done (backup + one verified restore drill into
  `nexus_test`), and explicit user OK (U4). Agents never run it on live data.
- Migration is tested in CI against `nexus_test` (upgrade, downgrade, backfill row counts); integration
  tests run in CI only (user decision 2026-10-23). Never against `nexus`.
- Must be merged and running before the multi-day keyed soak starts; otherwise the soak yields no valid
  "without" GO numbers and has to be repeated.

## Acceptance criteria
1. Tests first: config parsing/validation (defaults, extra set by one line, unknown venue, duplicate set,
   bad name, single-venue set, case normalization); no secrets involved.
2. Unit: two sets with identical stream but different venues produce different, independent inventories;
   a trade in set A never changes inventory/skip reasons in set B; cap applies per set (fixture where the
   cap binds in `all` but not in `excl_conditional`); capital equal across sets.
3. Unit: rebalancing sources never leave the set; blocked transfer in one set does not block another.
4. Migration: upgrade + downgrade pass on `nexus_test` in CI; all pre-existing rows get `portfolio_id='all'`;
   row counts equal before/after; architect sign-off on schema/indexes.
5. Integration (CI): per-set persistence and per-set report query return the manual sums on a fixture.
6. Report: sample quant report output has all fields of Scope 5 for each set, with after-tax and `since`.
7. Performance: sweep latency with 2 sets and with 4 sets measured on the sample stream; regression
   reported (paper is in-memory; target: no measurable change to sweep p95 beyond noise, else NEEDS_USER).
8. `make check` not worse than baseline (>= 721 tests as of stage-end Track 0 + B14, branch coverage >= 89 %, ruff 0,
   mypy --strict 0). No secrets in diff. Card and `todo.md` updated.

## Out of scope
Applying the migration to the live DB (separate U4 step); real orders/transfers; per-venue alert routing;
changing GO thresholds; DEX; proxying; capital sizing decisions (value comes from config, user/quant).

## Files likely touched
`src/nexus/config/groups.py` (+ root settings), `src/nexus/simulation/portfolio.py`, `src/nexus/scanner/paper.py`,
`src/nexus/engine/candidates.py` (cap per set), `src/nexus/persistence/` (models, repositories),
`migrations/versions/*`, `src/nexus/notifications/digest.py`, quant report module, `.env.example`,
`docker-compose.local.yml`, `tests/unit/...`, `tests/integration/...`, `todo.md`.

## Open points for NEEDS_USER at implementation time
- Fixed capital value and tax rate for the GO report ($10,000 per set, user decision 2026-10-23; tax rate from the user).

## Carried over
- R2-1 from `docs/audit/tech-lead-review-B14.md` (Round 2): `_episodes` returns bare `EpisodeStats()`
  on an empty window, so the digest shows "без условных н/д" on quiet days. Fix:
  `EpisodeStats(total_excl_conditional=0)` plus one test.
