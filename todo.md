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
- [x] Phase 5 tail: lawyer/security review of vision+architecture
- [x] U2 decisions: DEX seam only (ADR 0006), risk-manager added; roadmap = `docs/architecture/migration-plan.md` (project-manager cuts cards)

## Track 0 — Base (M1/M2 start)
- [x] R-01 Integration tests only on `nexus_test` DB, refuse otherwise
- [x] B1 `CORE_EXCHANGES` default, bitget/mexc extension-only — card `docs/tasks/m2/B1-core-exchanges-default.md` (first)
- [x] R-05 (first CI run green 2026-10-23, user-confirmed) GitHub Actions CI (lint, mypy, unit, integration w/ services, secret scan, image build) + coverage floor 89 % (A2) — card `docs/tasks/track0/A2-github-actions-ci.md`
- [x] A2a gitleaks pre-commit hook (S-06 G1; low) — card `docs/tasks/track0/A2a-gitleaks-pre-commit.md`
- [x] R-06 Bump certifi, protobuf (unpin or justify), pip-audit incl. dev group (done in f6b5abb: protobuf 5.29.6, certifi 2026.10.23, CI pip-audit --all-groups; confirmed by delta audit)
- [x] R-07 Tests prove httpx/stdlib loggers do not leak tokens; scrubber covers `redis://user:pass@` URLs (A4) — card `docs/tasks/track0/A4-log-scrub-tests.md`
- [ ] R-09 split into A5a-A5d (security review S-01..S-04, S-09, S-10, S-12):
  - [x] A5a backups + restore drill into `nexus_test` + external heartbeat (drill PASSED 2026-10-23; daily cron 03:15 installed in user crontab 2026-10-23; heartbeat deferred to VPS by user decision) — card `docs/tasks/track0/A5a-backups-restore-drill.md`
  - [ ] A5b Redis auth, healthcheck, maxmemory noeviction — card `docs/tasks/track0/A5b-redis-auth.md`
  - [ ] A5c DB roles + `nexus_test_owner` test role (needs user OK, U4) — card `docs/tasks/track0/A5c-db-roles-test-role.md`
  - [ ] A5d Docker hardening + secrets files (before any VPS) — card `docs/tasks/track0/A5d-docker-hardening-secrets.md`
- [x] A6 key-policy startup check (6766bfd + ee38592; tech-lead round 2 + security: accepted) `KeyPolicyCheck` (S-08/G4; before U3, no real keys without it) — card `docs/tasks/track0/A6-key-policy-startup-check.md`
- [ ] A6 follow-ups F-1..F-5 (parallel venue checks, IKeyIntrospection Protocol, guard test for _ws/transfer fallback, IP CIDR cut-off at U3, .env.example MEXC/Bitget wording) — see `docs/audit/tech-lead-review-track0.md` Round 2
- [x] B1a remove MEXC_*/BITGET_* key vars from scanner env + `.env.example` (G5; low) — card `docs/tasks/track0/B1a-remove-unused-key-vars.md`
- [ ] LICENSE decision (user)

- [x] A7 non-secret settings to committed `config/nexus.toml`, `.env` = secrets only (user decision 2026-10-23; after B15 part 1; security split pre-check; backend-lead; medium) — card `docs/tasks/track0/A7-config-file.md`. Accepted: security r1, tech-lead r2.
  - [ ] A7 follow-ups: check-env-settings clean error on bad .env encoding (TL R2-1), louder warning in up-local (R2-2), gitleaks `api-key` hyphen (R2-3) — `docs/audit/tech-lead-review-A7.md` Round 2

## Track 1 — Retro-verification
- [ ] `/audit`-style review for items 1.5.6 and 1.5.11 (security + tech-lead)
- [ ] Verify transfer-status parsers (needs read-only keys; guide for user)
- [x] Resolve scope drift: bitget/mexc adapters kept as extension only (ADR 0002)

## M2 — Code quality (under characterization tests)
- [x] R-02 Isolate exchange failures in sweep (`gather(return_exceptions=True)`) — done in S0b (`110fb91` + r2 `cb1c1af`, `gather_isolated`); per-route counters remain in B3
- [ ] R-03 Fee currency per exchange; no profit when transfer UNKNOWN; stablecoin peg guard (formula review: future `docs/quant/formula-review.md`, M3 quant item; the old `docs/reports/math-review.md` never existed in git)
- [ ] R-04 DB timeouts, purge indexes, batched purges, measure real row growth (+ A5a N4: drill [min,max] count check gives false MISMATCH once purges run alongside inserts; adjust drill when B7/purges land)
- [ ] R-08 Clock-drift guard; fix `_until_stopped` cancellation
- [ ] Split `scanner/service.py` (1169 lines; 20 `except Exception` in it, 35 in `src/`, 2026-10-24)
- [ ] Coverage gaps: repositories (integration), container, tasks, cli

## Migration-plan backlog (cards not cut yet; see `docs/architecture/migration-plan.md`)
- [ ] B3 log + count failed per-route evaluation tasks, `SweepResult.failed` (backend-lead, L)
- [ ] B4 / R-08a fix `_until_stopped` cancellation swallowing (backend-lead, L)
- [ ] B12 reaper for stale `SENDING` alert rows + payload version `v` (backend-lead, L)
- [ ] B13 WS fixes: `_give_up` unwatches, stream errors feed health tracker (backend-lead, L)
- [x] B14 (5ba4f07 + e23024d; tech-lead round 2: accepted) `CONDITIONAL_VENUES` (default bybit,gateio): every aggregate shows the list and combined totals ALL vs EXCLUDING conditional venues; marker on alerts (backend-lead + observability-engineer; medium) — card `docs/tasks/m2/B14-conditional-venues-reporting.md`
- [ ] B15 shadow paper portfolios (part 1 config/sim/persistence/migration DONE: architect r2, quant r2, tech-lead r3 ACCEPT + F1/F3; part 2 GO report generator per `docs/quant/b15-review-and-report-spec.md` incl. F2 fee disclosure: todo) per venue set (`[paper] venue_sets` in `config/nexus.toml`, env `PAPER_VENUE_SETS` overrides; soak runs 4 sets: all, excl_conditional, excl_bybit, excl_gateio; own inventory/rebalancing/top-N cap, same fixed capital; migration `portfolio_id` needs A5a restore drill + user OK U4; data accrues from the moment a set is added; quant GO report reads per-set results; backend-lead + quant-analyst; high) — card `docs/tasks/m2/B15-shadow-paper-portfolios.md`
- [ ] B16 public-only probe of expansion batch 1 (BingX, XT, Toobit, Bitfinex, Phemex; no keys, conditional by default, per-venue lawyer ToS gate, report in `docs/reports/`; backend-lead + crypto-specialist; medium) — card `docs/tasks/m2/B16-public-probe-expansion-batch1.md`
- [ ] C0 characterization pack for `Scanner.sweep`/`run` before the split (tester, L-M; after R-02/B3/B4)
- [ ] Backlog, no card (user idea G2): optional per-exchange proxy setting in adapters (ccxt proxy), off by default, proxy URL is a secret; gated by lawyer ToS check per core exchange on proxy/VPN use; design with the user when a server is discussed

## M3 — Data, quant, legal
- [ ] Agree GO/NO-GO numbers (threshold 2 %/month; see `docs/pipeline/nexus-appendix.md` P6)
- [x] S0 pre-soak gates: D-01 restart policy, D-02 backup copy to C:\nexus-backups + status file, R-02 sweep isolation, liveness watchdog to Telegram, gap accounting (devops + backend-lead; medium) — card `docs/tasks/m3/S0-pre-soak-gates.md`
- [x] S0 follow-up D-08: watchdog check for per-set paper data freshness (newest `paper_cap_stats` hour per set older than N h -> alert; disabled/failing set must not go silent) (backend-lead; small; before or early in the soak) — delta audit `docs/audit/delta-02-S0.md`
- [ ] Integration test (CI only, `nexus_test`) for the D-08 paper-set activity SQL (`PaperSetActivityRepository`), tech-lead D-08 review risk (tester; small)
- [ ] Multi-day keyed soak (>= 7-14 days) with backups running. Step 3.1 archive dump DONE 2026-10-24 (`nexus-archive-20261024T132431Z`, counts match, copied to C:). Remaining before/at soak start: fresh stack (U4 at each data step; guide `docs/guides/soak-fresh-stack.md`), D-03 restore drill on the first dump of the new DB, D-10 migrator exit 0 + `alembic current` = head, D-01 live restart check (security S-8). D-08 per-set freshness is its own line above (done). B15 part 1 done; part 2 report runs in parallel.
- [ ] Quant: formula review, cost model, latency vs spread lifetime, two execution modes, honest backtest, verdict
- [ ] Lawyer: `docs/legal/nexus-risk-assessment.md` verified with sources
- [ ] Dashboards as code (observability-engineer; ADR on stack)
- [ ] `docs/reports/go-no-go.md`

## M4 — Fork (UF): GO / Rework / NO-GO
- [ ] Iteration loop: up to 5 iterations of hypothesis search (vision + analyzer + quant + crypto), reports in `docs/reports/iterations/`, no separate code copies (ADR 0007)
- [ ] After 5 failed iterations: NO-GO -> portfolio packaging (only on explicit confirmation)

## Stage 2 / 3 (only after GO) — see `docs/pipeline/nexus-appendix.md` P7
