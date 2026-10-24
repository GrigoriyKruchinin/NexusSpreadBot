# A6 — Key policy startup check (S-08, G4)

- id: A6 (security review "Re-check 2026-10-23", gap G4)
- stage: Track 0 (base)
- owner: backend-lead; consult crypto-specialist (endpoints, [U] items)
- reviewers: security, tech-lead
- complexity: high (fail-closed security gate on every authenticated client; five venues with different response shapes)
- depends_on: B1 (done). Blocks U3: no real keys before this is merged.
- status: done (6766bfd + ee38592; TL round 2 + security ACCEPT). Follow-ups F-1..F-5 in todo. Code: `src/nexus/adapters/key_policy.py`, tests: `tests/unit/adapters/test_key_policy.py`

## Goal
At scanner startup a per-venue `KeyPolicyCheck` refuses to start if the configured key can trade, withdraw or transfer, or is not IP-bound.

## Context docs
`docs/reports/exchange-key-permissions.md` (endpoints, refuse rules, [U] items),
`docs/audit/security-review-architecture.md` (S-08, G4), `docs/architecture/target.md` §10.4,
`docs/decisions/0001-no-withdrawal-in-code.md` (no withdrawal/trading code), `src/nexus/config/groups.py` (`CORE_EXCHANGES`).

## Acceptance criteria
1. One `KeyPolicyCheck` per core venue (binance `GET /sapi/v1/account/apiRestrictions`, bybit
   `GET /v5/user/query-api`, okx `GET /api/v5/account/config`, kucoin `GET /api/v1/user/api-key`,
   gateio `GET /account/detail`), signed GET only, one call per venue, using the refuse rules in the report.
2. Startup refuses (non-zero exit, clear reason: venue + rule name) on: any trade/withdraw/transfer
   permission; unparseable response; missing required field; no IP binding where readable
   (binance `ipRestrict`, bybit `ips` empty/wildcard, okx `ip` empty, gateio `ip_whitelist` empty).
3. Logs contain booleans/rule names only; never the response body, key, uid, label (unit test with
   captured log output on a fake response that contains such fields).
4. Unit tests per venue with fixture responses: pass case, each refuse case, malformed JSON, missing field.
5. Test proves the GET-only guard is installed on every authenticated client (iterate over all
   constructed venue clients, including the one used by the check); a non-GET call raises.
6. kucoin (IP binding) and gateio (permissions) are not auto-checked: the check reports "attestation required" and the U3 guide gets a checkbox step for each; startup requires the attestation flag in settings (non-secret) for these venues.
7. The check never calls a trade/transfer/withdraw endpoint, not even with invalid params.
8. Disabled/no-key mode (public data only) skips the check without error.
9. `target.md` §10.4 gets the fail-closed, booleans-only, IP-refuse and attestation lines (docs-only edit in same commit).
10. `make check` not worse than baseline; no secrets in diff.

## Addendum KP-W (2026-10-24): IP-binding waiver for local runs
User decision (CLAUDE.md rule 2, STATE.md "User decisions"): keys for the local soak have no IP whitelist.
`KEY_POLICY_IP_BINDING_WAIVED=true` (env-only, strict bool, default false, refused from TOML by the
`KEY_POLICY_` deny-prefix) drops only `ip_not_restricted` and `attestation_required:ip_binding`; all other
rules stay fatal. `verify_key_policies` returns the sorted IP-unbound venue names, logs
`key_policy_ip_binding_waived` (names only) and the scanner puts one fixed line into the Telegram start
message. There is no environment/deploy-name setting in the code, so the "refuse on server/prod" guard
does not exist yet: **A5d must add it** (fail closed when the waiver is set on a VPS/prod deployment);
tracked in `todo.md` under A5d. Until then the guard is the user's own discipline plus guide wording.

## Out of scope
Real-key verification of [U] items (done at U3 with the user), gateio `main_keys` probe, runtime
re-checks (startup only), trading code, transfer-metadata fetching.

## Files likely touched
`src/nexus/exchanges/` (new `key_policy.py`), scanner startup wiring, `src/nexus/config/`,
`tests/unit/exchanges/`, `docs/architecture/target.md`, `docs/guides/` (U3 attestation steps), `todo.md`.

## Risks
Exchange changes a field name -> scanner refuses to start (intended, fail closed). Bybit `readOnly`
vs `permissions` ambiguity: `readOnly` is authoritative, confirm at U3.
