# T11 - Test isolation and CI update for the tool scope

- id: T11
- stage: S1-tool
- owner: tester
- complexity: medium (CI and fixture work)
- size: M
- depends_on: T1b
- status: done

## Goal
CI and tests reflect the reduced scope and cannot read a developer's `.env`.

## Context docs
`.github/workflows/`, `tests/conftest.py`, todo item 'Test isolation'

## Scope
1. Autouse fixture / `Settings(_env_file=None)` for all unit tests (todo item from M3)
2. Remove paper jobs; add: `.env.example` consistency check (T6), compose smoke (T8), alert flow E2E with fake Telegram (new -> update -> closed) in unit/integration
3. Integration tests still only against `nexus_test` (hard rule 5)
4. Record the new quality baseline (tests, coverage) for the CLAUDE.md proposal

## Acceptance criteria
- CI green; unit tests pass with a hostile local `.env` present
- New baseline numbers written in the card

## Out of scope
Load tests.

## Files likely touched
tests/, .github/workflows/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).

## Result (2026-10-25)
New baseline: 1059 unit tests, coverage 91.90 % (floor 89 %), ruff 0, mypy 0. Details and the proposed
CLAUDE.md line: `docs/audit/baseline-S1-tool.md`. Global hermetic fixture in `tests/unit/conftest.py`; CI runs
unit tests again with a hostile env/.env and `bash -n scripts/*.sh`. E2E alert flow, `.env.example` and compose
checks already exist as unit tests; compose smoke stays manual (needs fake Telegram).
