# Security review — A6 key-policy startup check (S-08 / G4)

- Reviewer: security · Date: 2026-10-23
- Scope: commit `6766bfd` (`feat(security): refuse to start on unsafe API key permissions (A6)`) plus
  uncommitted working-tree passthrough in `docker-compose.local.yml` / `.env.example`.
- Read: `src/nexus/adapters/key_policy.py`, `_key_info_request` in the five core adapters,
  `ccxt_base.py` (`fetch_key_info`, `_call`, `install_read_only_guard`, client construction),
  `container.py`, `cli.py`, `config/groups.py`, `config/roles.py`, `domain/errors.py`,
  `tests/unit/adapters/test_key_policy.py`, card A6, `target.md` §10.4,
  `docs/reports/exchange-key-permissions.md`, S-08. `.env` not read.
- Ran: `pytest tests/unit/adapters/test_key_policy.py` (100 passed), `make check` (green, 610 unit
  tests). Verified HTTP verbs in installed ccxt abstract API files.

## Verdict: **ACCEPT** (no blocking findings; follow-ups F1-F6 below, none blocks merge; F1 must be done before U3)

## Checklist

| Check | Result |
|---|---|
| Only GET read-only endpoints | OK. ccxt entries: binance `sapi GET account/apiRestrictions`, bybit `private GET v5/user/query-api`, okx `private GET account/config`, kucoin `private GET user/api-key`, gate `private/account GET detail`. No trade/transfer/withdraw endpoint referenced, not even as probe (AC7). Test patches `Exchange.fetch` below the guard and asserts exactly one GET per venue. |
| GET-only guard on every authenticated client | OK. Only `_rest` is built with credentials; WS uses `authenticated=False`; binance fallback is the public httpx source. Test iterates all registered venues (incl. mexc/bitget) and asserts POST/PUT/DELETE/PATCH raise on the client used by `fetch_key_info`. |
| Fail closed | OK. Non-mapping / error envelope -> `unparseable_response`; every required field type-checked (bool for binance, int 0/1 not bool for bybit `readOnly`, str for okx/kucoin); parser exception -> `unparseable_response`; `ExchangeError` on request -> `request_failed`; all venues evaluated, then one `KeyPolicyViolationError`; CLI exit 3; check runs before DB/engine work and adapters are closed. Key set without secret -> ccxt auth error -> refused. |
| IP binding refused where readable | OK. binance `ipRestrict=false`, bybit `ips` empty / `*` / `0.0.0.0(/0)` / `::/0` (list or string), okx `ip==""`, gateio `ip_whitelist` empty or wildcard. |
| No raw response / secret in logs or exceptions | OK. Only rule names + booleans logged; request failure logs class name only; `KeyPolicyViolationError` text = venue + rule names. Test captures logs with fake apiKey/uid/label/IP and asserts absence. |
| Attestation cannot bypass readable checks | OK. Attestation is *appended* to parser output, never replaces it; only kucoin IP and gateio permissions have flags; binance/bybit/okx have none. kucoin permissions and gateio IP are still parsed. Flags are non-secret bools, default false; empty env -> default (env_ignore_empty). |
| mexc/bitget keyed = refused | OK. No entry in `KEY_POLICIES` -> `no_key_policy_for_venue` (short-circuits before any call). Unit-tested with a fake adapter. |
| Public/no-key mode | OK, skipped with an info log, no call (AC8). |
| No network in tests | OK. Fixtures + fakes; transport patched at `ccxt Exchange.fetch`; guard test target is `https://example.invalid` and the guard raises before any I/O. |

## Follow-ups (non-blocking)

- **F1 (before U3, devops):** `KEY_POLICY_*` passthrough in `docker-compose.local.yml` and
  `.env.example` is still uncommitted. Without it a keyed kucoin/gateio in Docker is always
  refused (safe, but blocks U3). Commit it.
- **F2 (backend-lead, low):** `verify_key_policies` catches only `ExchangeError`. A
  `ReadOnlyViolationError` / `ConfigurationError` from `fetch_key_info` (e.g. a future override
  removed) escapes as a traceback (exit 1, still closed, but no venue/rule summary and other venues
  not reported). Catch `NexusError` (class name only) -> `request_failed`.
- **F3 (backend-lead, low):** rule names echo payload strings: kucoin unknown scopes
  (`permission:<scope>`) and bybit `SubMemberTransfer*`. Not secret, but untrusted text in logs.
  Restrict to `[A-Za-z0-9_]{1,40}` or map unknowns to `permission:unexpected_scope`.
- **F4 (devops, low):** scanner runs with `restart: unless-stopped`; a refused key gives a restart
  loop (Docker back-off) that re-calls the introspection endpoints and floods logs without a clear
  signal. Consider `restart: on-failure` with a max count for the scanner, or idle-and-unhealthy on
  exit code 3; optionally a Telegram "key policy refused" event (rule names only).
- **F5 (scribe, low):** guide §7 checklist still says to create keys for MEXC and Bitget; a keyed
  mexc/bitget is now refused at startup. Drop them from that line (or mark "only for extension runs").
- **F6 (tech-lead nit):** `BybitAdapter.key_info_method` ClassVar is unused dead code.

## Residual risks (accepted, confirm at U3)
- binance requires every listed flag incl. `enableFixApiTrade` / `enablePortfolioMarginTrading`;
  older keys may omit them -> refusal (intended fail-closed; adjust only after a real-key check).
- bybit: missing `permissions.Wallet` is treated as empty; acceptable because `readOnly` is
  authoritative (report [I]); confirm on a real key.
- kucoin IP and gateio scopes rest on user attestation (documented limitation of the venue APIs).
