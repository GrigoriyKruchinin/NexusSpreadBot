# A6 — Key policy startup check (S-08, G4)

- id: A6 (security review "Re-check 2026-10-23", gap G4)
- stage: Track 0 (base)
- owner: backend-lead; consult crypto-specialist (endpoints, [U] items)
- reviewers: security, tech-lead
- complexity: high (fail-closed security gate on every authenticated client; five venues with different response shapes)
- depends_on: B1 (done). Blocks U3: no real keys before this is merged.
- status: review (round 1 fixes applied: tech-lead 1-4, 6, 8, 9, 10, 12; security F2-F6); awaiting re-review. Code: `src/nexus/adapters/key_policy.py`, tests: `tests/unit/adapters/test_key_policy.py`

## Goal
At scanner startup a per-venue `KeyPolicyCheck` refuses to start if the configured key can trade, withdraw or transfer, or is not IP-bound.

## Context docs
`docs/reports/exchange-key-permissions.md` (endpoints, refuse rules, [U] items),
`docs/audit/security-review-architecture.md` (S-08, G4), `docs/architecture/target.md` §10.4,
`docs/adr/0001*` (no withdrawal/trading code), `src/nexus/config/groups.py` (`CORE_EXCHANGES`).

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

## Out of scope
Real-key verification of [U] items (done at U3 with the user), gateio `main_keys` probe, runtime
re-checks (startup only), trading code, transfer-metadata fetching.

## Files likely touched
`src/nexus/exchanges/` (new `key_policy.py`), scanner startup wiring, `src/nexus/config/`,
`tests/unit/exchanges/`, `docs/architecture/target.md`, `docs/guides/` (U3 attestation steps), `todo.md`.

## Risks
Exchange changes a field name -> scanner refuses to start (intended, fail closed). Bybit `readOnly`
vs `permissions` ambiguity: `readOnly` is authoritative, confirm at U3.
