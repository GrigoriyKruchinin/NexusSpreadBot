# Nexus — Roadmap & Checklist

Legend: `[ ]` todo · `[x]` done. Cards: `docs/tasks/`. Stage-1 history: `docs/product/stage1-history.md`.
Ticks only after verification and commit.

## Adoption (Phases 0-6)
- [x] U0 intake (`docs/pipeline/intake.md`)
- [x] Audit `docs/audit/00-16`, stage assessment
- [x] U1 team approved (14 agents)
- [x] Claude files, conventions, STATE, context plan, guide
- [x] Phase 5: vision (`docs/product/vision.md`), target architecture + migration plan, ADR 0003-0005 accepted
- [x] User confirmed vision proposals (portfolio default pivot, manual rebalancing; Rework extended to up to 5 iterations, ADR 0007)
- [ ] Phase 5 tail: lawyer/security review of vision+architecture
- [x] U2 decisions: DEX seam only (ADR 0006), risk-manager added; roadmap = `docs/architecture/migration-plan.md` (project-manager cuts cards)

## Track 0 — Base (M1/M2 start)
- [x] R-01 Integration tests only on `nexus_test` DB, refuse otherwise
- [x] B1 `CORE_EXCHANGES` default, bitget/mexc extension-only — card `docs/tasks/m2/B1-core-exchanges-default.md` (first)
- [x] R-05 (first CI run green 2026-10-23, user-confirmed) GitHub Actions CI (lint, mypy, unit, integration w/ services, secret scan, image build) + coverage floor 89 % (A2) — card `docs/tasks/track0/A2-github-actions-ci.md`
- [x] A2a gitleaks pre-commit hook (S-06 G1; low) — card `docs/tasks/track0/A2a-gitleaks-pre-commit.md`
- [ ] R-06 Bump certifi, protobuf (unpin or justify), pip-audit incl. dev group
- [x] R-07 Tests prove httpx/stdlib loggers do not leak tokens; scrubber covers `redis://user:pass@` URLs (A4) — card `docs/tasks/track0/A4-log-scrub-tests.md`
- [ ] R-09 split into A5a-A5d (security review S-01..S-04, S-09, S-10, S-12):
  - [ ] A5a backups + restore drill into `nexus_test` + external heartbeat (needs user OK, U4) — card `docs/tasks/track0/A5a-backups-restore-drill.md`
  - [ ] A5b Redis auth, healthcheck, maxmemory noeviction — card `docs/tasks/track0/A5b-redis-auth.md`
  - [ ] A5c DB roles + `nexus_test_owner` test role (needs user OK, U4) — card `docs/tasks/track0/A5c-db-roles-test-role.md`
  - [ ] A5d Docker hardening + secrets files (before any VPS) — card `docs/tasks/track0/A5d-docker-hardening-secrets.md`
- [x] A6 key-policy startup check (6766bfd + ee38592; tech-lead round 2 + security: accepted) `KeyPolicyCheck` (S-08/G4; before U3, no real keys without it) — card `docs/tasks/track0/A6-key-policy-startup-check.md`
- [ ] A6 follow-ups F-1..F-5 (parallel venue checks, IKeyIntrospection Protocol, guard test for _ws/transfer fallback, IP CIDR cut-off at U3, .env.example MEXC/Bitget wording) — see `docs/audit/tech-lead-review-track0.md` Round 2
- [x] B1a remove MEXC_*/BITGET_* key vars from scanner env + `.env.example` (G5; low) — card `docs/tasks/track0/B1a-remove-unused-key-vars.md`
- [ ] LICENSE decision (user)

## Track 1 — Retro-verification
- [ ] `/audit`-style review for items 1.5.6 and 1.5.11 (security + tech-lead)
- [ ] Verify transfer-status parsers (needs read-only keys; guide for user)
- [x] Resolve scope drift: bitget/mexc adapters kept as extension only (ADR 0002)

## M2 — Code quality (under characterization tests)
- [ ] R-02 Isolate exchange failures in sweep (`gather(return_exceptions=True)`), per-route error counters
- [ ] R-03 Fee currency per exchange; no profit when transfer UNKNOWN; stablecoin peg guard (`docs/reports/math-review.md`)
- [ ] R-04 DB timeouts, purge indexes, batched purges, measure real row growth
- [ ] R-08 Clock-drift guard; fix `_until_stopped` cancellation
- [ ] Split `scanner/service.py` (1048 lines); review 25 `except Exception`
- [ ] Coverage gaps: repositories (integration), container, tasks, cli

## Migration-plan backlog (cards not cut yet; see `docs/architecture/migration-plan.md`)
- [ ] B3 log + count failed per-route evaluation tasks, `SweepResult.failed` (backend-lead, L)
- [ ] B4 / R-08a fix `_until_stopped` cancellation swallowing (backend-lead, L)
- [ ] B12 reaper for stale `SENDING` alert rows + payload version `v` (backend-lead, L)
- [ ] B13 WS fixes: `_give_up` unwatches, stream errors feed health tracker (backend-lead, L)
- [ ] B14 (5ba4f07; tech-lead round 1: returned) `CONDITIONAL_VENUES` (default bybit,gateio): every aggregate shows the list and combined totals ALL vs EXCLUDING conditional venues; marker on alerts (backend-lead + observability-engineer; medium) — card `docs/tasks/m2/B14-conditional-venues-reporting.md`
- [ ] B15 shadow paper portfolios per venue set (config `PAPER_VENUE_SETS`, default `all` + `excl_conditional`, own inventory/rebalancing/top-N cap, same fixed capital; migration `portfolio_id` needs A5a restore drill + user OK U4; data accrues from the moment a set is added; quant GO report reads per-set results; backend-lead + quant-analyst; high) — card `docs/tasks/m2/B15-shadow-paper-portfolios.md`
- [ ] B16 public-only probe of expansion batch 1 (BingX, XT, Toobit, Bitfinex, Phemex; no keys, conditional by default, per-venue lawyer ToS gate, report in `docs/reports/`; backend-lead + crypto-specialist; medium) — card `docs/tasks/m2/B16-public-probe-expansion-batch1.md`
- [ ] C0 characterization pack for `Scanner.sweep`/`run` before the split (tester, L-M; after R-02/B3/B4)
- [ ] Backlog, no card (user idea G2): optional per-exchange proxy setting in adapters (ccxt proxy), off by default, proxy URL is a secret; gated by lawyer ToS check per core exchange on proxy/VPN use; design with the user when a server is discussed

## M3 — Data, quant, legal
- [ ] Agree GO/NO-GO numbers (threshold 2 %/month; see `docs/pipeline/nexus-appendix.md` P6)
- [ ] Multi-day keyed soak (>= 7-14 days) with backups running (depends on B15: shadow portfolios must be running before the soak starts, else no valid "without" GO numbers; also A5a)
- [ ] Quant: formula review, cost model, latency vs spread lifetime, two execution modes, honest backtest, verdict
- [ ] Lawyer: `docs/legal/nexus-risk-assessment.md` verified with sources
- [ ] Dashboards as code (observability-engineer; ADR on stack)
- [ ] `docs/reports/go-no-go.md`

## M4 — Fork (UF): GO / Rework / NO-GO
- [ ] Iteration loop: up to 5 iterations of hypothesis search (vision + analyzer + quant + crypto), reports in `docs/reports/iterations/`, no separate code copies (ADR 0007)
- [ ] After 5 failed iterations: NO-GO -> portfolio packaging (only on explicit confirmation)

## Stage 2 / 3 (only after GO) — see `docs/pipeline/nexus-appendix.md` P7
