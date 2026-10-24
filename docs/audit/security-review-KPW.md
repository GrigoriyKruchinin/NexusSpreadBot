# Security review — KP-W (IP-binding waiver), commit 699bb75

Date: 2026-10-24 · Reviewer: security · Scope: `git show 699bb75` (key_policy.py, groups.py,
container.py, events.py, formatting.py, scanner/service.py, tests, guide, A6 card, todo.md),
plus `config/file.py` TOML guard and `docker-compose.local.yml` env passthrough.
Basis: user decision 2026-10-24 (STATE.md, CLAUDE.md rule 2): IP whitelist waived for the local
soak only; mandatory on server/VPS and before any trading permission.

## Verdict: **ACCEPT** (security), with one functional finding (F-1) to fix before use

## Checks

| # | Check | Result |
|---|-------|--------|
| 1 | Only `ip_not_restricted` and `attestation_required:ip_binding` are dropped | PASS. `evaluate_waiver` filters exactly `{IP_UNBOUND, ATTEST_KUCOIN_IP}` after parsing + attestation. |
| 2 | Permissions / withdraw / transfer / trade flags stay fatal | PASS. Binance forbidden flags + allow-list, bybit `readOnly`/Wallet, okx/kucoin scope rules untouched; tests cover withdraw, margin, okx `trade`, kucoin `Transfer`. |
| 3 | Gate.io permission attestation stays fatal | PASS (tested, also with empty whitelist). |
| 4 | `request_failed`, `unparseable_response`, `missing_or_invalid_field:*` (incl. `ipRestrict`, `ips`, `ip`, `ip_whitelist`), unknown flags (`permission:unexpected_scope`, extra binance `enable*`) stay fatal | PASS. A missing/mistyped IP field is still a violation, not "unbound" — correct fail-closed. Unknown-venue `no_key_policy_for_venue` path unchanged. |
| 5 | Default off | PASS. `ip_binding_waived: bool = False`; without it the return is `(rules, False)` = old behaviour. |
| 6 | Strict boolean parsing | PASS (acceptable). Pydantic bool: `"maybe"` refused (tested). Note: pydantic also accepts `1/yes/on/t/y`; same as the existing attestation flags, explicit truthy words only — no risk. |
| 7 | Cannot be set via TOML | PASS. `_DENY_PREFIX = ("KEY_POLICY_",)` refuses the whole table; test case added. Not in `TOML_ALLOWED`. |
| 8 | Log / Telegram contain venue names only | PASS. `key_policy_ip_binding_waived` logs `venues=[names]`; Telegram line joins `esc(venue)` of internal adapter keys; no IPs, key, uid or label. Raw payload still `del`-ed before logging. |
| 9 | Wildcard IP (`*`, `0.0.0.0/0`, `::/0`, prefix <= /8) treated as unbound and waived | ACCEPTABLE. A wildcard whitelist gives the same exposure as no whitelist, so waiving one and not the other would be inconsistent, not safer. The venue is still reported in the warning + Telegram line, so the user sees it. A key with a real, narrow whitelist passes normally and is not listed. |
| 10 | Server guard deferred to A5d | ACCEPTABLE for a local soak. Keys are read-only and withdraw-disabled (enforced by the remaining rules), so the residual risk of an unbound key leaking is read access to balances/history — no funds movement. Tracked in `todo.md` under A5d; A5d is a precondition for any VPS. Must become a blocking item before deploy / before any trading permission (hard rule 2). |
| 11 | Secrets in diff | PASS. No keys, IPs, tokens; test fixtures are synthetic. |

## Findings

- **F-1 (functional, medium; blocks the soak use-case, not a security hole):** `docker-compose.local.yml`
  scanner env (`x-scanner-env`, lines 47-48) passes only `KEY_POLICY_KUCOIN_IP_ATTESTED` and
  `KEY_POLICY_GATEIO_PERMISSIONS_ATTESTED`. Containers never read `.env` (`NEXUS_RUNTIME=container`),
  so `KEY_POLICY_IP_BINDING_WAIVED=true` written to `.env` as the guide says has **no effect** in
  `make up-local`: the scanner stays parked (fail closed). Fix (devops/backend-lead): add
  `KEY_POLICY_IP_BINDING_WAIVED: ${KEY_POLICY_IP_BINDING_WAIVED:-}` to the scanner env only, and
  `KEY_POLICY_IP_BINDING_WAIVED=false` to `.env.example` with a "local only" comment. No re-review
  needed beyond a diff glance if limited to these two lines.
- **F-2 (low):** A5d guard must fail closed (refuse start when the waiver is set on a server deployment),
  not merely warn; and the future production compose file must not pass this variable at all.
- **F-3 (info):** the Telegram line says "разрешено для локального запуска" — keep it; it is the only
  in-band reminder until the A5d guard exists.
