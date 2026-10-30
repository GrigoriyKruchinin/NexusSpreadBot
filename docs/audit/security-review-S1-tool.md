# Security review - stage S1-tool (T14 gate)

- Reviewer: security (read-only)
- Date: 2026-10-25
- Branch / range: `chore/agent-pipeline-adoption`, `f603178~1..HEAD` (HEAD = 69c6a7e)
- Card: `docs/tasks/tool/T14-stage-gates.md` (scope item 3)
- Checks run: `make check` -> ruff 0, mypy --strict 0, **1059 passed**, 19 deselected (= baseline-S1-tool);
  `pytest tests/unit/test_safety.py tests/unit/adapters/test_key_policy.py` -> 161 passed; coverage TOTAL 92 %
  (`key_policy.py` 97 %, `startup_check/checks.py` 91 %). No dependency changes in range (`uv.lock` untouched;
  `pyproject.toml` only +license), so no new pip-audit run. Diff grep for secret shapes (Telegram token, AWS key,
  PEM, literal secrets): none. No `.env`, PEM or key files in the diff.
- Not done (by rule): no `.env` read, no `docker compose config`/`inspect`/`exec`, no containers.

## Verdict: **ACCEPT**

No blocking finding. Points R1-R6 below are recommendations (non-blocking, may go to the S2 backlog).
Point U1 is a **user action** on `.claude/settings.json` (agents may not edit it).
Point L1 records the decision on the lawyer's key statement.

## Findings by focus area

### 1. T9 key policy (b5f6ac3) - PASS
- Default mode: `container.enforce_key_policy` runs `verify_key_policies` before any market data / DB work;
  every rejected venue's keyed adapter is `close()`d and replaced by `exchange_registry.create(venue,
  ExchangeCredentials(), ...)` (credential-less ccxt client). `authenticated` excludes rejected venues; the
  close callback closes the rebuilt dict, not the rejected clients twice. If `close()` raises, startup aborts
  (fails closed, the keyed client is not used).
- Tested: `test_rejected_key_is_never_used_the_venue_gets_a_credential_less_client` asserts the rebuilt
  client has no `apiKey`/`secret` and other venues are unaffected; `test_scanner_scope_verifies_keys_before_anything_else`.
- Strict mode: `KeyPolicyViolationError` raised on any rejection; IP unbound and unverifiable properties
  become violations; CLI exits 3, compose wrapper parks (no restart loop). Tests:
  `test_strict_mode_refuses_instead_of_falling_back`, `test_strict_marks_unverifiable_properties_as_violations`,
  `test_strict_mode_fails_the_check`, `test_cli_exits_non_zero_on_key_policy_violation`.
- Fail-closed paths: request failure, any exception, parser bug, venue without policy (e.g. bitget/mexc),
  adapter without `fetch_key_info` -> rejected. Single signed GET, no retry. Raw payload never logged
  (`test_logs_contain_no_response_fields`); only rule names with a safe charset leave the module.
- Deprecated attestation variables: only NAMES reported.
- Read-only guard (`install_read_only_guard`) is installed on every ccxt client incl. the rebuilt public one.

### 2. Residual risk KuCoin / Gate.io - documentation ADEQUATE (R1 accuracy fix)
README "Read-only API keys" and quickstart (RU) "Что проверить самим" both state the residual risk and tell
the user to verify by hand; `nexus check` prints a `venue_keyed_warn` line on every start for these venues.
Precision issue (R1, on the safe side, non-blocking): KuCoin permissions ARE checked (allow-list `General`);
only its IP whitelist is unverifiable. For Gate.io the permissions are unverifiable and in default mode such
a key **is still used** (warning only). Suggested text: "KuCoin: Nexus checks permissions but cannot see the
IP whitelist. Gate.io: Nexus cannot see permissions; a Gate.io key with trade/withdraw rights would still be
used for reading in default mode (Nexus never sends orders or withdrawals, but a leaked key would be
dangerous). Check it by hand, or use `KEY_POLICY_STRICT=true` to refuse it."

### 3. T7 `nexus check` (3b02eea) - PASS (R2)
- Telegram token is only in the request URL; `httpx.HTTPError` reduced to the class name, never chained;
  API errors reported as status codes; bot username/chat type pass through `safe()`. DB errors: class name
  only. Venue results: rule names via `safe()`. Test message text is a fixed catalog string.
- httpx request-URL INFO logs are not printed (no handler configured -> stdlib lastResort is WARNING+).
- R2 (low, defense in depth): `cli.main` does not call `configure_logging` for `check`, so structlog runs
  with its default dev renderer **without** `redact_processor`. Today no log call on that path carries a
  secret (key_policy logs rule names only; fetch_key_info has no retry log), so there is no leak, but a
  future log line would be unscrubbed. Recommend `configure_logging(LoggingSettings(), service="check")`
  (with level WARNING to keep the report clean).

### 4. T8 `scripts/start.sh` - PASS (R3)
- `set +x`; presence checks by NAME with `grep -q`; no value printed or stored in a shell variable that is
  echoed. Password: `openssl rand` -> env var -> `awk ENVIRON[...]` -> temp file from `mktemp` under
  `umask 077`, `chmod 600`, atomic `mv`; trap removes the temp file; only a fixed message is echoed.
  Refuses to generate when the DB volume exists (no silent password mismatch). No `config`/`inspect`/`exec`.
  Temp `.env.XXXXXX` files are covered by `.gitignore` and `.dockerignore` (`.env.*`).
- R3 (low): if the user skipped `chmod 600` and set the password himself, `.env` (with exchange keys) stays
  0644. Suggest start.sh warn (or `chmod 600`) when `.env` is group/world-readable.

### 5. `docker-compose.yml` - PASS (R4, R5)
- No bind mounts (D-01b); config baked into image. App services: `USER nexus` (Dockerfile), `read_only`,
  `tmpfs /tmp`, `no-new-privileges`, log rotation.
- Secrets: per-service `environment:` interpolation from `.env` with least privilege (Telegram only in
  worker-alerts/check, exchange keys only in scanner/check, beat gets no secrets). This is stricter than
  `env_file` (which would give every service everything) - accepted as the intended design.
- No default passwords: `POSTGRES_PASSWORD`/`TELEGRAM_*` use `${VAR:?}` (start fails if empty).
- Redis: not published. Postgres: published on **127.0.0.1:5432 only** (not 0.0.0.0) - acceptable.
- R4 (low): for third-party users make the Postgres port opt-in (override file or profile), which also
  avoids a clash with a local Postgres on 5432; document that it is loopback only.
- R5 (low): `postgres:17-alpine` / `redis:7-alpine` are tag-pinned, not digest-pinned, and lack
  `no-new-privileges`. Pre-existing; backlog.

### 6. T5 Telegram edit / rate limit (2364740, c9c253b) - PASS
`TelegramNotifier`: token only in `_url()`; transport errors -> class name, `from None`; rejections carry
Telegram's `description` only. Rate limiter logs no token. Workers call `configure_logging` (redaction +
httpx at WARNING; Celery root logger not hijacked).

### 7. `.env.example` - PASS
All values empty; examples are visibly fake (`AAFake...`, rejected by the placeholder check); tells the user
`chmod 600`, read-only keys, never commit/paste `.env`. No real-looking secrets.

### 8. ADR 0001 safety tests - PASS
`tests/unit/test_safety.py` still covers: static AST scan of `src/` for withdraw/transfer/order/margin/
position/raw-request calls (only `list_transfer_routes` allow-entry removed together with HT1 code), interface
check without `withdraw`, runtime GET-only guard incl. bypass snippets. The perp-port test was removed with
the perp port itself (no perp code left). New `startup_check` code is inside `src/` and thus scanned; its
HTTP POSTs go only to the Telegram Bot API.

## L1. Lawyer statement s.3.3 ("Your keys stay with you") - APPROVED verbatim, with conditions
Verified in code: (a) keys go only into ccxt clients for the venue's own API hosts (only hard-coded hosts in
`src/` are api.telegram.org and a public, key-less binance.com bapi URL); (b) never logged (SecretStr,
rule-name-only key-policy logs, ccxt messages URL-stripped and scrubbed, causes dropped), never in DB tables,
never in Telegram (start notice lists venue NAMES only), never in `nexus check` output; (c) no telemetry
dependency or phone-home code. The statement in s.3.3 of `docs/legal/tool-distribution.md` **may be used
verbatim** in README (EN) and an equivalent RU text in the quickstart, on these conditions:
1. The residual-risk bullet (KuCoin/Gate.io, with the R1 precision) stays directly next to it, because
   "keys are ... read-only" is a requirement on the user, not something Nexus can guarantee on Gate.io.
2. The placeholder paragraph at README lines 79-82 ("being verified in the security review (T9) ...
   design goal, not a guarantee") is replaced by the statement.
3. Re-check if any of these change: new outbound host, telemetry/crash reporting, logging of adapter
   errors, or storage of credentials.
Note for completeness (not a contradiction): Docker keeps container environment in local container metadata
on the user's own machine; that is still "with you".

## U1. `.claude/settings.json` - rules that no longer cover the renamed compose file (USER to apply)
The stack file is now `docker-compose.yml` (default name). Generic rules (`docker compose config:*`,
`exec:*`, `run:*`, `down -v:*`, `down --volumes:*`) still cover calls WITHOUT `-f`, but these rules only match
the old name and no longer protect anything:
- deny: `docker compose -f docker-compose.local.yml down -v:*`, `... down --volumes:*`, `... config:*`,
  `... exec:*`, `... run:*`, `docker compose -f ./docker-compose.local.yml config:*`, `... exec:*`, `... run:*`
- allow (stale, harmless): `docker compose -f docker-compose.local.yml ps:*`, `... logs:*`
- ask (stale targets that no longer exist): `make up-local`, `make down-local`

Uncovered today: `docker compose -f docker-compose.yml config|exec|run|down -v`, any global option before the
subcommand (`docker compose --profile tools run --rm check env`, `--project-directory . config`, `--ansi never
config`), `docker compose convert` (alias of config), `docker compose cp`, `docker cp`,
`docker container exec|run|cp`, `make reset-data`, and `make up`/`make down`/`make doctor`/`scripts/start.sh`
are not in "ask".

Proposed replacement (remove the 8 deny + 2 allow + 2 ask stale lines above, then add):
```json
"allow": [
  "Bash(docker compose ps:*)",
  "Bash(docker compose logs:*)"
],
"ask": [
  "Bash(make up)",
  "Bash(make down)",
  "Bash(make doctor:*)",
  "Bash(scripts/start.sh:*)",
  "Bash(./scripts/start.sh:*)",
  "Bash(bash scripts/start.sh:*)"
],
"deny": [
  "Bash(docker compose -f:*)",
  "Bash(docker compose --profile:*)",
  "Bash(docker compose --project-directory:*)",
  "Bash(docker compose --ansi:*)",
  "Bash(docker compose --progress:*)",
  "Bash(docker compose --parallel:*)",
  "Bash(docker compose --dry-run:*)",
  "Bash(docker compose convert:*)",
  "Bash(docker compose cp:*)",
  "Bash(docker cp:*)",
  "Bash(docker container exec:*)",
  "Bash(docker container run:*)",
  "Bash(docker container cp:*)",
  "Bash(make reset-data:*)",
  "Read(./.env.*)"
]
```
`Read(./.env.*)` also covers the transient `.env.XXXXXX` temp file of start.sh (`.env.example` is then
denied for Read too; agents can still `cat .env.example`, or the user may skip this line). Keep all existing
generic rules (`docker compose config:*`, `exec:*`, `run:*`, `down -v:*`, `down --volumes:*`,
`--file:*`, `-p:*`, `--env-file:*`, `docker run:*`, `docker exec:*`, `docker inspect:*`).

## Recommendations summary (non-blocking)
| # | Sev | Item |
|---|---|---|
| R1 | low | Docs: KuCoin perms are checked (IP not); Gate.io key with write rights is still used in default mode - say so |
| R2 | low | `nexus check`: call `configure_logging` so the redaction processor is active |
| R3 | low | start.sh: warn/chmod when `.env` is group/world-readable |
| R4 | low | Postgres loopback port opt-in for third parties |
| R5 | low | Digest-pin postgres/redis images, add `no-new-privileges` |
| R6 | info | Old file name `docker-compose.local.yml` remains in historic audit docs/handoff - fine as history; repo-hygiene may annotate |

---

## Follow-up 2026-10-30 - fix round (3897f27..5be3081)

Scope: R1-R5 closure and the new changes (start.sh `.env` permission warning, opt-in Postgres port,
digest-pinned images, redacting logging in `nexus check`, key-check retries, `nexus pin-text`,
`config/local.toml` overlay baked into the image, hermetic config tests, E2E guide). Read-only review;
`.env` not read, no docker commands run.

### Verdict: **ACCEPT**

No blocking finding. One partial (R5b) and one informational item carried to the S2 backlog.

### R1-R5 closure
| # | Status | Evidence |
|---|---|---|
| R1 | CLOSED | README + quickstart: KuCoin perms checked / IP not visible; Gate.io perms not visible, write-capable key still used in default mode, `KEY_POLICY_STRICT=true` refuses it. L1 statement kept verbatim next to the residual-risk bullet. |
| R2 | CLOSED | `cli.main` `check` branch calls `configure_logging(LoggingSettings(level="WARNING", json_format=False))` before `run`; runner tests added. |
| R3 | CLOSED | `scripts/start.sh` warns (mode only, never values) when group/other bits are set; `600`/`400`/`700` silent. |
| R4 | CLOSED | No `ports:` in `docker-compose.yml` at all; `docker-compose.postgres-port.yml` is opt-in and binds `127.0.0.1` only. |
| R5 | PARTIAL | postgres/redis digest-pinned (tag+digest). `no-new-privileges` is on every app service (`x-image`) but not on `postgres`/`redis` (R5b, low: internal network, no published port). |

### New changes
- **config/local.toml**: gitignored (`.gitignore:238`, `git check-ignore` confirms, not tracked). Deliberately
  NOT in `.dockerignore`: it is baked into the image via `COPY config/nexus.toml config/local.tom[l]`. The
  overlay goes through the same `validate_config` guard (denied names, allow-list `TOML_ALLOWED`,
  credential-value heuristic); test `test_local_overlay_is_guarded_like_the_main_file` covers a
  `[telegram] bot_token` refusal. Env still wins over the overlay. A secret therefore cannot load from it,
  and the file is not committed. Residual (info): the image carries the owner's personal settings; do not
  push `nexus-spread-bot:local` to a public registry (it is a local tag, no push target exists).
- **Startup / Telegram messages**: `ScannerStarted` renders venue names, market counts, auth icon,
  IP-unbound / public-fallback venue names only. `pin-text` prints a static catalog text. No token, chat id,
  key or password in any new template.
- **Key-check retries**: only class names logged (`error=type(exc).__name__`); auth errors not retried.
- **Placeholder check**: now `fullmatch`; the token value is never echoed in the result item.
- **Telegram token scope**: unchanged; token only in the `x-telegram-env` services. `check` profile service
  receives it by design (it validates it).
- **Default passwords**: none. `POSTGRES_PASSWORD` is `:?` required; Redis has no password but no
  published port (internal network only).
- **`.claude/settings.json`**: old `-f docker-compose.local.yml` rules replaced by generic denies
  (`docker compose -f:*`, `--profile:*`, `--project-directory:*`, `cp`, `convert`, `container exec/run/cp`,
  `make reset-data:*`); all earlier generic guards kept. Matches U1.
- **E2E guide `docs/guides/s1-tool-e2e-check.md`**: tells the user not to show the token or `.env`, to mask
  token and chat id on screenshots, to edit `.env` himself, and forbids `down -v` / `reset-data`. The
  suggested `docker compose --profile tools run --rm check ls /app/config` lists file names only. PASS.
- **Secrets scan** (grep over the 3897f27..HEAD diff for key/secret/password/token literals): 0 hits.
  gitleaks not installed.

### Carried to S2 backlog (non-blocking)
| # | Sev | Item |
|---|---|---|
| R5b | low | Add `security_opt: ["no-new-privileges:true"]` to `postgres` and `redis` (compatible with their gosu/su-exec entrypoints). |
| I1 | info | Pre-existing: `ExchangeDown` puts `str(ExchangeError)[:500]` into Telegram. With keys, a ccxt error text may embed a request URL (signed query, never the secret). Consider passing it through the same redaction as logs, or class name + HTTP status only. |
