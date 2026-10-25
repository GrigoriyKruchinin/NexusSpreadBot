# T0 - ADR 0010: Nexus as a self-hosted spread-alert tool

- id: T0
- stage: S1-tool
- owner: architect
- complexity: low (one short document)
- size: S
- depends_on: none (first)
- status: todo

## Goal
Record the post-NO-GO product decision so later cards and hygiene have one authority.

## Context docs
`docs/reports/go-no-go.md`, `docs/pipeline/STATE.md` (2026-10-25), `docs/decisions/0001*`, `docs/product/vision.md`

## Scope
- ADR `docs/decisions/0010-self-hosted-alert-tool.md`: context, decision (clone, fill `.env`, one command, alerts to own Telegram chat/channel, optional read-only keys, PostgreSQL storage), alternatives (hosted bot, portfolio packaging), consequences
- States what is dropped: paper portfolios, GO report, hedged transfer, trading; ADR 0001 stays in force
- Marks superseded: parts of `vision.md`, `migration-plan.md` that assume GO; ADR 0007 iteration loop (cancelled)

## Acceptance criteria
- ADR exists, status accepted after user OK, linked from `todo.md` S1-tool header
- Lists each superseded doc by path (input for T12 hygiene)

## Out of scope
Rewriting vision.md (T12 does a minimal banner only).

## Files likely touched
docs/decisions/, docs/product/vision.md (banner)

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
