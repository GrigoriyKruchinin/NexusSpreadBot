# Security review A7 — `config/nexus.toml` loader and guard

- Reviewer: security (critic, read-only on code), 2026-10-23
- Scope: commits `f28db06`, `8670a2f`; handoff `docs/handoffs/A7-to-review.md`;
  spec `docs/audit/security-config-split-A7.md`. `.env` was NOT read; probes ran in the session
  scratchpad against `nexus.config.file` only (no settings group built from the repo cwd, no DB).

## Verdict: **ACCEPT**

No blocking or medium findings. The low items below are follow-ups; none lets a secret or ENV-ONLY
value enter the effective settings through the TOML file.

## Checked against the spec

| Spec item | Result |
|---|---|
| 1 Allowlist first | `TOML_ALLOWED` = 71 SETTING names (65 + 6 from Table B); completeness/classification test ties it to the groups and to the repo file. Unknown key / table refused. |
| 2 Denylist | Exact list (10 names), `KEY_POLICY_` prefix and the spec regex, applied to `<table>_<key>` and to the bare key, case-insensitive, checked before the allowlist. Test asserts no allowed name hits the denylist. |
| 3 Value check | Credential URL and Telegram-token shape, recursive into lists and inline tables. |
| 4 Error content | `<path>:<line>: [table] key: reason`; parse errors give line/column only, `from None`; non-UTF-8 refused without content; `hide_input_in_errors=True` kept on the base config. See L1. |
| 5 Order / every role | Guard runs inside `settings_customise_sources` on every group load (scanner, workers, migrator via `MigratorSettings`, beat via `CelerySettings`); raises before any value is used. |
| 6 Missing file | Explicit path missing -> refuse; default missing -> refuse in container, WARNING locally. |
| 7 Env override log | `settings_loaded` carries service, path, hash, env-override NAMES only (`TOML_ALLOWED & present`); secrets can never be listed. See L3. |
| 8 Hash | SETTING fields only, filtered by `TOML_ALLOWED`; secrets are placeholders passed as init kwargs (never hashed); test proves secrets/ENV-ONLY do not change it. |
| 9 Tests | All required cases present (exact names, per-venue `_API_`, `key_policy.*`, credential value, unknown key, parse error), asserting key present and value absent. 147 config/compose tests pass. |
| ENV-ONLY not from TOML | `TELEGRAM_CHAT_ID`, `TELEGRAM_API_BASE_URL`, `KEY_POLICY_*`, `NEXUS_*` all refused (probed). |
| R2 integration DB | Conftest checks the MERGED `DatabaseSettings().db` == `nexus_test` and `pytest.exit`s otherwise; alembic uses the same merged sources; `test_migration_b15` uses the guarded fixture; unit test proves repo TOML (`db = "nexus"`) is refused. Unit tests hermetic via autouse `NEXUS_CONFIG_FILE` -> empty file; config tests also `chdir` to tmp (no `.env`). |
| R7 compose | `./config/nexus.toml:/app/config/nexus.toml:ro` on every app service; secrets stay per-service anchors; postgres DB/user tied to TOML by a test. |
| gitleaks | Two path-scoped rules (`^config/.*\.toml$`), no allowlist for `config/`; repo file does not match. See L2, L4. |

## Bypass probes (all refused unless stated)

Quoted key `"bot_token"`, dotted top-level `telegram.bot_token`, inline table `telegram = {bot_token=..}`,
upper-case `[TELEGRAM] BOT_TOKEN`, Cyrillic look-alike key (unknown), `[mexc] api_key`,
`[nexus_unbound_exchange] api_secret`, `[key_policy] *_attested`, `[telegram] api_base_url`,
`[telegram] chat_id`, `[nexus] runtime`, `[[spread]]` array of tables, credential URL under an allowed key,
token inside a list and inside an inline table, unquoted token (parse error: line/column only),
quoted `.env`-style file (top-level key named, value not printed). Accepted: `host = "user:pw@evil"`
(no scheme; host is SETTING, R4 — diff review).

## Findings

1. **L1 (low) — key and table names are echoed verbatim.** A secret placed in KEY position
   (`[telegram] "<token>" = 1` or `["<token>"]`) is printed in the `ConfigFileError` message. Unlikely
   (requires a malformed or wrong file), but the spec says "never a snippet of the file". Fix: print the
   name only if it matches `^[A-Za-z0-9_-]{1,64}$` and is not token/URL-shaped, otherwise
   `<unprintable key>` + line number; add a test.
2. **L2 (low) — gitleaks secret-key rule (spec regex) misses** quoted keys (`"bot_token" = ...`),
   dotted keys (`telegram.bot_token = ...`), inline tables, hyphenated keys, `chat_id`, and the URL rule
   misses upper-case schemes. Runtime guard covers all of these, so this is defence in depth only.
   Fix: e.g. `(?im)^\s*[^#\n=]*?(password|passwd|secret|token|passphrase|api_key|private_key|attested|_url|dsn|chat_id)[^=\n]*=\s*\S+`
   and `(?i)` on the URL rule. The spec regex was the reviewer's; no blame on the implementation.
3. **L3 (info) — `settings_loaded` is logged by scanner and Celery workers only**, not by migrator or
   beat (guard does run there). Acceptable; add if soak provenance needs it.
4. **L4 (info) — gitleaks rules not run with the real binary** (checked with Python `re`). Confirm the CI
   `secret-scan` job is green on this branch before the stage closes.
5. **L5 (info) — `tests/unit/config/conftest.py::isolated_env`** does not clear `KEY_POLICY_*` or
   `NEXUS_WORKER_ROLE`; harmless today, worth adding for hermeticity.

Accepted residual risks unchanged from the spec: R3 (stale `.env` overrides, now visible by name), R4
(`POSTGRES_HOST`), R5 (retention), R6 (`POSTGRES_ECHO`).
