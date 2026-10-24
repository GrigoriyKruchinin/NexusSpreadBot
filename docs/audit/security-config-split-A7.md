# Security pre-check A7 — secret / setting split for `config/nexus.toml`

- Task: `docs/tasks/track0/A7-config-file.md` (Scope 1, Scope 3)
- Author: security (critic, read-only on code), 2026-10-23
- Sources read: `.env.example`, `src/nexus/config/{base,groups,roles}.py`, `docker-compose*.yml` (variable
  names only), `.github/workflows/ci.yml`, `.gitleaks.toml`, `.pre-commit-config.yaml`. `.env` was NOT read.
- Repository visibility at time of review: private.

## Classes

| Class | Lives in | TOML allowed? | In run-settings hash? |
|---|---|---|---|
| **SECRET** | `.env` / container env only | No — startup refused | No (never, not even hashed) |
| **ENV-ONLY** | `.env` / container env only | No — startup refused | No |
| **SETTING** | `config/nexus.toml` (env may override) | Yes | Yes |

ENV-ONLY is a third class introduced by this review: values that are not credentials but must still not
live in a committed, agent-editable file (personal identifiers, human-only safety attestations, values that
choose where a secret is sent, deployment plumbing). For the guard they behave exactly like SECRET.

## Counts

- `.env.example`: 84 variables -> SECRET 16, ENV-ONLY 3, SETTING 65.
- Read by `src/nexus/config/*.py` (or runtime) but missing from `.env.example`: 13 names/patterns ->
  SECRET 3 (patterns), ENV-ONLY 4, SETTING 6.

## Table A — variables in `.env.example`

| Variable | Group | Class | Reason |
|---|---|---|---|
| TELEGRAM_BOT_TOKEN | telegram | SECRET | Full control of the bot. |
| TELEGRAM_CHAT_ID | telegram | ENV-ONLY | Not a credential (useless without the token), but a private-chat id equals the user's Telegram user id = personal identifier; git history is permanent and agents read the TOML. Zero cost to keep in env. **Contested** (see C1). |
| TELEGRAM_DISABLE_NOTIFICATION | telegram | SETTING | Behaviour flag. |
| TELEGRAM_ALERT_MAX_AGE_S | telegram | SETTING | Tunable. |
| TELEGRAM_EVENT_MAX_AGE_S | telegram | SETTING | Tunable. |
| POSTGRES_HOST | postgres | SETTING | Not sensitive; differs per environment, compose overrides it via env. Note: it is where the password is sent — see R4. |
| POSTGRES_PORT | postgres | SETTING | Not sensitive. |
| POSTGRES_DB | postgres | SETTING | Not sensitive. TOML value must stay `nexus`; integration safety must not rely on it — see R2. |
| POSTGRES_USER | postgres | SETTING | Low sensitivity (half a credential pair, but a default well-known name `nexus`; the password is the secret). **Contested lightly** (C2). |
| POSTGRES_PASSWORD | postgres | SECRET | Credential. |
| REDIS_URL | redis | SECRET | `SecretStr` in code; a Redis URL may embed a password (`redis://:pw@host`). Stays env even though the default has none. Splitting into host/port/db + `REDIS_PASSWORD` is a possible later change (out of scope: A7 must not change defaults). |
| CELERY_BROKER_URL | celery | SECRET | Same as REDIS_URL. |
| CELERY_TIMEZONE | celery | SETTING | Tunable. |
| LOG_LEVEL | logging | SETTING | Tunable (DEBUG relies on the existing redaction processor). |
| LOG_JSON_FORMAT | logging | SETTING | Tunable. |
| EXCHANGES_ENABLED | exchanges | SETTING | Universe; part of run hash. |
| EXCHANGES_REQUEST_TIMEOUT_MS | exchanges | SETTING | Tunable. |
| CONDITIONAL_VENUES | conditional | SETTING | Universe; part of run hash. |
| BYBIT_API_KEY / BYBIT_API_SECRET | credentials | SECRET | Exchange credential. |
| BINANCE_API_KEY / BINANCE_API_SECRET | credentials | SECRET | Exchange credential. |
| OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE | credentials | SECRET | Exchange credential. |
| GATEIO_API_KEY / GATEIO_API_SECRET | credentials | SECRET | Exchange credential. |
| KUCOIN_API_KEY / KUCOIN_API_SECRET / KUCOIN_API_PASSPHRASE | credentials | SECRET | Exchange credential. |
| KEY_POLICY_KUCOIN_IP_ATTESTED | key_policy | ENV-ONLY | Not a secret, but a human-only safety gate tied to the specific key in `.env`. In a committed agent-editable file an agent (or a merge) could flip it, and the attestation would survive a key rotation. It must live next to the key it attests. **Contested** (C3). |
| KEY_POLICY_GATEIO_PERMISSIONS_ATTESTED | key_policy | ENV-ONLY | Same as above. |
| SCANNER_QUOTE_ASSETS, SCANNER_SYMBOLS_WHITELIST, SCANNER_SYMBOLS_BLACKLIST, SCANNER_MIN_QUOTE_VOLUME_USD, SCANNER_TICKER_INTERVAL_S, SCANNER_METADATA_REFRESH_S, SCANNER_ORDERBOOK_DEPTH, SCANNER_MAX_CANDIDATES_PER_SWEEP, SCANNER_MAX_CONCURRENT_REQUESTS_PER_EXCHANGE, SCANNER_SNAPSHOT_TOP_K, SCANNER_HEARTBEAT_TTL_S, SCANNER_EXCHANGE_DOWN_AFTER_FAILURES, SCANNER_RATE_LIMIT_BACKOFF_S, SCANNER_WS_ENABLED, SCANNER_WS_MAX_STREAMS, SCANNER_WS_HOT_TTL_S (16) | scanner | SETTING | Tunables, no sensitivity. |
| SPREAD_MIN_NET_PROFIT_PCT, SPREAD_MIN_NET_PROFIT_USD, SPREAD_REFERENCE_NOTIONAL_USD, SPREAD_MAX_ORDERBOOK_AGE_MS, SPREAD_MAX_BOOK_SKEW_MS, SPREAD_MAX_GROSS_SPREAD_PCT, SPREAD_MAX_UNVERIFIED_GROSS_SPREAD_PCT, SPREAD_DEFAULT_TAKER_FEE_PCT, SPREAD_INCLUDE_TRANSFER_COST, SPREAD_TRANSFER_TAX_PCT, SPREAD_REQUIRE_VERIFIED_TRANSFER, SPREAD_ALERT_COOLDOWN_S (12) | spread | SETTING | Tunables; part of run hash. |
| ALERT_REALERT_GROWTH_PCT | alert | SETTING | Tunable. |
| EPISODE_CLOSE_GAP_S | episode | SETTING | Tunable. |
| QUARANTINE_PERSIST_MIN, QUARANTINE_TTL_H, QUARANTINE_WINDOW_H, QUARANTINE_MAX_EPISODES (4) | quarantine | SETTING | Tunables. |
| PAPER_ENABLED, PAPER_VENUE_SETS, PAPER_CAPITAL_USD, PAPER_USDT_SHARE_PCT, PAPER_COIN_PER_ROUTE_USD, PAPER_COIN_IDLE_RELEASE_H, PAPER_CONVERSION_COST_PCT, PAPER_TRADE_NOTIONAL_USD, PAPER_LATENCY_MS, PAPER_REBALANCE_THRESHOLD_PCT, PAPER_REBALANCE_DELAY_MIN (11) | paper | SETTING | Simulation tunables (virtual capital, no money); part of run hash. |
| MAINTENANCE_SNAPSHOT_RETENTION_DAYS, MAINTENANCE_EVALUATION_RETENTION_DAYS, MAINTENANCE_EPISODE_RETENTION_DAYS, MAINTENANCE_CLEANUP_INTERVAL_S (4) | maintenance | SETTING | Tunables. Note: lowering retention is a data-deletion lever — keep under diff review (R5). |
| DIGEST_ENABLED, DIGEST_TIME, DIGEST_TZ (3) | digest | SETTING | Tunables. |

## Table B — read by code/runtime but absent from `.env.example`

| Variable | Source | Class | Reason |
|---|---|---|---|
| POSTGRES_POOL_SIZE | `DatabaseSettings.pool_size` | SETTING | Tunable. |
| POSTGRES_MAX_OVERFLOW | `DatabaseSettings.max_overflow` | SETTING | Tunable. |
| POSTGRES_ECHO | `DatabaseSettings.echo` | SETTING | Tunable, but `echo=true` makes SQLAlchemy log SQL with bound parameters, bypassing structured redaction. Not a secret leak today (no secrets in SQL), flag only (R6). |
| REDIS_SOCKET_TIMEOUT_S | `RedisSettings.socket_timeout_s` | SETTING | Tunable. |
| CELERY_RESULT_BACKEND | `CelerySettings.result_backend` (`SecretStr`) | SECRET | URL that may embed credentials. |
| TELEGRAM_API_BASE_URL | `TelegramSettings.api_base_url` | ENV-ONLY | The bot token travels in the URL path to this host. One line changed in a committed, agent-editable file would send the token to any https host (the `https://` validator does not prevent this). No legitimate reason to vary it. **Contested** (C4). |
| TELEGRAM_REQUEST_TIMEOUT_S | `TelegramSettings.request_timeout_s` | SETTING | Tunable. |
| `<NAME>_API_KEY` / `_API_SECRET` / `_API_PASSPHRASE` for any venue (MEXC_*, BITGET_* on extension runs) | `ExchangeCredentials.for_exchange` (dynamic prefix) | SECRET | Exchange credential; must be matched by pattern, not by a fixed list. |
| NEXUS_UNBOUND_EXCHANGE_API_* | sentinel prefix of `ExchangeCredentials` | SECRET | Same fields; pattern covers it. |
| NEXUS_RUNTIME | `base.py` (disables `.env` in containers) | ENV-ONLY | Deployment plumbing; setting it from the file being loaded is circular. |
| NEXUS_WORKER_ROLE | `workers/tasks.py` | ENV-ONLY | Per-container identity, set by compose. |
| NEXUS_CONFIG_FILE | new in A7 | ENV-ONLY | Points at the TOML; cannot be in it. |
| HOSTNAME | compose | ENV-ONLY | Container plumbing, not a Nexus setting. |

Unclear meaning: none blocking. `HOSTNAME` appears in compose only (healthcheck/worker naming); not a
settings field — leave it out of the TOML schema entirely.

## Startup guard spec (Scope 3, fail closed)

1. **Allowlist first.** The TOML loader accepts only keys that map to a field classified SETTING above
   (explicit list kept next to the settings groups, e.g. `TOML_ALLOWED: frozenset[str]` of full env names).
   Any other key — SECRET, ENV-ONLY, misspelled, or unknown table — refuses startup. This is what makes
   "unknown key handling (fail closed)" and "secret-in-TOML refusal" one mechanism.
2. **Denylist as belt and braces** (applied even if a future field is wrongly added to the allowlist),
   case-insensitive, on the normalized full name (`<table>_<key>` upper-cased, also on the bare key):
   - exact: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_API_BASE_URL`, `POSTGRES_PASSWORD`,
     `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `NEXUS_RUNTIME`, `NEXUS_WORKER_ROLE`,
     `NEXUS_CONFIG_FILE`;
   - prefix: `KEY_POLICY_`;
   - regex: `(?i)(_API_(KEY|SECRET|PASSPHRASE)$|PASSWORD|PASSWD|SECRET|TOKEN|PASSPHRASE|PRIVATE_KEY|CREDENTIAL|DSN|_URL$|_ATTESTED$)`.
3. **Value check** (any string value, any key): refuse if it matches a credential-bearing URL
   `[a-z][a-z0-9+.-]*://[^/\s:@]*:[^/\s@]+@` or a Telegram-token shape `\d{6,}:[A-Za-z0-9_-]{20,}`.
   Error names the key only.
4. **Error content.** Message = file path + key name (+ line number for parse errors) + reason class
   ("secret/env-only key not allowed in TOML", "unknown key"). Never the value, never a snippet of the file.
   Catch `tomllib.TOMLDecodeError` and re-raise with path + line/column only (protects the case where
   `NEXUS_CONFIG_FILE` mistakenly points at `.env`). Keep `hide_input_in_errors=True` on the TOML source path.
5. **Order.** Guard runs on the raw parsed TOML dict before any pydantic source is built, in every role
   (scanner, workers, migrator, scheduler); exit non-zero, no partial start.
6. **Missing file** (to be documented by backend-lead): `NEXUS_CONFIG_FILE` set but file missing ->
   refuse. Default path missing -> refuse in containers (`NEXUS_RUNTIME=container`, soak reproducibility);
   locally a WARNING + code defaults is acceptable.
7. **Env override visibility.** At startup log one INFO/WARNING event listing the NAMES of SETTING fields
   whose effective value came from env/`.env` rather than TOML (values not needed; names only). Old local
   `.env` files still contain settings and would otherwise silently override the versioned file.
8. **Run-settings hash (Scope 5)** covers SETTING fields only. SECRET and ENV-ONLY fields are excluded
   entirely (no hashing of secrets: a hash of a credential is still derived material).
9. **Tests required:** each exact denylist name, one per-venue `_API_` pattern (e.g. `mexc_api_key` in a
   `[credentials]`-like table), `key_policy.*`, a credential URL value under an allowed-looking key, unknown
   key, parse error — each asserting the error contains the key name and does NOT contain the value.

## gitleaks

Yes, add a rule. Default gitleaks rules need high entropy or known token shapes; a weak password or a
`redis://:pw@` DSN in `config/nexus.toml` can slip through. Proposed (scoped by path, no allowlist):

```toml
[[rules]]
id = "nexus-config-toml-secret-key"
description = "Secret-like key with a value in committed config TOML"
path = '''^config/.*\.toml$'''
regex = '''(?im)^\s*[a-z0-9_]*(password|passwd|secret|token|passphrase|api_key|private_key|attested|_url|dsn)[a-z0-9_]*\s*=\s*\S+'''

[[rules]]
id = "nexus-config-toml-credential-url"
description = "URL with embedded credentials in committed config TOML"
path = '''^config/.*\.toml$'''
regex = '''[a-z][a-z0-9+.-]*://[^/\s:@]*:[^/\s@]+@'''
```

Never add an allowlist entry for `config/`. Verify the rules with a throwaway file under the scratchpad
copy, not by committing a sample.

## Risks

- **R1 (high if missed) — agents edit settings freely.** That is the goal of A7, so anything an agent
  must not change (attestations, Telegram host, credentials) has to be ENV-ONLY, not "SETTING with care".
- **R2 (high) — integration DB safety (R-01).** `POSTGRES_DB = "nexus"` in a committed TOML means a test
  run without env would target the live DB. The integration conftest must assert the EFFECTIVE merged
  `DatabaseSettings.db == "nexus_test"` (not just the env var, as CI does today) and refuse otherwise.
  Unit tests must not pick up the repo `config/nexus.toml` implicitly (set `NEXUS_CONFIG_FILE` to a fixture
  or disable the source in test setup) — hermetic tests.
- **R3 (medium) — stale `.env` overrides.** Env > TOML; old `.env` files override the versioned file.
  Mitigated by guard item 7 + run hash over effective values; the Russian guide should tell the user to
  delete setting lines from `.env` after migration.
- **R4 (low/medium) — credential destination via `POSTGRES_HOST`.** Changing the host in TOML would send
  the DB login to that host (asyncpg may answer a cleartext-password request). Accepted as SETTING because
  compose overrides it and it differs per environment; tech-lead diff review must treat host changes as
  security-relevant.
- **R5 (low) — retention values** are a data-deletion lever; diff review only.
- **R6 (low) — `POSTGRES_ECHO`** logs bound SQL parameters outside structlog redaction.
- **R7 (low) — container mount.** Mount `config/nexus.toml` read-only (`:ro`) into services; it holds no
  secrets so mounting it into every role does not weaken per-service isolation.

## Contested items

- **C1 TELEGRAM_CHAT_ID** -> ENV-ONLY (recommended). Alternative SETTING is acceptable in a private repo;
  cost of ENV-ONLY is nil.
- **C2 POSTGRES_USER** -> SETTING. Alternative ENV-ONLY if the user prefers all DB-login parts together.
- **C3 KEY_POLICY_*** -> ENV-ONLY (recommended, strongly): human attestation must not be agent-flippable.
- **C4 TELEGRAM_API_BASE_URL** -> ENV-ONLY (recommended): token-exfiltration vector otherwise.

No NEEDS_USER: all recommendations are on the safe side and do not change defaults or behaviour.
