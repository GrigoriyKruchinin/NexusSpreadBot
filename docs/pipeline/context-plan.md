# Context plan

All important state lives in files: STATE.md, todo.md, docs/tasks/, docs/handoffs/, docs/decisions/,
docs/adr/, docs/reports/. Context can be reset at any time.
- Agents read only CLAUDE.md, their card and linked docs; end with updated files + handoff + short report.
- Orchestrator checkpoints after every stage/sub-stage (checkpoint-context), then recommends `/clear` and "continue".
- Hooks: SessionStart prints STATE.md; PreCompact reminds to update it.
- Long runs: `scripts/run-pipeline.sh` (one step per clean session). No `--dangerously-skip-permissions`.
