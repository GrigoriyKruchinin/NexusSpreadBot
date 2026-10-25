# 0010 — Nexus becomes a self-hosted spread-alert tool (after NO-GO)

Date: 2026-10-25. Status: accepted (records user decisions 2026-10-25 after UF NO-GO; see
`docs/pipeline/STATE.md` and `docs/reports/go-no-go.md`). Supersedes ADR 0007, ADR 0008, ADR 0009;
amends ADR 0006. ADR 0001 stays in force unchanged.

## Context
UF ended in NO-GO (`docs/reports/go-no-go.md`): no tested strategy (spot inventory, hedged transfer,
margin short, unhedged transfer) reaches the GO criterion under the user's access constraints. The
scanner, net-spread math, orderbook slippage, transfer-cost metadata, alerts and PostgreSQL analytics
work and are useful on their own. The user chose to keep them as a product that anyone can run for
themselves, and to drop everything that only served the GO verdict.

## Decision drivers
- One authority for the post-NO-GO scope, so S1-tool cards and T12 hygiene do not argue with old docs.
- Hard rules unchanged: no trading, no withdrawal/transfer code (ADR 0001), secrets never leave `.env`.
- A third party must get from `git clone` to alerts in their own Telegram with minimal steps.
- Less code to maintain: remove features with no consumer after NO-GO.

## Considered options
1. **Self-hosted tool (chosen).** Anyone clones the repo, runs `cp .env.example .env`, fills their own
   Telegram bot token and chat/channel id and optional read-only exchange keys, runs one command; alerts
   go to their own chat or channel, data goes to their own PostgreSQL.
2. **Hosted bot / public channel run by the user.** Rejected: needs a server, uptime, support, and raises
   the distribution/ToS questions of a public service (T13 lawyer input); no revenue model.
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
  read them), the GO report (`make go-report`, B15), hedged transfer (HT1, already removed in f603178),
  perp market data, the iteration loop and GO-HOLD states, any path to trading or Stage 2/3.
- **Schema:** Alembic history is squashed into one initial schema (T2); existing deployments start from
  a fresh DB (data wipe already approved by the user).
- **Key policy:** human `KEY_POLICY_*` attestations are not required from third-party operators; an
  optional `KEY_POLICY_STRICT` keeps the strict check for those who want it (T9). Keys stay read-only,
  withdrawals disabled (ADR 0001, CLAUDE.md rule 2).
- **ADR 0001** stays in force. Its "revisit in Stage 2-3 by creative-ceo" clause is void: there is no
  Stage 2-3 and creative-ceo is retired (T12). Revisiting ADR 0001 now needs a new ADR and the user.
- **DEX:** the seam (ADR 0004/0006) stays documented; no DEX code unless the user opens a new decision.

## Consequences
Good:
- Smaller codebase and schema; one clear onboarding path (T6-T8, T10).
- No money-touching code at all; legal exposure limited to running a read-only tool (T13).

Bad:
- Historical soak/paper data and GO-report tooling are gone; old evidence lives only in reports.
- Squashed migrations break upgrades of any existing DB (acceptable: only the user's, wipe approved).
- Quality-ratchet numbers will drop in test count as paper tests are removed; the floor is coverage
  (89 %), ruff 0, mypy 0, not the raw test count (tech-lead to restate the baseline at S1-tool end).

## Superseded / obsolete documents (input for T12 hygiene)
| Path | Status after this ADR |
|---|---|
| `docs/decisions/0007-iteration-loop-find-profitable-approach.md` | superseded (iteration loop cancelled) |
| `docs/decisions/0008-go-hold-dex-during-hold.md` | superseded (no GO/GO-HOLD states) |
| `docs/decisions/0009-perp-market-data-and-hedged-paper-strategy.md` | superseded (HT1 removed) |
| `docs/decisions/0006-u2-dex-seam-only-risk-manager.md` | amended (DEX timing "after GO" void; risk-manager retired) |
| `docs/product/vision.md` s.3 GO criterion, s.5 outcomes / GO-HOLD / iteration loop / pivots, s.7 ADR 0001 revisit, s.8 sceptic's dashboard | superseded; banner only (T12) |
| `docs/architecture/target.md` s.1 principles 2/5 ("until GO", "feeds GO verdict"), s.2/s.3/s.4 `paper.py` and `paper_*` rows, s.7 Stage 2 boundary | superseded in those parts; update after T1a/T1b |
| `docs/architecture/migration-plan.md` "Out of scope until GO", E-steps "revisit after GO", B7 paper retention, C6 paper glue | superseded in those parts |
| `docs/architecture/HT1-design-review.md` | obsolete (delete or archive) |
| `docs/tasks/HT1-hedged-transfer-paper.md`, `docs/tasks/m2/B15-*`, `docs/tasks/m2/B16-*`, `docs/tasks/m3/S1-fresh-stack-runbook.md` | obsolete |
| `docs/quant/hedged-transfer-spec.md`, `docs/quant/b15-review-and-report-spec.md`, `docs/quant/b15-part2-review.md`, `docs/quant/b14-conditional-totals-review.md` | obsolete (keep `hedge-method-comparison.md` as evidence) |
| `docs/guides/soak-fresh-stack.md`, `docs/guides/soak-auto-recovery.md`, `docs/guides/gate-0-how-to-continue.md` | obsolete (soak-specific) |
| `docs/legal/go-gates-checklist.md`, `docs/legal/futures-access.md` | historical evidence (GO gates no longer apply) |
| `docs/reports/go-no-go.md` | kept as evidence; authority for the NO-GO |

## Confirmation
- T12 hygiene: every path above deleted, archived or bannered; link check clean.
- `grep -ri "paper\|go-report" src/ config/` empty after T1a/T1b (except changelog/history notes).
- No order/withdrawal/transfer calls in `src/` (existing ADR 0001 check stays in CI/review).
