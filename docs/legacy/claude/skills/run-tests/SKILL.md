---
name: run-tests
description: Run the Nexus Spread Scanner test suite (unit by default; pass "integration" or "all" as argument) with coverage, and summarize failures with root-cause hints. Use after code changes.
---

# run-tests

Argument: `unit` (default) | `integration` | `all` | a pytest node id / path.

1. Choose the command:
   - `unit`: `uv run pytest -q -m "not integration" --cov=src/nexus --cov-report=term-missing`
   - `integration`: ensure local stack is healthy first
     (`docker compose -f docker-compose.local.yml ps`), then
     `uv run pytest -q -m integration`
   - `all`: `uv run pytest -q --cov=src/nexus --cov-report=term-missing`
   - path / node id: `uv run pytest -q <arg>`

   If `pyproject.toml` or `tests/` does not exist yet, say so and stop.

2. For each failure: show the test id, the assertion/exception, and the most likely root cause
   (read the relevant source). Do not "fix" a failing money-math test by changing the expected
   value unless the hand calculation in the test is demonstrably wrong — explain the arithmetic.

3. Report to the user **in Russian**: passed/failed/skipped counts, coverage for
   `engine/` and `execution/` (target ≥ 90 %), and the failure analysis.
