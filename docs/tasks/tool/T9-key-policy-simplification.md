# T9 - Simplify KEY_POLICY_* for third-party users

- id: T9
- stage: S1-tool
- owner: security
- complexity: medium (security semantics must not weaken; mostly deletion and defaults)
- size: M
- depends_on: T7
- status: done (security review ACCEPT pending at stage end)

## Goal
Third-party users face no attestation flags; read-only is verified by the API where possible and otherwise documented.

## Context docs
A6 card `docs/tasks/track0/A6-key-policy-startup-check.md`, `adapters/key_policy.py`, `.env.example`, ADR 0001

## Scope
1. Remove `KEY_POLICY_*_ATTESTED` and `IP_BINDING_WAIVED` human attestations from the default path. Replace with automated checks (T7): withdrawals permission off, trading permission off where the venue returns permissions (binance, okx, kucoin, bybit, gateio - verify per adapter)
2. Where a venue cannot report permissions: warn once (`cannot verify read-only; make sure the key has only Read`) and continue; this is a documented residual risk, not a refusal
3. IP whitelist: recommended in the guide (strongly), not enforced; the owner's own deployment can still set a stricter optional flag `KEY_POLICY_STRICT=true` (keeps old behaviour) - decide with security
4. Keep the guard that refuses keys with withdraw enabled; no trading permission ever accepted (hard rule 1-2 of CLAUDE.md remain, wording in T12 handoff)

## Acceptance criteria
- security review verdict ACCEPT recorded in `docs/audit/`
- Tests: withdraw-enabled key -> venue public mode + warning; unknown-permission venue -> warning only; old flags in `.env` ignored with a deprecation notice (not an error)
- `.env.example` and docs updated

## Out of scope
Server/VPS deployment policy.

## Files likely touched
src/nexus/adapters/key_policy.py, src/nexus/config, tests/, docs/guides/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).

## Progress (2026-10-25)
- Attestation flags and `KEY_POLICY_IP_BINDING_WAIVED` removed; only `KEY_POLICY_STRICT` (env-only, TOML denied) remains. Old vars are ignored; `nexus check` shows a deprecation warning.
- One policy function `assess_venue_key` (`adapters/key_policy.py`) serves `nexus check` and the scanner.
- Default: rejected/unverifiable-fatal key -> `container.enforce_key_policy` closes the adapter and rebuilds it from empty credentials (public mode); warning log + `ScannerStarted.public_fallback_venues` Telegram line. IP binding and KuCoin IP / Gate.io scopes (API cannot show them) are warnings.
- Strict: old fail-closed (exit 3), IP binding required, unverifiable venues refused (no attestation exists any more).
- Tests: credential-less client asserted (`test_rejected_key_is_never_used_...`). Open: CLAUDE.md rule 2 still names the IP waiver flag (user-owned file); A5d guard text in todo adjusted.
