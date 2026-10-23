# 0007 — Up to 5 iterations to find a profitable spread approach

Date: 2026-10-23. Status: accepted (user decision).

**Context.** The project goal is to earn on spreads, not to validate one hypothesis. The first
vision draft allowed one Rework iteration only.

**Decision.** If the current approach is not viable, vision, analyzer, quant-analyst and
crypto-specialist propose other approaches and test them, up to 5 iterations. Success test and
time box are fixed before each run; results are reports (`docs/reports/iterations/`) and git
tags, not separate code copies. GO at any iteration leads to Stage 2; no GO after 5 means NO-GO
and the portfolio pivot. Hard rules still apply (no DEX build, no money-touching code, user
confirms at each UF point).

**Alternatives.** One Rework only (rejected by user: too narrow). Separate code per iteration
(rejected: bloats the codebase).

**Consequences.** M3/M4 plans must budget for repeated analysis cycles; quant tooling should
make runs reproducible by parameter set.
