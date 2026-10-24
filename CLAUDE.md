# CLAUDE.md — Nexus Spread Scanner

Async Python CEX (and planned DEX) spread scanner: net spread after fees, orderbook slippage and
transfer cost; Telegram alerts; PostgreSQL analytics. Docker-first. Details live in `docs/`.

## Language policy
- English: code, comments, docstrings, commits, this file, agent/skill files, ADRs, audits.
- Russian: all talk to the user (questions, summaries, CLI guides) and `docs/guides/*`.
- Plain language for the user: explain terms briefly on first use.

## Where we are
Trajectory **M** (MVP/analysis with GO/NO-GO fork). Current state: `docs/pipeline/STATE.md`.
Roadmap/checklist: `todo.md`. Audit baseline: `docs/audit/`. Intake answers: `docs/pipeline/intake.md`.
GO criterion: net return >= **2 % / month** on allocated capital (~$10-20k USDT), out-of-sample,
after all costs, plus no blocking legal verdict (`docs/legal/`).

## Hard rules (never break)
1. **No withdrawal/transfer/address-management code**, no real orders until GO and explicit user
   confirmation (ADR 0001). Reading transfer fee/status metadata is allowed.
2. Exchange API keys: withdrawals disabled, IP whitelist; trading permission only after GO.
3. Agents have no live keys and no production access. Stage 1 = public read-only data.
4. Secrets never enter code, logs, Telegram, git, or chat. Never read `.env`.
5. **Integration tests run only against a dedicated test DB** (`nexus_test`); never against the live
   `nexus` DB (it was wiped once, see risk R-01). No `docker compose down -v`, no `system prune`.
6. No force-push, no `--no-verify`, no history rewrite, no push to `main` without user consent.
7. Ask the user before: prod changes, destructive data ops, major dependency upgrades, deleting
   tests/CI, anything touching money.

## Agents (`.claude/agents/`, only `orchestrator` calls others)
orchestrator (opus) · analyzer · project-manager · scribe · architect · tech-lead · backend-lead ·
tester · security · devops · quant-analyst · crypto-specialist · observability-engineer · lawyer.
Added: creative-ceo (Phase 5), risk-manager added at U2 (2026-10-23). DEX: seam only, dex-engineer deferred until after GO (ADR 0006).
Critics (tech-lead, security, analyzer, lawyer) never edit code.

## Commands (verified in audit, see docs/audit/04)
```bash
uv sync                     # install
make lint                   # ruff format --check + ruff check
make format                 # ruff format + fix
make typecheck              # mypy --strict
make test                   # unit tests (-m "not integration")
make test-cov               # unit tests + coverage
make check                  # lint + typecheck + test (before every commit)
make up-local / down-local  # docker compose local stack (ask first)
make test-integration       # ONLY with test DB (ask first)
```
Single test: `uv run pytest tests/unit/<path>::<name> -q`.

## Quality ratchet (baseline from docs/audit/05)
481 unit tests green, branch coverage 89 %, ruff 0, mypy --strict 0. Never get worse.

## Workflow
"continue" -> read CLAUDE.md, STATE.md, todo.md, check `git log` vs STATE.md, take the first
unchecked item. Per task: card -> implement -> `make check` not worse than baseline -> tick
todo.md -> commit (Conventional Commits, English, one logical unit, todo tick in same commit) ->
push the working branch. Stage end: tech-lead review (max 3 fix rounds) -> tester -> security ->
delta audit -> repo hygiene (skill `repo-hygiene`: delete stale agent/doc files, update
the rest) -> summary to user. Conventions: `docs/conventions.md`.

## Participation points (only places to stop and ask)
U1 team (done) · U2 roadmap (after vision+architecture; DEX/risk-manager decision) · UF GO/NO-GO ·
U3 keys/accounts via guide files · U4 risky actions · U5 launch/legal. Subagents return `NEEDS_USER`.

## When compacting, preserve
Current stage/task from STATE.md, hard rules above, the commands, open user questions, blockers.
