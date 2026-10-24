# Conventions (found in the code, enforced by tooling)

- Python 3.12, uv, `src/nexus/` layout; ruff (line 100, isort) and `mypy --strict`; Google docstrings.
- Money and prices: `decimal.Decimal` only, never `float`; quantize only at presentation.
- Async: no blocking I/O, every network call has a timeout, fan-out with `asyncio.TaskGroup` or
  isolated `gather(return_exceptions=True)`; one exchange failing must not stop the sweep.
- Errors: hierarchy in `nexus/domain/errors.py`; never swallow silently; log with context.
- Logging: `structlog`; never log secrets, tokens, signatures, URLs containing tokens.
- SOLID: new exchange = new adapter + registry entry; narrow interfaces; concrete classes wired only
  in `container.py`.
- Config: settings live in committed `config/nexus.toml` (env overrides; startup guard rejects secrets and
  unknown keys); `.env` / `.env.example` hold only secrets and ENV-ONLY variables (A7). Each container loads
  only its own subset.
- Telegram: HTML parse mode, escape dynamic values, templates in `notifications/`.
- Tests: hand-computed expectations for spread math, never mock the math; adapters tested on
  recorded fixtures; integration tests marked `integration`, test DB only.
- Commits: Conventional Commits in English; branches `chore/`, `feat/`, `fix/`; PR before `main`.

## Docs and agent-file hygiene
At each stage end (skill `.claude/skills/repo-hygiene`): stale files under `CLAUDE.md`, `.claude/`, `docs/` are
deleted, the rest updated to match the code and STATE.md. Handoffs of accepted tasks are deleted; ADRs,
reviews/audits backing GO/NO-GO, task cards, tests, CI and migrations are never deleted.
