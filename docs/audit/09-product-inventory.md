# 09 - Product Inventory

Basis: static code/doc review at commit 83824bd (branch chore/agent-pipeline-adoption), ~7.6k LOC in `src/nexus`, 32 unit test files + 5 integration test files. Nothing was executed; "works" below means "implemented and covered by tests per repo evidence", not verified live.

## What the product does now (V1 / Stage 1.5, read-only)

A containerized multi-exchange spot arbitrage detector. Services: migrator, scanner, worker-alerts, worker-maintenance, beat, plus postgres and redis (docker-compose.local.yml:119-223).

| # | Feature | Code evidence | Status |
|---|---|---|---|
| F1 | 7 CEX adapters (Bybit, Binance, OKX, Gate.io, KuCoin, MEXC, Bitget) via ccxt behind a registry | `src/nexus/adapters/cex/*.py`, `adapters/registry.py` | Implemented; fixtures in tests |
| F2 | Read-only enforcement: non-GET blocked on authenticated clients | `adapters/cex/ccxt_base.py:76-102`, `tests/unit/test_safety.py` | Implemented |
| F3 | Universe/ticker pre-filter and candidate selection | `scanner/universe.py`, `engine/candidates.py` | Implemented |
| F4 | Order-book depth walk, fees on both legs, slippage, transfer cost | `engine/depth.py`, `engine/estimator.py`, `engine/transfer.py`, `domain/spread.py` | Implemented, Decimal-based (only 2 `float(` uses, both non-money: workers/tasks.py:79, notifications/telegram.py:60) |
| F5 | False-positive guards (stale/skewed/crossed books, gross cap, unverified-contract cap, transfer unavailable) | `domain/spread.py`, `SpreadSettings` in `config/groups.py` | Implemented |
| F6 | WebSocket hot-set for routes with positive net spread, REST fallback | `scanner/streams.py` (166 lines), `ccxt_base.py:517 watch_order_book` | Implemented; effectiveness unmeasured |
| F7 | Opportunity episodes (one alert per run, re-alert on growth, closed summary) | `scanner/episodes.py`, `domain/episodes.py` | Implemented |
| F8 | Auto-quarantine of dead routes (persistence, recurrence, unavailable) | `scanner/quarantine.py`, `domain/quarantine.py`, migration `add_route_quarantine` | Implemented; recurrence history in memory only (todo.md:305) |
| F9 | Paper trading with virtual inventory and virtual rebalances | `scanner/paper.py`, `simulation/portfolio.py` (423 lines), migration `add_paper_trading_tables` | Implemented |
| F10 | Telegram alerts, system events, episode-closed, daily digest (Russian, HTML) | `notifications/*`, `services/alerts.py`, `services/digest.py`, `workers/tasks.py` | Implemented |
| F11 | Persistence: evaluations, snapshots, episodes, quarantine, paper tables, exchange metadata stats; 6 Alembic migrations | `persistence/models.py`, `repositories.py`, `migrations/versions/` | Implemented |
| F12 | Retention cleanup via beat | `services/maintenance.py`, `workers/app.py` | Implemented |
| F13 | Exchange health tracking (down/recovered events), heartbeat healthcheck | `scanner/health.py`, `cli.py:40-76` | Implemented |
| F14 | Secret-scrubbing structured logging | `log.py` | Implemented |

User scenarios supported: (1) copy `.env.example`, `make up-local`, receive Telegram alerts on verified routes with net >= 0.3 % and >= $5; (2) receive a 09:00 digest with paper P&L, episodes, uptime and coverage; (3) query Postgres on 127.0.0.1:5432 for analysis; (4) tune via env (whitelist/blacklist, thresholds). Not supported: any interactive control, UI, trading, DEX.

## Claimed vs reality

- C1 README/todo: "Stage 1.5 implemented, soak pending" - consistent with code. Soak (>= 3 days, real keys) is NOT done (todo.md:310); only a ~10 h keyless soak (todo.md:293) and a 4 min smoke. The go/no-go metrics (>= 5-10 verified episodes/day surviving 2 s) are unknown. Severity: Medium (product value unproven). Confidence: High.
- C2 CLAUDE.md "V1 Target CEX: Bybit, Binance, OKX, Gate.io, KuCoin" vs code/README 7 exchanges (adds MEXC, Bitget) and todo.md:395 lists MEXC/Bitget under Stage 3 plugins as future. Doc drift. Severity: Low. Confidence: High.
- C3 todo.md 1.5.2 ticked "(R) audited" but its sub-item "With keys, statuses come from ccxt fetch_currencies on all 7 exchanges. Verify..." (todo.md:166) is unchecked: key-based transfer-status paths are unverified on real exchanges. Fee/status correctness drives "verified route" gating, the core false-positive defense. Severity: Medium. Confidence: High.
- C4 todo.md 1.9 "Smoke test... graceful stop" ticked while "User check: real Telegram token" unchecked (todo.md:112). Real-Telegram delivery formatting is thus unconfirmed by the user, though the 4-minute live smoke reports an alert sent.
- C5 CLAUDE.md layout lists `execution/`, `dashboard/`, `adapters/dex/`: absent (expected, future). `interfaces/dex.py` defines `BaseDEXProvider` (37 lines) with no implementation - dead scaffolding. `ITradeExecutor` absent, consistent with the safety rule.
- C6 Hard Safety Rule 2 ("refuse to start in trading mode if withdrawal permission detected") has no code, but there is no trading mode either. Not a defect now.
- C7 README says `make test-integration  # repositories against PostgreSQL` but there are 5 integration files (digest, episodes, paper, quarantine, repositories); no Makefile wiring to the compose DB (see 07 INF-14).
- C8 The audit gates: todo.md 1.5.6 (R) and 1.5.11 (R) are ticked but, unlike 1.5.1-1.5.5/1.5.7, their headings carry no "audited: SAFE TO PROCEED" marker (todo.md:218, 293). Either the audit was skipped or not recorded. Severity: Medium (process). Confidence: Medium.
- C9 Soak finding 1.5.11: "recurrence history is in memory (a restart forgets)" accepted - quarantine can be defeated by restarts. Low.

## Duplicates and overlap
- D1 todo.md:117 (24 h soak) is explicitly superseded by 1.5.10 soak; both remain unchecked -> double-counted open items.
- D2 Alert dedup has two mechanisms: legacy route cooldown (`SPREAD_ALERT_COOLDOWN_S`) and episode id keys (todo.md:213); kept as "floor" - added config surface.
- D3 Roadmap duplicates: digest appears in 1.5.8 (done) and again in 2.4 "Daily digest (beat...)" (todo.md:349); MEXC/Bitget in 1.5.1 (done) and 3.4 (todo.md:395); exchange health/heartbeat in 1.7 and 2.5 monitoring.
- D4 Dual ccxt usage: `ccxt.async_support` (REST) and `ccxt.pro` (WS) clients per exchange in one adapter; `binance_public.py` adds a separate Binance path for keyless capital config.

## Unchecked todo.md items (as of this audit)

Stage 1: 1.9 user check real Telegram token (112); 1.10 24h soak (117, superseded).
Stage 1.5: user keys for all 7 exchanges (144); 1.5.2 with-keys verification (166); 1.5.9 revisit `SCANNER_MIN_QUOTE_VOLUME_USD` after soak (291); 1.5.10 multi-day soak (310) and Stage 2 go/no-go (311).
Stage 2 (entirely open): 2.0 guide (320-322); 2.1 executor, pre-trade checks, two-leg execution, leg risk, idempotent IDs, inventory model, withdrawal-permission startup check, paper default (325-332); 2.2 risk limits, kill switch, circuit breakers, isolated risk settings, separate DB roles (335-339); 2.3 order state machine, persistence, reconciliation (342-344); 2.4 advanced notifications, monthly summary (347-350); 2.5 prod compose, isolation, backups, monitoring (353-356); 2.6 CI/CD (359-362); 2.7 exit criteria (365-367).
Stage 3 (entirely open): 3.0 guide (374); 3.1 backend/auth/brute-force (377-379); 3.2 analytics and controls (382-386); 3.3 UI (389-391); 3.4 plugins/DEX (394-398); 3.5 exit (401-402).

## Key risks to product value
1. The core question (do verified opportunities exist and survive latency?) is unanswered until the keyed multi-day soak (C1).
2. Infrastructure for running that soak unattended is missing (see 07: no backup, no external alive signal).
3. Paper P&L in first soak was +$82 realized but -$102 MTM (todo.md:295-296): profitability not demonstrated.
