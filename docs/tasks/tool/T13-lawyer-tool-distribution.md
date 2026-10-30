# T13 - Lawyer: ToS and distribution review for a public alert tool

- id: T13
- stage: S1-tool
- owner: lawyer
- complexity: medium (legal reading, no code)
- size: S
- depends_on: T0
- status: done (2026-10-25; Apache-2.0 chosen by user and committed, fe5737f)

## Goal
Know whether publishing the tool and posting exchange-derived prices to a (possibly public) Telegram channel violates exchange ToS or needs disclaimers; also LICENSE choice input.

## Context docs
`docs/legal/`, exchange API terms for binance, okx, kucoin, bybit, gateio

## Scope
- Market-data redistribution clauses for public API data in a public channel vs private chat
- Wording for README/pinned disclaimer (not financial advice, no affiliation, use at own risk)
- Recommendation on LICENSE (MIT / Apache-2.0 / source-available), as input to the user decision
- Third-party keys: nothing leaves the user's machine; statement for README

## Acceptance criteria
- [x] `docs/legal/tool-distribution.md` with sources and verdict per venue; input for T4 (footer), T10, LICENSE

## Result (2026-10-25)
- Output: `docs/legal/tool-distribution.md` (verdict table s. 1, inputs for T4/T9/T10 s. 2, texts s. 3, LICENSE s. 4,
  Russian summary at the end).
- Verdict: publishing the code OK; private channel OK on all five; public channel breaches OKX (API Agreement s. 9.4)
  and KuCoin (Art. 89), high risk Binance, grey Bybit/Gate; any monetisation breaches all five.
- LICENSE recommendation: Apache-2.0 (alternatives MIT, AGPL-3.0, source-available) -> user decision (todo item).
- Follow-ups: T9/security must confirm the "keys stay with you" statement before T10 publishes it; T4 ships the pinned
  text (s. 3.2), no public-broadcast/ads features; Bybit API PDF and Binance live ToS need a human re-read before any
  shared/public channel.

## Out of scope
Legal advice to end users.

## Files likely touched
docs/legal/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
(Docs-only task: no code, no tests.)
