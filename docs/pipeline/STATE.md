# STATE (updated 2026-10-30)

Older history: see `git log -- docs/pipeline/STATE.md`.

## Where we are
- **Trajectory: NO-GO** (user decision 2026-10-25, `docs/reports/go-no-go.md`). Product = self-hosted
  spread-alert tool (ADR 0010, `docs/decisions/0010-self-hosted-alert-tool.md`). No trading, no paper portfolios (ADR 0001).
- **Stage S1-tool gates passed:**
  - tech-lead ACCEPT (round 3)
  - security ACCEPT
  - tester unit regression green
  - delta audit `docs/audit/delta-03-S1-tool.md`
- **T12 repo hygiene done** (`7a754e3`).
- **T14 stage gates: open, pending user** (close after manual checks below).
- Branch `chore/agent-pipeline-adoption`. Not merged to `main` (only with user consent).

## Quality ratchet (never get worse)
- 1085 unit tests green
- branch coverage 92.08 % (floor 89 %)
- ruff 0, mypy --strict 0

## User waits (open items)
1. **Manual checks** per `docs/guides/s1-tool-e2e-check.md`:
   - N-2: image build with and without `config/local.toml`
   - N-3: live-bot E2E
2. **Tags:** propose `s1-tool-rc1`, then `v0.1.0` after checks.
3. **CLAUDE.md proposal:** `docs/handoffs/project-manager-to-user-claude-md-2026-10-25.md`, section "Update 2026-10-30".
4. **Merge to `main`:** only with explicit user consent.
5. **Old data deletion:** commands handed to the user (agents have no permission to run them). Completion not recorded here.

## Key decisions in force
- NO-GO 2026-10-25.
- Tool posts analytical spread alerts and stores data in PostgreSQL. Alerts go only to the owner's PRIVATE Telegram channel/chat (lawyer T13: public channels breach OKX/KuCoin ToS).
- License: Apache-2.0.
- Alert language: `en` default; owner uses `ru` via `config/local.toml`.
- Agents retired: quant-analyst, risk-manager, creative-ceo, observability-engineer.
- Stack stopped (`docker compose stop`). Old volumes and backups: deletion by user.
- Exchange keys: read-only, withdrawals disabled. IP whitelist waived for local use only; mandatory on any server and before any trading permission.

## Next
- S2 backlog (`todo.md`):
  - R5b: `no-new-privileges` for postgres/redis (low)
  - I1: redact `ExchangeDown` Telegram text, send class + HTTP status only (source: `docs/audit/security-review-S1-tool.md`)
- Blocking: none for agents. Waiting on user items above.
