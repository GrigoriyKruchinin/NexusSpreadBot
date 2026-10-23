# Intake (U0) — Nexus adoption

Date: 2026-10-23. Source: `nexus-adoption-instructions.md` (Appendix P) + user answers.

| Item | Answer |
|---|---|
| A. Stage | MVP / analysis (hypothesis "stable profit on spread" still being tested). Audit confirms or corrects. |
| B. GO / NO-GO fork protocol | Yes -> trajectory M |
| GO threshold | Net return >= 2 % / month on allocated capital (orientation $10-20k USDT), out-of-sample, after all costs |
| DEX leg | In scope from the start (add `dex-engineer`; to be confirmed in roadmap U2) |
| Existing AI rules (CLAUDE.md, agents, skills) | Fully replaced by the new pipeline across the whole project. No legacy copy kept (originals remain in git history at tag `pre-agents-baseline`). |
| API keys | Withdrawal permission is always disabled on exchange keys (funds cannot leave via API). Trading via API is allowed, but only after GO and explicit user confirmation. |
| Current phase | Testing / analysis, no real money. Funding, order-size limits and trading rules are given to the user as guides only after the opportunity analysis. |
| GUI | None; analytical dashboards only (no `frontend-lead` / `designer`) |
| Docker | Remains the base of running (local and server) in any outcome |
| Budget | No paid services without approval; dashboards open-source only |
| Autonomy | Ask only at participation points |
| Live access | Agents get no exchange keys, no production access; Stage 1 is public read-only data |

## Defaults assumed (not asked)
- Solo repository, branch `main`, Conventional Commits; adoption work in `chore/agent-pipeline-adoption`.
- Depth of intervention: audit, fixes, refactor, math/performance; new features only after U2.
- Jurisdiction: Argentina (per Appendix P5).
