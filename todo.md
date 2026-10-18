# Nexus Spread Scanner — Roadmap & Task Checklist

Legend: `[ ]` todo · `[x]` done · `(R)` requires `/audit-risks` before ticking.

---

## Phase 0 — Infrastructure Setup

- [x] Clarifying questions answered
  - [x] V1 exchanges: Bybit, Binance, OKX, Gate.io, KuCoin (spot)
  - [x] Alert threshold: net profit ≥ 0.3 % AND ≥ $5
  - [x] Reference notional for slippage: $1,000
  - [x] Admin credentials: via `.env` (`ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`)
- [x] `CLAUDE.md` (commands, style, architecture rules, workflow gates)
- [x] `.claude/agents/implementation.md` — Implementation Agent
- [x] `.claude/agents/risk-critic.md` — Security & Trading Risk Critic Agent
- [x] `.claude/skills/` — `check-code-quality`, `run-tests`, `audit-risks`, `next-task`, `ship`
- [x] Hard safety rule: bot never withdraws/transfers funds
- [x] Autonomous delivery loop: implement → verify → tick → commit → push
- [x] `.claude/settings.json` — tool permissions, `.env` read deny
- [x] `todo.md` (this file)
- [x] User says **"Start Implementation"**

---

## Stage 1 — MVP: Opportunity Detector & Telegram Alerts (Read-Only, local)

### 1.0 User guide → `docs/guides/stage-1-local-setup.md` (Russian, file only)
- [x] Read-only API keys: Bybit, Binance, OKX, Gate.io, KuCoin (note: public orderbooks need no keys; keys are used for per-account fee tiers & deposit/withdrawal status)
- [x] Telegram bot via `@BotFather` → `TELEGRAM_BOT_TOKEN`; obtain `TELEGRAM_CHAT_ID`
- [x] Local `.env` from `.env.example`; Docker Desktop / WSL2 prerequisites

### 1.1 Project skeleton & tooling
- [ ] `pyproject.toml` (uv, Python 3.12, `src/` layout, dependency groups: main / dev)
- [ ] `uv.lock` generated
- [ ] ruff config (line length 100, rule sets: E, F, I, B, UP, N, S, ASYNC, RUF, ANN, SIM, PT)
- [ ] mypy strict config (+ pydantic plugin, sqlalchemy typing)
- [ ] pytest config (`asyncio_mode=auto`, `integration` marker, coverage)
- [ ] Root `Makefile` (lint, format, typecheck, test, test-cov, check, up-local, down-local, logs, migrate, revision)
- [ ] `.env.example` with every setting documented
- [ ] `pre-commit` config (ruff, mypy, end-of-file, detect-secrets)
- [ ] `README.md` (English): overview, architecture diagram, quickstart

### 1.2 Modular Pydantic Settings
- [ ] Base groups: `DatabaseSettings`, `RedisSettings`, `CelerySettings`, `TelegramSettings`, `LoggingSettings`
- [ ] `ExchangeCredentials` per exchange (`SecretStr`, optional in V1) + `ExchangesSettings` (enabled list, symbols whitelist/blacklist)
- [ ] `SpreadSettings`: `min_net_profit_pct=0.3`, `min_net_profit_usd=5`, `reference_notional_usd=1000`, `max_orderbook_age_ms`, `alert_cooldown_s`
- [ ] Role-specific loaders: `MigratorSettings`, `SchedulerSettings`, `ScannerSettings`, `NotifierWorkerSettings`, `AppSettings` (full, for tests/dev only)
- [ ] Unit tests: each role loader ignores/forbids unrelated secrets

### 1.3 Domain & Interfaces
- [ ] Value objects (Decimal): `Symbol`, `Asset`, `PriceLevel`, `OrderBook` (timestamped), `FeeSchedule`, `TransferCost`, `SpreadOpportunity`
- [ ] Error hierarchy (`domain/errors.py`)
- [ ] Interfaces: `IRestMarketData`, `IWebSocketOrderbook`, `IFeeProvider`, `ITransferInfoProvider`, `BaseExchangeAdapter`, `BaseDEXProvider` (stub for V3), `INotifier`, repository protocols
- [ ] Exchange registry / factory (register adapters by name, no orchestrator changes on add)

### 1.4 Async CEX Connectors
- [ ] Shared base: ccxt.pro wrapper, reconnect w/ backoff, heartbeat, rate-limit handling, symbol normalization
- [ ] `BybitAdapter`
- [ ] `BinanceAdapter`
- [ ] `OKXAdapter`
- [ ] `GateIOAdapter`
- [ ] `KuCoinAdapter`
- [ ] Market metadata sync: common symbol intersection, tick/lot sizes, taker/maker fees, deposit/withdraw enabled + network fees per chain
- [ ] Orderbook snapshots → Redis hot cache (TTL = max book age)
- [ ] Adapter tests with recorded fixture payloads

### 1.5 Net Spread Engine (R)
- [ ] Depth walker: VWAP for buy (asks) / sell (bids) at reference notional; reject if insufficient depth
- [ ] Fee model: taker fees on both legs, fee asset handling
- [ ] Transfer cost model: cheapest common network withdrawal fee, deposit/withdraw availability check
- [ ] `NetSpreadEstimator`: gross spread → net spread (%, USD) with full cost breakdown
- [ ] Staleness & clock-skew guard
- [ ] Threshold filter (both % and USD) + per-pair alert cooldown / dedup
- [ ] Unit tests with hand-computed scenarios (incl. edge cases: empty book, thin book, suspended withdrawals, symbol collision)

### 1.6 Persistence (PostgreSQL)
- [ ] Async engine & session factory
- [ ] Models: `Exchange`, `MarketPair`, `SpreadSnapshot` (sampled), `Opportunity` (with cost breakdown), `AlertLog`, `ExchangeHealth`
- [ ] Indexes for time-series queries; retention policy for snapshots
- [ ] Alembic setup + initial migration
- [ ] Repository implementations + integration tests

### 1.7 Redis / Celery
- [ ] Celery app (Redis broker/backend), task routing: `scanner`, `alerts`, `maintenance` queues
- [ ] Beat schedule: market metadata refresh, fee refresh, snapshot retention cleanup, health checks
- [ ] Alert tasks with retries & idempotency keys
- [ ] Scanner orchestrator service (long-running asyncio process: WS streams → cache → estimator → DB + alert queue)

### 1.8 Telegram Notifier
- [ ] `TelegramNotifier(INotifier)` on aiogram, HTML parse mode, rate-limit aware
- [ ] Opportunity alert template: 🔀 pair, buy/sell exchanges, prices, gross vs net spread, fee/slippage/transfer breakdown, est. profit on $1,000, book age, blockquote summary
- [ ] System alerts: exchange disconnect/reconnect, scanner start/stop
- [ ] Escaping & snapshot tests of rendered messages

### 1.9 Docker (local)
- [ ] Multi-stage `Dockerfile` (uv, non-root user, slim runtime)
- [ ] `docker-compose.local.yml`: postgres, redis, migrator, scanner, celery-worker, celery-beat, telegram-worker
- [ ] Healthchecks for all services; `depends_on: condition: service_healthy` / `service_completed_successfully` (migrator)
- [ ] Per-service `env_file`s exposing only required variables
- [ ] Smoke test: stack up → alerts received in Telegram

### 1.10 Stage 1 Exit
- [ ] `make check` green, coverage `engine/` ≥ 90 %
- [ ] `/audit-risks` verdict SAFE TO PROCEED
- [ ] 24h local soak run; review false-positive rate from DB

---

## Stage 2 — Prod: Automated Trade Execution & CI/CD

### 2.0 User guide → `docs/guides/stage-2-production-setup.md` (Russian, file only)
- [ ] Trade-only API keys (withdrawals DISABLED, IP whitelist) for each exchange
- [ ] VPS provisioning (region near exchange matching engines), SSH hardening, firewall
- [ ] Docker Engine + Compose plugin install; production secrets preparation

### 2.1 Trade Execution Engine (R)
- [ ] `ITradeExecutor` per exchange adapter (separate from market-data interfaces)
- [ ] Pre-trade checks: fresh re-quote, balance check on both exchanges, slippage tolerance, min notional / lot rounding
- [ ] Concurrent two-leg execution (IOC/limit-with-tolerance), execution timeout
- [ ] Partial fill & leg-risk handling: hedge/unwind strategy
- [ ] Idempotent client order IDs; no duplicate submission on retry
- [ ] Inventory model (pre-funded balances on each exchange; rebalancing alerts only)
- [ ] No withdraw/transfer methods in any interface; startup check refuses keys with withdrawal permission (where detectable)
- [ ] Paper-trading / dry-run mode (default ON)

### 2.2 Risk Limits (R)
- [ ] Max position size per trade / per symbol / per exchange
- [ ] Daily loss limit & global kill switch (Redis flag + Telegram command)
- [ ] Max concurrent open executions; per-exchange circuit breaker on error rate
- [ ] Risk settings group isolated to executor container

### 2.3 Order State Management
- [ ] Order/Execution state machine (NEW → SUBMITTED → PARTIAL → FILLED / CANCELLED / FAILED)
- [ ] Persistence models: `Execution`, `Order`, `Fill`, `BalanceSnapshot`
- [ ] Reconciliation task vs exchange order history

### 2.4 Advanced Telegram Notifications
- [ ] 🟢 Successful arbitrage: latency (ms), volume, fees, net profit USD
- [ ] ⚠️ Warnings: partial fills, timeouts, connection anomalies, risk-limit hits
- [ ] 📊 Daily digest (beat, configurable time/TZ)
- [ ] 📊 Monthly summary on the 1st (PnL, volume, win rate, best pairs/exchanges, fees paid)

### 2.5 Production Deployment
- [ ] `docker-compose.yml` (prod): restart policies, resource limits, log rotation, Docker secrets
- [ ] Executor container isolated with only trade keys; scanner has none
- [ ] Postgres backups (scheduled `pg_dump` → offsite)
- [ ] Monitoring: healthcheck endpoint, Telegram heartbeat

### 2.6 CI/CD
- [ ] GitHub Actions: lint, typecheck, unit tests, integration tests (service containers)
- [ ] Image build & push (GHCR), tagged by commit SHA
- [ ] Deploy job to VPS (SSH, `docker compose pull && up -d`, migration step, rollback)
- [ ] Secret scanning & dependency audit in CI

### 2.7 Stage 2 Exit
- [ ] Paper-trading run ≥ 7 days with reconciliation clean
- [ ] `/audit-risks` verdict SAFE TO PROCEED
- [ ] Live with minimal position limits

---

## Stage 3 — FastAPI Admin Dashboard & Multi-Exchange Expansion

### 3.0 User guide → `docs/guides/stage-3-dashboard.md` (Russian, file only)
- [ ] Generating `ADMIN_PASSWORD_HASH`, dashboard access & security notes

### 3.1 Dashboard Backend
- [ ] FastAPI app (separate container, `DashboardSettings` only, read-only DB role)
- [ ] Auth: login with `ADMIN_USERNAME` / bcrypt `ADMIN_PASSWORD_HASH`, JWT (short TTL) + HTTP-only cookie; Basic Auth fallback for API
- [ ] Brute-force protection (rate limiting), secure headers, CORS policy

### 3.2 Analytics API
- [ ] Spread distribution by pair / exchange pair / time window
- [ ] Exchange profitability metrics; realized PnL (V2 data)
- [ ] Latency metrics (WS lag, execution latency)
- [ ] Top deals table (paginated, filterable)
- [ ] Runtime controls: pause scanner, kill switch, threshold edit (audited)

### 3.3 Chart.js UI
- [ ] Layout & theme (Jinja2 templates + static assets)
- [ ] Spread distribution histogram, PnL over time, latency charts, exchange heatmap
- [ ] Top deals table, live opportunity feed (SSE/WebSocket)

### 3.4 Multi-Exchange / DEX Plugins
- [ ] Plugin discovery (entry points) for `BaseExchangeAdapter` / `BaseDEXProvider`
- [ ] Additional CEX plugins (e.g. MEXC, HTX, Bitget)
- [ ] DEX providers: EVM (Uniswap v3 quoter, 1inch/0x aggregator API), Solana (Jupiter)
- [ ] Gas oracle & bridge cost model for CEX↔DEX spreads
- [ ] Plugin contract test suite every adapter must pass

### 3.5 Stage 3 Exit
- [ ] Dashboard e2e tests; `/audit-risks` on auth & controls
- [ ] Docs: "How to add an exchange plugin" guide in README
