---
name: check-code-quality
description: Run ruff (format + lint) and mypy --strict on the Nexus Spread Scanner codebase, then do a structural SOLID/style review of changed files against CLAUDE.md. Use after any code change and before commits.
---

# check-code-quality

1. Run the tooling (report actual output; do not assume success):
   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src tests
   ```
   If `pyproject.toml` does not exist yet, say so and stop.

2. Structural review of changed files (`git diff --name-only HEAD` plus untracked files under `src/`):
   - `float` used for prices/quantities/fees/PnL → violation (must be `Decimal`).
   - Concrete adapter imported outside `src/nexus/container.py` or `adapters/` → DIP violation.
   - Orchestrator/engine code branching on exchange name (`if exchange == "bybit"`) → OCP violation.
   - Interfaces mixing market data + trading responsibilities → ISP violation.
   - Network calls without timeout; blocking calls (`requests`, `time.sleep`) in async code.
   - Secrets or API keys logged / formatted into messages.
   - New settings fields missing from `.env.example`.
   - Telegram templates without `html.escape` on dynamic values.
   - Missing docstrings on public classes/functions; non-English comments.

3. Report to the user **in Russian**: tool results (pass/fail with counts), then a list of
   violations as `path:line — issue — suggested fix`. Offer to auto-fix with
   `uv run ruff format . && uv run ruff check --fix .` where applicable.
