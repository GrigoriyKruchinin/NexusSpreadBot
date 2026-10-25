# T12 - Repo hygiene: obsolete docs, agents, guides; CLAUDE.md proposal

- id: T12
- stage: S1-tool
- owner: project-manager
- complexity: medium (many files, judgement per file; skill repo-hygiene)
- size: M
- depends_on: T1b, T10
- status: todo

## Goal
Delete or archive everything tied to soak/GO/paper/HT1; leave a consistent doc set; hand CLAUDE.md changes to the user.

## Context docs
skill `repo-hygiene`, `docs/handoffs/project-manager-to-user-claude-md-2026-10-25.md`

## Scope
1. Delete (candidates, confirm by link check): `docs/guides/soak-fresh-stack.md`, `soak-auto-recovery.md`, `gate-0-how-to-continue.md` (if obsolete), `docs/tasks/m3/S1-fresh-stack-runbook.md`, `docs/tasks/m2/B15-*`, `B16-*` (cancelled), `docs/tasks/HT1-*`, `docs/quant/hedged-transfer-spec.md` (keep hedge comparison as evidence), `scripts/host_watchdog.sh` if not kept as advanced, handoffs tied to HT1/D01b
2. Keep as evidence: `docs/reports/go-no-go.md`, `docs/quant/hedge-method-comparison.md`, `docs/legal/`, ADRs (mark superseded)
3. Agents: review `.claude/agents/` - candidates to retire or slim: quant-analyst (GO math), risk-manager, creative-ceo, lawyer (keep for ToS), observability-engineer (dashboards as code cancelled); decision by user via NEEDS_USER
4. Update STATE.md, todo.md, docs index, `docs/product/vision.md` banner
5. CLAUDE.md is user-owned: proposed text in the handoff (see that file), not edited

## Acceptance criteria
- Hygiene list (deleted / updated) in the card; no dangling links (link check); STATE.md current
- Handoff with CLAUDE.md proposal exists and is delivered to the user by the orchestrator

## Out of scope
Editing CLAUDE.md.

## Files likely touched
docs/, .claude/, scripts/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
