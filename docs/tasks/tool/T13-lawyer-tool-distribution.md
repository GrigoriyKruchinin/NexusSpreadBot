# T13 - Lawyer: ToS and distribution review for a public alert tool

- id: T13
- stage: S1-tool
- owner: lawyer
- complexity: medium (legal reading, no code)
- size: S
- depends_on: T0
- status: todo

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
- `docs/legal/tool-distribution.md` with sources and verdict per venue; input for T4 (footer), T10, LICENSE

## Out of scope
Legal advice to end users.

## Files likely touched
docs/legal/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
