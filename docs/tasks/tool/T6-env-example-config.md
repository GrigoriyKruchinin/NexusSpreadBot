# T6 - Complete commented .env.example and config for third parties

- id: T6
- stage: S1-tool
- owner: devops
- complexity: medium (docs-plus-config but must match compose and settings exactly)
- size: M
- depends_on: T1a
- status: done

## Goal
A stranger can fill `.env.example` without reading code and knows what is required vs optional.

## Context docs
`.env.example`, `config/nexus.toml`, `docker-compose*.yml`, `docs/guides/stage-1-local-setup.md`

## Scope
1. Sections in order: REQUIRED (Telegram bot token, chat/channel id, DB password) / OPTIONAL read-only keys per venue (binance, okx, kucoin, bybit, gateio) each with 'leave empty = public mode' and what it unlocks (transfer fee/withdraw-deposit status) / advanced
2. Every variable: purpose, format example (obviously fake), where to get it (BotFather, `@userinfobot`, channel id steps), 'bot must be admin with Post (and Edit) messages right in a channel'; negative `-100...` ids explained
3. Passwords: generate command (`openssl rand -base64 32`) or auto-generate on first start (T8) if left empty - decide in T8; Redis/Celery URL lines hidden under 'advanced, leave default for docker'
4. A test/script `scripts/check_env_example.py` (or existing check-env-settings) asserts every variable read by Settings appears in `.env.example` and vice versa

## Acceptance criteria
- Check script green in `make check` or CI; no real-looking secrets (gitleaks clean)
- Placeholders (`<your-bot-token>`) are rejected by startup validation with a clear message (T7)

## Out of scope
Startup validation (T7).

## Files likely touched
.env.example, scripts/, Makefile, tests/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
