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
- [ ] R-05 GitHub Actions CI (lint, mypy, unit, integration w/ services, secret scan, image build) + coverage floor 89 %
- [ ] R-06 Bump certifi, protobuf (unpin or justify), pip-audit incl. dev group
- [ ] R-07 Silence httpx INFO / scrub tokens in stdlib loggers
- [ ] R-09 Postgres pg_dump backups + external heartbeat; Redis auth; per-service DB roles
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

## M3 — Data, quant, legal
- [ ] Agree GO/NO-GO numbers (threshold 2 %/month; see `docs/pipeline/nexus-appendix.md` P6)
- [ ] Multi-day keyed soak (>= 7-14 days) with backups running
- [ ] Quant: formula review, cost model, latency vs spread lifetime, two execution modes, honest backtest, verdict
- [ ] Lawyer: `docs/legal/nexus-risk-assessment.md` verified with sources
- [ ] Dashboards as code (observability-engineer; ADR on stack)
- [ ] `docs/reports/go-no-go.md`

## M4 — Fork (UF): GO / Rework / NO-GO
- [ ] Iteration loop: up to 5 iterations of hypothesis search (vision + analyzer + quant + crypto), reports in `docs/reports/iterations/`, no separate code copies (ADR 0007)
- [ ] After 5 failed iterations: NO-GO -> portfolio packaging (only on explicit confirmation)

## Stage 2 / 3 (only after GO) — see `docs/pipeline/nexus-appendix.md` P7
