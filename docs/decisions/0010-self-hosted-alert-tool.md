# 0010 — Nexus becomes a self-hosted spread-alert tool (after NO-GO)

Date: 2026-10-25. Status: accepted (records the owner's decisions of 2026-10-25 after the
earlier trading-strategy research ended in NO-GO). Supersedes earlier internal decisions on an
iteration loop, a GO-HOLD state and hedged paper trading. ADR 0001 stays in force unchanged.

## Context
The research phase ended in NO-GO: no tested strategy (spot inventory, hedged transfer,
margin short, unhedged transfer) reaches the GO criterion under the user's access constraints. The
scanner, net-spread math, orderbook slippage, transfer-cost metadata, alerts and PostgreSQL analytics
work and are useful on their own. The user chose to keep them as a product that anyone can run for
themselves, and to drop everything that only served the GO verdict.

## Decision drivers
- One authority for the post-NO-GO scope.
- Hard rules unchanged: no trading, no withdrawal/transfer code (ADR 0001), secrets never leave `.env`.
- A third party must get from `git clone` to alerts in their own Telegram with minimal steps.
- Less code to maintain: remove features with no consumer after NO-GO.

## Considered options
1. **Self-hosted tool (chosen).** Anyone clones the repo, runs `cp .env.example .env`, fills their own
   Telegram bot token and chat/channel id and optional read-only exchange keys, runs one command; alerts
   go to their own chat or channel, data goes to their own PostgreSQL.
2. **Hosted bot / public channel run by the user.** Rejected: needs a server, uptime, support, and raises
   the distribution/ToS questions of a public service; no revenue model.
3. **Portfolio packaging only** (freeze the repo as a showcase, vision s.5 "honest pivots"). Rejected as
   the main path: the tool is useful as is; a clean self-hosted tool is also the better portfolio piece.
4. **Keep paper/GO machinery "just in case".** Rejected: no consumer, large test and migration surface,
   and it keeps old soak-specific config in the user-facing setup.

## Decision
- **Product:** self-hosted, Docker-first spread-alert tool. Scanner + net spread after fees, slippage and
  transfer cost; Telegram alerts (`[alert] language = en|ru`, default `en`); PostgreSQL storage for the
  operator's own analytics. Public mode when no keys are set; keyed read-only mode per venue when keys
  are given (transfer status / fees metadata only).
- **Dropped:** paper portfolios (`PaperBook`/`PaperTrader`, `paper_*` tables, digest/watchdog parts that
  read them), the GO report, hedged transfer (already removed),
  perp market data, the iteration loop and GO-HOLD states, any path to trading.
- **Schema:** Alembic history is squashed into one initial schema; existing deployments start from
  a fresh DB (data wipe already approved by the user).
- **Key policy:** human `KEY_POLICY_*` attestations are not required from third-party operators; an
  optional `KEY_POLICY_STRICT` keeps the strict check for those who want it. Keys stay read-only,
  withdrawals disabled (ADR 0001).
- **ADR 0001** stays in force. Revisiting it needs a new ADR and the owner's explicit decision.
- **DEX:** the seam (ADR 0004) stays documented; no DEX code unless the user opens a new decision.

## Consequences
Good:
- Smaller codebase and schema; one clear onboarding path.
- No money-touching code at all; legal exposure limited to running a read-only tool.

Bad:
- Historical soak/paper data and GO-report tooling are gone.
- Squashed migrations break upgrades of any existing DB (acceptable: only the user's, wipe approved).
- Quality-ratchet numbers will drop in test count as paper tests are removed; the floor is coverage
  (89 %), ruff 0, mypy 0, not the raw test count (tech-lead to restate the baseline at S1-tool end).

## Confirmation
- No order/withdrawal/transfer calls in `src/` (existing ADR 0001 check stays in CI/review).
