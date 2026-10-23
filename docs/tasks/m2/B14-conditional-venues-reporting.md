# B14 — Conditional venues: totals with and without them in every aggregate

- id: B14
- stage: M2 (analysis tooling; needed before the multi-day keyed soak and the GO/NO-GO numbers)
- owner: backend-lead (+ observability-engineer for the message/log format)
- reviewers: tech-lead (diff), quant-analyst (totals semantics, later quant reports)
- complexity: medium (cross-cutting read-side change; config validation across groups; no scanner/DB logic change)
- depends_on: B1 (done)
- status: todo

## Goal
Every aggregate shows which venues are "conditional" (data collected, but possibly not tradable for
the user now) and two combined totals, ALL venues and EXCLUDING all conditional venues, so GO is
judged with and without Bybit/gateio (user decisions 2026-10-23, vision GO-HOLD, checklist G1.7).

## Context docs
`docs/product/vision.md` (GO-HOLD, Bybit/gateio rule), `docs/pipeline/STATE.md` (user request (a)),
`docs/architecture/target.md`, `docs/legal/go-gates-checklist.md` (G1.7), `src/nexus/config/groups.py`
(`CORE_EXCHANGES`, `ExchangesSettings`), `src/nexus/domain/digest.py` (`EpisodeStats`, `PaperStats`),
`src/nexus/notifications/digest.py`, `src/nexus/notifications/formatting.py`,
`src/nexus/services/digest.py`, `src/nexus/scanner/paper.py`, `src/nexus/simulation/portfolio.py`.

## Scope
1. Config: `CONDITIONAL_VENUES` (env list, default `["bybit","gateio"]`), normalized lowercase,
   no duplicates, name regex as for exchanges. Validated as a subset of `EXCHANGES_ENABLED`
   (cross-group check at the root settings level; unknown venue = startup error naming the venue).
   Empty list allowed (then "excluding" equals "all"; the line is shown as "none").
2. Domain: one pure helper `touches_conditional(buy, sell, conditional) -> bool` and a split of
   aggregates into `all` and `excl_conditional` (a route is excluded if EITHER leg is a conditional
   venue). Totals are combined, no per-venue breakdown.
3. Apply to every aggregate: periodic Telegram digest (episodes, paper P&L), structured logs of
   periodic summaries, analytics/paper P&L summaries; later quant reports reuse the same helper.
4. Individual alerts for a route touching a conditional venue get a marker (see format).
5. Raw data collection, persistence schema, thresholds and scanner logic unchanged.
   Paper-portfolio note: in the "excluding" total, P&L is recomputed from trades/transfers not
   touching conditional venues; equity/mark-to-market on conditional-venue inventory is excluded.
   If that cannot be derived from stored rows without a migration, backend-lead stops and returns
   a NEEDS_USER (do not add a migration inside this card).

## Message format (Telegram, Russian, all values via `esc`; sample)
Digest block, added after the header:
```
⚠️ Условные биржи (данные собираются, торговать пока нельзя): Bybit, Gate.io
━━━━━━━━━━━━━━━━━━━━
Эпизоды:   все 24 | без условных 6
Бумажный P&L (hedged): все +$41.20 | без условных +$9.75
```
When the list is empty: `Условные биржи: нет` and only the "все" values.
Individual alert: title gets a suffix, body one line:
```
🔔 LUNC: Binance → Bybit  ⚠️ условная биржа (Bybit)
```
Logs (JSON): fields `conditional_venues=["bybit","gateio"]`, `total_all`, `total_excl_conditional`.

## Acceptance criteria
1. Tests (written first): `touches_conditional` for buy-only, sell-only, both, neither, empty list.
2. Tests: aggregation yields both totals on a fixture with routes touching 0, 1 and 2 conditional
   venues; excl total equals manual sum of untouched routes; all total equals sum of everything.
3. Config tests: default is `["bybit","gateio"]`; env override; non-subset of enabled -> error;
   duplicates/invalid name -> error; empty list ok; uppercase normalized.
4. Format tests: digest sample above reproduced (golden string) incl. empty-list case; alert marker
   present only for routes touching a conditional venue; HTML-escaped; message < `TELEGRAM_MAX_LENGTH`.
5. Log test: periodic summary record contains the three fields; no secret-like values
   (existing scrub tests still green).
6. `.env.example` and `docker-compose.local.yml` document `CONDITIONAL_VENUES` (empty value falls
   back to default, as for B1).
7. `make check` not worse than baseline: >= 625 tests, branch coverage >= 89 %, ruff 0, mypy --strict 0.
8. No secrets in code, messages, logs, diff.

## Out of scope
Per-venue breakdown; changing which venues are collected; changing GO thresholds; quant report
generator itself (it must call the helper once it exists); DB migrations; exchange key handling.

## Files likely touched
`src/nexus/config/groups.py`, `src/nexus/config/__init__.py` (+ root settings), `src/nexus/domain/digest.py`,
`src/nexus/notifications/digest.py`, `src/nexus/notifications/formatting.py`, `src/nexus/services/digest.py`,
`src/nexus/scanner/paper.py` / `simulation/portfolio.py` (read-side only), `.env.example`,
`docker-compose.local.yml`, `tests/unit/...`, `todo.md`.
