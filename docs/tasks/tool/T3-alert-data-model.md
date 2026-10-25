# T3 - Alert data model: executable volume, transfer, lifetime inputs

- id: T3
- stage: S1-tool
- owner: backend-lead
- complexity: high (touches engine/domain contracts used by alerts and persistence; money math)
- size: L
- depends_on: T1a
- status: todo

## Goal
Make every field of the approved alert available as typed data on the evaluation/alert payload, with honest 'unknown' states.

## Context docs
`src/nexus/engine/{estimator,depth,transfer}.py`, `domain/models.py`, `domain/events.py` (`AlertContext`), `docs/quant/` cost model notes

## Scope
1. Executable volume: from orderbook depth, the base amount and quote notional fillable on both sides at the net-positive limit (already partly `cost_quote`/`base_bought`; define 'max volume while net spread > 0' vs 'volume sized by scanner' and expose both if they differ)
2. Transfer block: network, fee (coin and USD), approximate time. Time comes from a static per-network table (crypto-specialist, T3a-note) because exchanges do not publish it via the status API; mark as 'approx'
3. Withdraw (source) / deposit (destination) flags as `open | closed | unknown` per exchange (keyless venues -> `unknown`, never fake 'open')
4. Lifetime: episode `opened_at`, `last_seen_at`, `closed_at` available to the alert layer (episodes already exist; add accessors)
5. Add the new fields to the alert task payload with a payload version `v` (B12 item) and backward-compatible decoding of in-flight rows

## Acceptance criteria
- Unit tests for each field including unknown/unverified branches and Decimal rounding
- Network time table in `config/` or a module with source comments; crypto-specialist reviews values
- Public-mode venue yields transfer 'unknown' and the alert still passes the profit gate only per existing rules (R-03: no profit when transfer UNKNOWN stays as is)

## Out of scope
Rendering (T4); delivery behaviour (T5).

## Files likely touched
src/nexus/engine/, src/nexus/domain/, src/nexus/services/alerts.py, tests/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
