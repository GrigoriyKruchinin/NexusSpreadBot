#!/usr/bin/env bash
# Run one pipeline step in a clean Claude Code session (non-interactive).
set -euo pipefail
cd "$(dirname "$0")/.."
claude -p "continue: read CLAUDE.md, docs/pipeline/STATE.md and todo.md, do the next step, update STATE.md, then stop." \
  --agent orchestrator --max-turns 80
