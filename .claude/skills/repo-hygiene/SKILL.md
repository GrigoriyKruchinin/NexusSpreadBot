---
name: repo-hygiene
description: Stage-end audit of agent/doc files - delete stale ones, update the ones that stay.
---

# repo-hygiene

Runs at every stage end, after the delta audit (user decision 2026-10-23). Goal: files do not pile up,
what stays matches reality.

## Scope
`CLAUDE.md`, `.claude/agents/*`, `.claude/skills/*`, `.claude/settings.json`, `docs/**`, `todo.md`.

## Who
- `analyzer` writes the list `docs/audit/hygiene-<stage>.md`: each file -> KEEP / UPDATE (what is wrong) /
  DELETE (why; what replaces it). Checks: references to removed code, commands, agents or files; facts that
  contradict STATE.md/code; duplicates; one-off files whose content already lives elsewhere.
- `scribe` applies UPDATE items and fixes links that pointed to files marked DELETE (scribe has no shell).
- `orchestrator` runs `git rm` for DELETE items and makes one commit `chore(docs): stage <X> hygiene`.
- Agent/skill files: update by `orchestrator` or `scribe`; a skill no agent references and no workflow uses -> DELETE.

## Rules (what goes)
- `docs/handoffs/*` of accepted tasks: DELETE (results live in card, review, commit).
- Superseded plans, drafts, scratch notes, duplicate guides: DELETE after the useful part is merged.
- STATE.md: trim "Done this session" to what the next session needs; history lives in git/CHANGELOG.

## Never delete (only UPDATE or mark superseded)
ADRs (`status: superseded by ...`), reviews/audits and quant/legal reports that back a GO/NO-GO verdict,
task cards, tests, CI, migrations, `docs/guides/*` the user still needs. Anything outside this list
that the user created: ask first.

Done when: hygiene list committed, changes applied, `make check` unaffected, the user summary lists deleted
and updated files (one line each).
