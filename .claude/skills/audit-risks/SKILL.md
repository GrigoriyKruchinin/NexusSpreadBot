---
name: audit-risks
description: Trading & security risk audit of the current changes (or a given path) using the risk-critic agent. Use after changes to spread/PnL math, fees, execution, risk limits, adapters, settings/secrets, Docker or CI.
---

# audit-risks

Argument (optional): a path or git ref range. Default: uncommitted changes + last commit.

1. Collect scope:
   ```bash
   git status --short
   git diff HEAD --stat
   ```
   If an argument was given, scope to it instead.

2. Delegate to the `risk-critic` agent with the list of files in scope and this instruction:
   "Audit these files against your full checklist (spread/PnL correctness, execution risk,
   security). Return ranked findings with path:line evidence and a final verdict."

3. Independently verify each CRITICAL/HIGH finding by reading the cited code. Drop findings that
   do not hold up; mark the rest as confirmed.

4. Report to the user **in Russian**: verdict (`SAFE TO PROCEED` / `BLOCKED`), confirmed findings
   ranked by severity with `path:line`, and proposed fixes. Do not apply fixes without the user's
   go-ahead if they change trading behavior or thresholds.
