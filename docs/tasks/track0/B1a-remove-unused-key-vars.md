# B1a — Remove MEXC/BITGET key vars from scanner env (G5)

- id: B1a (follow-up to B1; security review S-08, gap G5)
- stage: Track 0 (base)
- owner: backend-lead / devops
- complexity: low (config edit, no logic)
- depends_on: B1 (done)
- status: todo
- Priority: low; must be done before any soak that loads keys.

## Goal
Core-only deployments do not pass or advertise API keys for extension venues (mexc, bitget).

## Context docs
`docs/audit/security-review-architecture.md` (G5), `docs/tasks/m2/B1-core-exchanges-default.md`, ADR 0002.

## Acceptance criteria
1. No `MEXC_*` / `BITGET_*` variables in the scanner service env in `docker-compose.local.yml`.
2. No `MEXC_*` / `BITGET_*` entries in `.env.example`.
3. Extension-run docs (README or `docs/guides/`) state how to add these vars back for extension runs.
4. `docker compose -f docker-compose.local.yml config` still valid (do not start the stack; `.env` not read).
5. `make check` not worse than baseline.

## Out of scope
Removing the bitget/mexc adapters (kept as extension, ADR 0002), other venues' vars.

## Files likely touched
`docker-compose.local.yml`, `.env.example`, one doc file, `todo.md`.
