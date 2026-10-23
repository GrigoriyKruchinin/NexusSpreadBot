# Intake (U0) — Nexus adoption

Date: 2026-10-23. Source: `nexus-adoption-instructions.md` (Appendix P) + user answers.

| Item | Answer |
|---|---|
| A. Stage | MVP / analysis (hypothesis "stable profit on spread" still being tested). Audit confirms or corrects. |
| B. GO / NO-GO fork protocol | Yes -> trajectory M |
| GO threshold | Net return >= 2 % / month on allocated capital (orientation $10-20k USDT), out-of-sample, after all costs |
| DEX leg | In scope from the start (add `dex-engineer`; to be confirmed in roadmap U2) |
| Existing AI rules (CLAUDE.md, agents, skills) | Replace with the new pipeline; originals kept in `docs/legacy/`. User's hard safety rules are migrated verbatim ("user rule (migrated)"). |
| GUI | None; analytical dashboards only (no `frontend-lead` / `designer`) |
| Docker | Remains the base of running (local and server) in any outcome |
| Budget | No paid services without approval; dashboards open-source only |
| Autonomy | Ask only at participation points |
| Live access | Agents get no exchange keys, no production access; Stage 1 is public read-only data |

## Defaults assumed (not asked)
- Solo repository, branch `main`, Conventional Commits; adoption work in `chore/agent-pipeline-adoption`.
- Depth of intervention: audit, fixes, refactor, math/performance; new features only after U2.
- Jurisdiction: Argentina (per Appendix P5).
