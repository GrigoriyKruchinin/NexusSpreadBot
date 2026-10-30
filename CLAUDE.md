# CLAUDE.md — Nexus Spread Scanner

Async Python CEX spread scanner: net spread after fees, orderbook slippage and transfer cost;
Telegram alerts; PostgreSQL analytics. Self-hosted, read-only, Apache-2.0. Docker-first.

## Language policy
- English: code, comments, docstrings, commits, this file, agent/skill files, ADRs, audits, README.
- Russian: all talk to the user (questions, summaries, CLI guides) and `docs/guides/*`.
- Plain language for the user: explain terms briefly on first use.

## Where we are
Decision: NO-GO for trading. Product = self-hosted spread-alert tool (ADR 0010). Stage S1-tool done;
repo prepared for public GitHub. Current state: `docs/pipeline/STATE.md`; roadmap `todo.md`.

## Hard rules (never break)
1. **No withdrawal/transfer/address-management code and no order placement** (ADR 0001). Reading
   transfer fee/status metadata is allowed.
2. Exchange API keys: read-only, withdrawals disabled, no trading permission. IP whitelist is
   mandatory on any server/VPS deployment (`KEY_POLICY_STRICT`).
3. Agents have no live keys and no production access.
4. Secrets never enter code, logs, Telegram, git, or chat. Never read `.env`, and never run commands that
   expand it (`docker compose config`, `docker inspect`, `exec ... env`); denied in `.claude/settings.json`.
5. **Integration tests run only against the dedicated test DB** (`nexus_test`); never against the live
   `nexus` DB. No `docker compose down -v`, no `system prune`.
6. No force-push, no `--no-verify`, no history rewrite, no push to `main` without user consent.
7. Ask the user before: prod changes, destructive data ops, major dependency upgrades, deleting
   tests/CI, release/tag, anything touching money.
8. Legal limits: alerts go only to the owner's PRIVATE channel/chat; no public channels, no monetisation.

## Agents (`.claude/agents/`, only `orchestrator` calls others)
orchestrator (opus) · analyzer · project-manager · scribe · architect · tech-lead · backend-lead ·
tester · security · devops · crypto-specialist · lawyer. Critics (tech-lead, security, analyzer,
lawyer) never edit code.

## Commands
```bash
uv sync                     # install
make lint | format | typecheck | test | test-cov
make check                  # lint + typecheck + test (before every commit)
make up / down              # one-command start (auto migrations) / stop; ask first
uv run nexus check          # startup validation
make test-integration       # ONLY with test DB (ask first)
```
Single test: `uv run pytest tests/unit/<path>::<name> -q`.

## Quality ratchet (baseline docs/audit/delta-03-S1-tool.md)
1066 unit tests green (1085 minus the 19 deleted host-watchdog tests), branch coverage 92.08 % (floor 89 %), ruff 0, mypy --strict 0. Never get worse
(test count may drop only by deliberately deleted tests).

## Workflow
"continue" -> read CLAUDE.md, STATE.md, todo.md, check `git log` vs STATE.md, take the first
unchecked item. Per task: card -> implement -> `make check` not worse than baseline -> tick
todo.md -> commit (Conventional Commits, English, one logical unit) -> push the working branch.
Stage end: tech-lead review (max 3 fix rounds) -> tester -> security -> delta audit -> repo hygiene
(skill `repo-hygiene`) -> summary to user.
CLAUDE.md and `.claude/` (agents, skills, settings) are tracked in git. Working docs (todo.md,
docs/pipeline|tasks|audit|handoffs|legal|reports ...) are local only and never committed
(see "Internal working docs" in `.gitignore`).

## Participation points
U1 team (done) · U3 keys/accounts via guide files · U4 risky actions (destructive ops, prod,
release/tag). Subagents return `NEEDS_USER`.

## When compacting, preserve
Current stage/task from STATE.md, hard rules, the commands, open user questions, blockers.
