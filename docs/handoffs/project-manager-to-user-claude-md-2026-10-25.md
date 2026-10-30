# Proposed CLAUDE.md changes after NO-GO (for the user; CLAUDE.md is user-owned, not edited by agents)

Why: product is now a self-hosted spread-alert tool (stage S1-tool, `todo.md`). Apply after T1a/T1b/T12 land.

1. Header: "Async Python CEX spread scanner that posts net-spread alerts to the user's own Telegram chat/channel and stores
   analytics in PostgreSQL. Self-hosted, Docker-first, no trading."
2. "Where we are": replace trajectory M / GO criterion with: "Decision: NO-GO for trading (docs/reports/go-no-go.md).
   Current stage S1-tool (todo.md). Product = self-hosted alert tool (ADR 0010)."
3. Hard rule 2: keys read-only, withdrawals disabled (checked at startup where the venue API reports permissions);
   remove the IP-whitelist waiver text and `KEY_POLICY_IP_BINDING_WAIVED` after T9; IP binding stays a recommendation.
4. Hard rule 1: keep (no trading/withdrawal code, ever; ADR 0001 permanent, no "until GO").
5. Hard rule 7: drop "anything touching money" wording to "any real order or key with trading permission is forbidden".
6. Agents: remove creative-ceo, quant-analyst/risk-manager from the active list or mark "on demand" (user decides in T12).
7. Commands: remove `make go-report` mentions if any; add `make up`, `make down`, `nexus check` after T8/T7.
8. Quality ratchet: replace numbers with the new baseline recorded in T11 (1041 tests / 91.5 % / floor 89 % are pre-removal).
9. Participation points: remove UF GO/NO-GO and U5 launch/legal; keep U4 (destructive ops, prod) and add "release/tag".
10. Language policy: add "Telegram alerts and startup messages: en and ru via `[alert] language`".

## Update 2026-10-30 (after S1-tool, delta audit 03, T12 hygiene) - exact text to apply

Items 1-10 above still hold. Concrete replacements, current facts:

A. Agents (lines 33-35). Retired in T12 (files deleted): quant-analyst, risk-manager, creative-ceo, observability-engineer.
   Replace with:
   `orchestrator (opus) · analyzer · project-manager · scribe · architect · tech-lead · backend-lead · tester · security · devops · crypto-specialist · lawyer.`
   Delete the line "Added: creative-ceo ... DEX: seam only ..." (DEX seam is moot after NO-GO, ADR 0010).
B. Quality ratchet: `1085 unit tests green, branch coverage 92.08 % (floor 89 %), ruff 0, mypy --strict 0. Never get worse.` (baseline `docs/audit/delta-03-S1-tool.md` s.6).
C. Commands: remove `make up-local / down-local` (removed in T8). Use `make up` / `make down` (one-command start, auto migrations) and `uv run nexus check` (startup validation). Keep `make test-integration` (test DB only).
D. "Where we are": replace the trajectory-M paragraph and GO criterion with:
   "Decision: NO-GO for trading (`docs/reports/go-no-go.md`). Stage S1-tool done pending user manual checks (`docs/guides/s1-tool-e2e-check.md`). Product = self-hosted spread-alert tool (ADR 0010, Apache-2.0). Current state: `docs/pipeline/STATE.md`; roadmap `todo.md`."
E. Hard rule 2: drop the IP-whitelist waiver / `KEY_POLICY_IP_BINDING_WAIVED` text (T9 replaced it by `KEY_POLICY_STRICT`); keep "mandatory on any VPS deployment" as `KEY_POLICY_STRICT` guard (todo A5d).
F. Participation points: `U1 team (done) · U4 risky actions (destructive ops, prod, release/tag) · U3 keys/accounts via guide files`. Remove UF, U2, U5.
