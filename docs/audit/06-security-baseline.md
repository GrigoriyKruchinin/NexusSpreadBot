# 06 - Security Baseline (read-only audit, 2026-10-23)

Scope: repository at branch `chore/agent-pipeline-adoption`. No code was modified. No secret value was printed.

## Summary

| Area | Verdict |
|---|---|
| Secrets in tracked files / git history | PASS (no real secrets found; fake test fixtures only) |
| Dependency vulnerabilities | 2 packages affected (certifi, protobuf) - fix by bumping |
| Docker hardening | Good for app image; infra images lack hardening |
| Per-container settings isolation | Good, with minor over-grants |
| Secret logging | Mitigated (scrubber + SecretStr); one residual risk |
| Telegram / HTTP | Good |
| No withdraw / transfer / address calls | CONFIRMED, plus a runtime GET-only guard |
| No trading calls | CONFIRMED |

## 1. Secrets in code and history

- `.env` is git-ignored (`.gitignore:153`); only `.env.example` is tracked (all secret fields empty).
- `git ls-files` shows no key/pem/secret files.
- History scan (38 commits, all refs) for AWS-key, PEM private-key, generic `api_key/secret/password = "<16+ chars>"`, and Telegram-token shapes:
  - AWS / PEM / generic assignments: no hits.
  - Telegram-token-shaped strings in commits `7460288`, `865113a`, `c5a7948`, present today in `tests/unit/config/test_settings.py:18`, `tests/unit/notifications/test_telegram.py:13`, `tests/unit/test_log.py:10`. They are obviously synthetic (`123456789:AAHabcdef...`); LOW risk. Recommendation: confirm they are not a real token; if ever in doubt, revoke via @BotFather.
- Not verified: no dedicated scanner (gitleaks/trufflehog) was run; `.env` content was deliberately not read. Recommend adding gitleaks to pre-commit/CI.
- `.dockerignore` excludes `.env`, `.env.*`, `.git`, `.venv`, `.claude`. Good.

## 2. Dependency vulnerabilities

`pip-audit` 2.10.1 against `uv export --frozen --no-dev` (runtime deps, OSV/PyPI data, run online today):

| Package | Version | ID | Fix |
|---|---|---|---|
| certifi | 2026.10.18 | PYSEC-2026-4320 | 2026.10.19 |
| protobuf | 5.29.5 | PYSEC-2026-1805 | 5.29.6 / 6.33.5 |

- `protobuf==5.29.5` is hard-pinned in `pyproject.toml`; bump the pin to `5.29.6` (reason for the pin should be documented).
- certifi: `uv lock --upgrade-package certifi`.
- Dev-only dependencies were not audited. Add `pip-audit` to CI.

## 3. Docker hardening

Positive: multi-stage build; non-root user `nexus` (uid 10001, nologin shell); `read_only: true` + tmpfs `/tmp`; `no-new-privileges`; `init: true`; log rotation; healthchecks; uv pinned to 0.9.8; Postgres published only on `127.0.0.1:5432`; Redis not published; secrets required with `:?` guards.

Findings:
- MEDIUM: base images tagged, not pinned by digest (`python:3.12-slim`, `postgres:17-alpine`, `redis:7-alpine`). Pin digests for production.
- MEDIUM: Redis has no password and no `--protected-mode`/ACL config; safe only while the compose network stays private. Add `requirepass` before any VPS use (Stage 2).
- LOW: `postgres` and `redis` services lack `read_only`, `no-new-privileges`, `cap_drop: [ALL]`, and log limits. App services lack `cap_drop: [ALL]`.
- LOW: secrets are passed as environment variables (visible via `docker inspect`); Docker/Compose secrets (`_FILE`) would be stronger. `file_secret_settings` is already enabled in `config/base.py`.
- LOW: Postgres password reachable on the loopback port; acceptable locally.
- INFO: no Dockerfile `HEALTHCHECK` (compose-level checks exist). `.github` exists; CI not reviewed.

## 4. Settings isolation per container

Compose uses per-role env anchors:
- Telegram token/chat id: only `worker-alerts`. Good.
- Exchange API keys: only `scanner`. Good. Migrator has no exchange keys. Beat has no DB or exchange secrets.
- `worker-maintenance` receives DB env only (no Telegram/exchange). Good.
- Over-grants (LOW): `scanner` gets full DB credentials (needed for persistence) and keys for MEXC/Bitget in addition to the five V1 exchanges; `worker-alerts` has full DB write credentials (a dedicated limited DB role would be better). One DB superuser role is shared by all services; use per-service roles.
- `.env.example` states keys must be read-only; the code cannot verify this (key permissions are not introspected for V1). CLAUDE.md rule 2 (refuse trading mode if withdrawal permission is detectable) is only relevant for V2.

## 5. Logging of secrets

- `src/nexus/log.py` masks sensitive keys (`api_key`, `secret`, `password`, `passphrase`, `token`, ...) and regex-scrubs signatures, exchange auth headers, and bot-token shapes in all strings.
- Config uses `SecretStr` for DB password, Redis/Celery URLs, bot token, and API credentials; validation errors do not echo input (`config/base.py:29`).
- Residual (LOW): Celery and httpx/ccxt libraries log through stdlib; confirm they pass through the structlog scrubber (Celery task args, `httpx` INFO logs print the full Telegram URL containing the bot token: `https://api.telegram.org/bot<TOKEN>/sendMessage`). Set `httpx`/`httpcore` loggers to WARNING or verify the scrubber is installed on stdlib handlers.
- `Redis`/Celery broker URLs are `SecretStr` but may contain a password once Redis auth is added.

## 6. Telegram / HTTP safety

- `httpx.AsyncClient` with explicit timeout, TLS verification default (no `verify=False`), JSON payload, `parse_mode: HTML`, link preview disabled.
- Exceptions are re-raised without the original message (`from None`), preventing token leakage via the request URL in tracebacks. Good.
- Error text from Telegram truncated to 300 chars. Rate limit (`retry_after`) handled.
- Only outbound calls; no inbound webhook or dashboard yet (V3 not implemented). No chat-id authorization needed until interactive commands exist.
- HTML escaping is mandated by CLAUDE.md; templates were not re-audited here.

## 7. Withdraw / transfer / address / trading calls

Grep over `src/` for `withdraw`, `transfer`, `deposit_address`, `createDepositAddress`, `fetchDepositAddress`, `addresses`, `create_order`, `createOrder`, `cancel_order`, `edit_order`, `sub_account`, `leverage`, `borrow`:
- No call to any such ccxt method. Matches are only domain/persistence names (`transfer_fee`, `transfer_status`, virtual paper rebalance) and the text of comments.
- ccxt methods actually used: `load_markets`, `fetch_trading_fees`, `fetch_trading_fee`, `fetch_currencies`, `fetch_deposit_withdraw_fees` (read-only fee metadata), `fetch_tickers`, `fetch_order_book`, `watch_order_book`.
- Defense in depth: `install_read_only_guard` (`adapters/cex/ccxt_base.py:75`) wraps `client.fetch` and raises `ReadOnlyViolationError` for any non-GET request, except an exact allowlist for public POST (KuCoin `/api/v1/bullet-public`, applied only to unauthenticated clients). Order placement, withdrawals and transfers need POST/PUT/DELETE on all supported venues, so they are blocked even with an over-privileged key.
- Caveats (LOW): the guard covers REST `fetch`; the ccxt.pro WebSocket client uses separate transport (only public `watch_order_book` used). Some venues (e.g. certain Gate/Bitget endpoints) use GET for authenticated state-changing calls rarely; the explicit method allowlist in code (no trading/transfer methods are called) covers this. A unit test asserting the guard is installed on every authenticated client is recommended (not verified here).

## 8. Prioritized actions

1. Bump `protobuf` pin to 5.29.6 and upgrade `certifi`; add `pip-audit` + gitleaks to CI.
2. Verify/force httpx logger level or scrubber so the Telegram URL token never reaches logs.
3. Add Redis auth and hardening flags; pin image digests before Stage 2 (VPS).
4. Use per-service DB roles and Docker secrets (`_FILE`) for production.
5. Remove MEXC/Bitget key passthrough from the scanner env if those exchanges are not enabled, or document it.
