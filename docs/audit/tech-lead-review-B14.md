# Tech-lead review — B14 conditional venues reporting (commit 5ba4f07)

- Date: 2026-10-23. Reviewer: tech-lead. Round: 1 of max 3.
- Inputs: `docs/tasks/m2/B14-conditional-venues-reporting.md`, `docs/conventions.md`, `docs/architecture/target.md`, diff of 5ba4f07.
- **Verdict: RETURN** (small; points 1-3 blocking, 4-6 non-blocking).

## Checks (run by reviewer)
`make check`: ruff format 0 / ruff check 0, mypy --strict 0 (134 files), **646 passed**, 16 deselected.
Branch coverage (`pytest --cov --cov-branch`): **91 %** (baseline 89 %, >= 625 tests). Ratchet OK.
Integration tests not run (need `nexus_test` + user OK).

## What is good
- Pure helper `domain/conditional.py`, no infra imports; layering per target.md respected.
- Money stays `Decimal`, log money as strings; no float. All dynamic text through `esc`.
- No migration, scanner/thresholds untouched, no secrets in diff. Golden digest strings match the card.

## Review questions
**(1) Fail-fast on custom EXCHANGES_ENABLED.** Fail-fast is right for an *explicitly set*
`CONDITIONAL_VENUES`: a typo (`gate` vs `gateio`) would silently put a conditional venue into the
"excluding" total and inflate the GO number. It is wrong for the *default*: an operator who only
narrows `EXCHANGES_ENABLED` gets a startup crash about a variable they never set.
Recommendation: explicit value -> keep fail-fast; unset/empty (default) -> intersect the default with
`EXCHANGES_ENABLED` and log a `conditional_venues_defaulted` warning (use `model_fields_set`).
**(2) SQL filter.** `~or_(buy.in_(c), sell.in_(c))` is correct for "either leg" exclusion: columns are
NOT NULL (no NULL-in-NOT-IN trap); SQLAlchemy 2.1 renders empty `IN` as an always-false expression,
so with `[]` excl == all. Scope matches the "all" totals (since start, executed only, `moved`).
But this path has **zero tests** (unit or integration) and it is the GO-relevant number.
**(3) Alerts worker without subset check.** Acceptable: compose feeds the same variable to scanner
and alerts worker, so the scanner check guards both; a non-enabled venue in the worker is harmless
(never matches). Residual risk only for non-compose deployments -> point 5.
**(4) Tests after code.** Card AC1 says "written first" — process deviation, noted. Content is mostly
meaningful (helper table, config cases, golden strings, log fields, marker). Weak spots in point 4.

## Points
1. **[blocking] Test the `_paper` excl SQL.** Extend `tests/integration/test_digest.py` with trades and
   rebalances touching 0/1/2 conditional venues (incl. from/to legs and a BLOCKED rebalance) and the
   empty-list case; assert excl == manual sum. Plus a unit test compiling the excl `WHERE` with the
   postgresql dialect (both lists and `()`), so CI covers it without a DB. AC2 currently covers episodes only.
2. **[blocking] Default vs explicit (question 1).** Implement the recommendation above; update the
   `.env.example` comment and the card's Operational note; add config tests for both branches.
3. **[blocking] Misleading defaults/tests.** `PaperStats.*_excl_conditional_usd` default to 0, so any
   future constructor that forgets them reports "без условных +$0.00" silently.
   `test_paper_hedged_excl_equals_all_when_no_conditional_rows` asserts excl == 0 (name says equals all).
   Fix: rename the test to what it checks, or make the excl fields `Decimal | None` rendered as `н/д`.
   Also `assert "<b>x" not in text.replace("<b>", "")` in `test_digest_conditional_names_are_escaped`
   is vacuous (always true); assert on the exact escaped venue line instead.
4. [non-blocking] Semantics for quant-analyst: excl rebalance cost includes transfers between free
   venues that were triggered by conditional-venue trades (conservative), and equity/MTM is not split.
   Record in the card / quant notes so GO readers know.
5. [non-blocking] Log the effective `conditional_venues` once at startup in both scanner and alerts
   worker (one grep confirms both processes agree).
6. [non-blocking] With ~20 venues planned, consider validating conditional names against the adapter
   registry in a later card (not now).

Next: backend-lead fixes 1-3 (round 2), then tester/security for the stage.

## Round 2 (2026-10-23)
- Inputs: fix commit e23024d, integration tests 9c5a4d9 (CI only per user decision, not run locally).
- **Verdict: ACCEPT** (one non-blocking follow-up R2-1 below).

### Checks (run by reviewer)
`make check`: ruff 0, mypy --strict 0 (135 files), **656 passed**, 16 deselected.
Branch coverage **91 %** (baseline 89 %). Ratchet OK (646 -> 656 tests).

### Points
1. **Resolved.** `trade_free_clause` / `rebalance_free_clause` extracted and compiled with the
   postgresql dialect in unit tests (lists and `()`; no bare `IN ()`). Integration file
   `tests/integration/test_digest_conditional.py` covers 0/1/2 venues, buy-only/sell-only legs,
   a BLOCKED rebalance and the empty list (CI).
2. **Resolved.** `model_fields_set` check in `ScannerRoleSettings.load`: default intersected with
   `EXCHANGES_ENABLED` + `conditional_venues_defaulted` warning; explicit list fails fast. Tests cover
   narrowed default, no-warning, `""` as unset, typo + non-enabled explicit, explicit `[]`.
   `.env.example` and card Operational note updated.
3. **Resolved.** Excl fields are `None` until computed, rendered `н/д`; excl P&L labelled
   `≈ ... (оценка)`; test renamed; escape test now asserts the exact line.
4. **Resolved (documented)** in the card Implementation notes + quant review.
5. **Resolved.** `scanner_starting.conditional_venues` and `alerts_worker_starting.conditional_venues`.
6. **Deferred** explicitly to a later card (noted in the card).

### Regression check
- R2-1 [non-blocking]: `DigestRepository._episodes` returns bare `EpisodeStats()` for an empty
  window (`repositories.py:724`), so on a quiet day the digest shows `без условных н/д` and the log
  `total_excl_conditional.episodes` is `None` instead of `0`. Fix: `EpisodeStats(total_excl_conditional=0)`
  + one unit test. Safe direction (no inflated number); may be folded into B15.
- No other constructors of `EpisodeStats`/`PaperStats` in `src/`; no scanner/threshold/migration
  changes; no secrets; money remains `Decimal`.

Next: tester + security for the stage; backend-lead picks up R2-1 in the next card.
