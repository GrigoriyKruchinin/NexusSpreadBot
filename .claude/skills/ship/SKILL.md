---
name: ship
description: Final step of the delivery loop - re-verify green state, ensure todo.md is ticked, commit with a Conventional Commits message, and push to origin main. Use after an item is implemented and verified. Never ships red code.
---

# ship

Argument (optional): short description of the unit of work being shipped.

1. **Re-verify** (all must pass; on any failure STOP and report, do not commit):
   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src tests
   uv run pytest -q -m "not integration"
   ```
   Skip a tool only if the project skeleton for it does not exist yet (e.g. docs-only commits);
   say so in the report.

2. **todo.md:** confirm the completed item(s) are ticked `[x]`. If an item is marked `(R)`,
   confirm `/audit-risks` returned `SAFE TO PROCEED` in this session; otherwise run it first.

3. **Stage & review:**
   ```bash
   git status --short
   git add -A
   git diff --cached --stat
   git diff --cached --name-only | grep -E '(^|/)\.env($|\.)|secret|\.pem$|\.key$' && echo "STOP"
   ```
   If any secret-like file (other than `.env.example`) is staged, unstage it, fix `.gitignore`,
   and report. Read the staged diff for hard-coded keys/tokens.

4. **Commit** (English, Conventional Commits; scope = module):
   ```
   <type>(<scope>): <imperative summary ≤ 72 chars>

   <what and why, 1–5 lines; reference todo.md section, e.g. "todo: 1.5">

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   ```
   Types: feat, fix, refactor, test, docs, chore, build, ci, perf. Never use `--no-verify`.

5. **Push:** `git push origin main`. Never `--force`. If the push is rejected, STOP and report
   (do not rebase/reset pushed history without the user).

6. Report to the user **in Russian**, one or two lines: commit hash + subject, push result.
