# T8 - One-command start: make up / scripts/start.sh

- id: T8
- stage: S1-tool
- owner: devops
- complexity: medium (compose/Docker orchestration; must not touch live volumes)
- size: M
- depends_on: T2, T6, T7
- status: todo

## Goal
`git clone && cp .env.example .env && <edit> && make up` brings up Postgres, Redis, migrator, scanner and workers and posts alerts.

## Context docs
`docker-compose.local.yml`, `Makefile`, `scripts/`, D-01/D-01b handoffs

## Scope
1. Single compose file for users (`docker-compose.yml`) with healthchecks; `make up` = build + `nexus check` (T7) + `docker compose up -d`; the migrator creates the schema on an empty DB (`alembic upgrade head`) - no manual `make migrate`, no manual `bootstrap-roles`
2. DB bootstrap: postgres image creates DB/user from `POSTGRES_*`; roles for backup/test (`bootstrap-roles`, A5c) become optional dev tools, not part of `make up`
3. Startup order and restart policies kept from D-01 (exit 3 no loop); `make down` keeps volumes; `make reset-data` WARNING-guarded and documented (user-run, not agent-run)
4. Optional pieces moved out of the default path: backups cron, host watchdog (D-01b), per-venue proxy; documented as 'advanced' in the guide
5. Windows/WSL note: works with Docker Desktop; no bind mounts needed (config baked in image, D-01b)
6. Remove soak-only scripts/guides' references (guides deleted in T12)

## Acceptance criteria
- On a clean machine (or fresh compose project name + new volumes, run by the user) `make up` reaches healthy and a startup message appears in the Telegram chat
- `make up` fails fast with T7 messages when `.env` is not filled
- No command in the flow uses `docker compose config`, `docker inspect`, `exec ... env`
- CI job builds the image and runs the compose smoke with a fake Telegram endpoint (or documented manual check if infeasible)

## Out of scope
VPS hardening (A5d), proxies.

## Files likely touched
Makefile, docker-compose*.yml, scripts/, .github/workflows/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
