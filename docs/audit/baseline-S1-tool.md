# Quality baseline after stage S1-tool (T11)

Measured 2026-10-25 on `chore/agent-pipeline-adoption` (paper/HT code removed, migrations squashed,
`nexus check` and key-policy changes in). Supersedes the numbers in `05-quality-baseline.md` and `delta-02-S0.md`.

| Metric | Value |
|---|---|
| Unit tests | **1059** passed, 0 failed, 19 deselected (integration; run in CI only) |
| Coverage (unit, branch) | **91.90 %** total (5464 stmts, 415 missed; 1168 branches, 78 partial; branch-only 89.55 %) |
| Coverage floor in pyproject | `fail_under = 89` (unchanged) |
| ruff format --check / ruff check | 0 issues (160 files) / 0 errors |
| mypy --strict | 0 errors (162 files) |

## Test isolation (T11)
- `tests/unit/conftest.py` autouse fixture: runs every unit test in an empty tmp cwd (no `.env`), removes all
  Nexus variable prefixes from the environment, pins `NEXUS_CONFIG_FILE` to an empty file.
- Verified: `make check` passes with `KEY_POLICY_STRICT=true KEY_POLICY_IP_BINDING_WAIVED=true
  TELEGRAM_CHAT_ID=999 POSTGRES_DB=nexus` exported. Module-level `KeyPolicySettings()` in
  `startup_check/test_checks.py` was read at import and is now explicit.
- CI `unit` job repeats `make test` with hostile variables and a hostile `.env`.
- Integration tests: unchanged guard (`tests/db_guard.py`, CI asserts `POSTGRES_DB=nexus_test`).
- Already covered by unit tests: `.env.example` consistency (`test_env_example.py`), compose shape
  (`test_compose.py`), alert new -> update -> closed flow with fake Telegram (`test_alert_edit_in_place.py`).
  `bash -n` on `scripts/*.sh` runs in CI `lint`. A full compose smoke is not in CI (needs a fake Telegram endpoint); manual: `make up`.

## Proposed CLAUDE.md "Quality ratchet" line (user-owned file, not edited)
> 1059 unit tests green, branch coverage 91.9 % (floor 89 %), ruff 0, mypy --strict 0. Never get worse.
> (baseline `docs/audit/baseline-S1-tool.md`)
