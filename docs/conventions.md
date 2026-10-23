# Conventions (found in the code, enforced by tooling)

- Python 3.12, uv, `src/nexus/` layout; ruff (line 100, isort) and `mypy --strict`; Google docstrings.
- Money and prices: `decimal.Decimal` only, never `float`; quantize only at presentation.
- Async: no blocking I/O, every network call has a timeout, fan-out with `asyncio.TaskGroup` or
  isolated `gather(return_exceptions=True)`; one exchange failing must not stop the sweep.
- Errors: hierarchy in `nexus/domain/errors.py`; never swallow silently; log with context.
- Logging: `structlog`; never log secrets, tokens, signatures, URLs containing tokens.
- SOLID: new exchange = new adapter + registry entry; narrow interfaces; concrete classes wired only
  in `container.py`.
- Config: pydantic-settings, each container loads only its own subset; `.env.example` in sync.
- Telegram: HTML parse mode, escape dynamic values, templates in `notifications/`.
- Tests: hand-computed expectations for spread math, never mock the math; adapters tested on
  recorded fixtures; integration tests marked `integration`, test DB only.
- Commits: Conventional Commits in English; branches `chore/`, `feat/`, `fix/`; PR before `main`.
