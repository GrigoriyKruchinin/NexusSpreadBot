# T14 - Stage gates: tech-lead, tester, security, delta audit, close

- id: T14
- stage: S1-tool
- owner: orchestrator
- complexity: medium (process card; reviews are done by critics)
- size: M
- depends_on: T1a-T13
- status: todo

## Goal
Close S1-tool per `close-stage`.

## Context docs
skill `close-stage`, `docs/audit/`

## Scope
1. tech-lead review of the whole diff (max 3 fix rounds); focus: alert state machine (T5), startup validation (T7), removed-code leftovers
2. tester: full regression + manual E2E with a real test bot/channel by the user
3. security review: secret handling in startup messages and logs, Telegram token scope, key permission checks, compose exposure of ports (Postgres/Redis not published), default passwords absent
4. delta audit `docs/audit/delta-03-S1-tool.md`; tag proposal; summary to the user (Russian)

## Acceptance criteria
- tech-lead ACCEPT, security ACCEPT, delta audit committed, STATE/todo current, ratchet baseline updated

## Out of scope
Merge to main (only with user consent).

## Files likely touched
docs/audit/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
