# A7 -> review: non-secret settings in `config/nexus.toml`

- Author: backend-lead, 2026-10-23. Task: `docs/tasks/track0/A7-config-file.md`. Spec (wins over the card):
  `docs/audit/security-config-split-A7.md`. `todo.md` NOT ticked (reviewers first).
- Reviewers: security (guard, gitleaks, split), tech-lead (diff).

## What changed
- `src/nexus/config/file.py`: `NexusTomlSource` (subclass of pydantic-settings `TomlConfigSettingsSource`),
  `TOML_ALLOWED` (65 + 6 SETTING names), denylist, value check, `ConfigFileError`.
- `src/nexus/config/base.py`: source order init > env > `.env` (local only) > TOML > secrets dir. Table = env
  prefix without trailing `_` (`[spread]`, `[log]`, ...), key = field name. Guard runs on every group load, so
  every role (scanner, workers, migrator, scheduler) refuses a bad file; no partial start.
- `src/nexus/config/provenance.py`: `env_overridden_names()` (R3), `settings_hash()`, `log_settings_provenance()`
  (event `settings_loaded`: service, config_file, settings_hash, env_overrides names). Called from
  `cli._run_scanner` and the worker `_init_logging`.
- `config/nexus.toml`: every SETTING key, commented, values == code defaults (test proves no default changed).
- `.env.example` shrunk to SECRET + ENV-ONLY (TELEGRAM token/chat id, POSTGRES_PASSWORD, REDIS_URL,
  CELERY_BROKER_URL, API keys, KEY_POLICY_*). `docker-compose.local.yml`: setting vars removed (only
  `POSTGRES_HOST: postgres` remains as env override), `config/nexus.toml` mounted `:ro` into app services (R7),
  postgres container `POSTGRES_DB/USER` hardcoded `nexus` (a test ties them to the TOML).
- `.gitleaks.toml`: two path-scoped rules from the spec, no allowlist for `config/`. NOT run with the real
  gitleaks locally (binary absent); regexes were checked with Python `re` (no match on the file, match on samples);
  CI secret-scan is the real check.
- Russian guide `docs/guides/stage-1-local-setup.md` + README updated (delete leftover setting lines from `.env`).

## Decisions / behaviour to review
- Missing file: `NEXUS_CONFIG_FILE` set -> refuse; default `config/nexus.toml` (cwd-relative) missing -> refuse when
  `NEXUS_RUNTIME=container`, WARNING `config_file_missing` + code defaults locally.
- Error format: `<path>:<line>: [table] key: reason`; line is best effort from the raw text; parse errors give
  line/column only and are re-raised `from None`.
- R2: `DatabaseSettings()` in the integration conftest is already the merged result; comment added; unit test
  `test_merged_db_name_is_what_the_integration_guard_checks` shows repo TOML gives `nexus` and the guard refuses.
  Unit tests are hermetic via `tests/unit/conftest.py` (autouse `NEXUS_CONFIG_FILE` -> empty file).
- Run-settings hash (Scope 5): sha256 of typed, normalized effective values of SETTING fields only, built from the
  settings groups with placeholder secrets (never hashed). Role independent, source independent (same value from env
  or TOML hashes equal). Code defaults of keys absent from the file are included via the typed values. It is
  separate from the B15 paper `config_hash` (`scanner/paper.py:definition`), which is UNCHANGED; the GO report can
  cite both. The hash is logged, not persisted to the DB (no migration).
- `env_overrides` is INFO level (in containers `POSTGRES_HOST` always shows up, a WARNING would be noise).
- Deviation: `EXCHANGES_ENABLED`/`CONDITIONAL_VENUES` etc. in a stale `.env` still override silently except for the log.

## Pitfalls
- `POSTGRES_HOST` in TOML is `localhost`; compose overrides it to `postgres` (security-relevant if changed, R4).
- Adding a settings field needs: `TOML_ALLOWED`, `config/nexus.toml`, and the tests in `test_config_file.py` will fail
  until both are done (completeness + classification test).
- Not verified here: `docker compose config` / a real stack start (no docker run per rules); CI jobs.

## Round 2 (backend-lead, 2026-10-23) - fixes for tech-lead RETURN and security L1-L5

| Point | Fix | Commit |
|---|---|---|
| TL1 dict/list merge | `NexusTomlSource` drops a key when its full name is set non-empty in env or (locally) `.env`; shared `present_env_names()`. Tests: dict/list, `.env`, container, empty env | "fix(config): A7 round 2 ..." |
| TL2 stale `.env` lines | Containers cannot see `.env`, so detection is host-side: `make check-env-settings` (also run by `make up-local`) prints NAMES only; Russian guide rewritten (docker ignores, host overrides, move values into the TOML) | same |
| TL2 soak venue sets | `[paper] venue_sets` = 4 soak sets; valid with default venues (test); defaults-equality test allows exactly this deviation | "feat(config): set the four soak venue sets ..." |
| TL3 hash | Decimals normalized; `POSTGRES_*`, `REDIS_*`, `LOG_*` excluded (deployment plumbing) | first |
| TL4 tests | Telegram in defaults-equality; bare keys vs denylist; `not_settings` derived from `_DENY_EXACT` | first |
| TL5 / sec L3 | beat (`beat_init`) and migrator (`migrations/env.py`) log `settings_loaded` | first |
| sec L1 | key/table names not matching `[A-Za-z0-9_-]{1,64}` print as `<unprintable key>` | first |
| sec L2 | gitleaks key rule from the review (prefix `[^#\n]*?`, adds `chat_id`), URL rule `(?i)`; tested with Python `re` | first |
| sec L5 | `isolated_env` clears `KEY_POLICY_*` and `NEXUS_WORKER_ROLE` | first |

Notes: the GO report should cite the scanner `settings_loaded` event. The settings hash changed
definition (new feature, nothing persisted). `todo.md` not ticked.
