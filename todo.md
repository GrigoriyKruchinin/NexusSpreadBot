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
- [x] `pyproject.toml` (uv, Python 3.12, `src/` layout, dependency groups: main / dev)
- [x] `uv.lock` generated
- [x] ruff config (line length 100, rule sets: E, F, I, B, UP, N, S, ASYNC, RUF, ANN, SIM, PT)
- [x] mypy strict config (+ pydantic plugin, sqlalchemy typing)
- [x] pytest config (`asyncio_mode=auto`, `integration` marker, coverage)
- [x] Root `Makefile` (lint, format, typecheck, test, test-cov, test-integration, check, up-local, down-local, ps-local, logs, migrate, revision)
- [x] `.env.example` with every setting documented
- [x] `pre-commit` config (ruff, mypy, end-of-file, detect-secrets)
- [x] `README.md` (English): overview, architecture diagram, quickstart

### 1.2 Modular Pydantic Settings
- [x] Base groups: `DatabaseSettings`, `RedisSettings`, `CelerySettings`, `TelegramSettings`, `LoggingSettings`
- [x] `ExchangeCredentials` per exchange (`SecretStr`, optional in V1) + `ExchangesSettings` (enabled list, symbols whitelist/blacklist)
- [x] `SpreadSettings`: `min_net_profit_pct=0.3`, `min_net_profit_usd=5`, `reference_notional_usd=1000`, `max_orderbook_age_ms`, `alert_cooldown_s`
- [x] Role-specific loaders: `MigratorSettings`, `SchedulerSettings`, `ScannerRoleSettings`, `AlertsWorkerSettings`, `MaintenanceWorkerSettings`
- [x] Unit tests: each role loader ignores/forbids unrelated secrets
- [x] Risk audit fixes: no secrets in validation errors, `.env` ignored in containers (`NEXUS_RUNTIME=container`), bounded freshness/fee settings, strong DB password, https-only Telegram URL
- [x] `.env.example` documents every setting (guarded by test)

### 1.3 Domain & Interfaces
- [x] Value objects (Decimal): `PriceLevel`, `OrderBook` (validated, timestamped), `Ticker`, `MarketInfo`, `NetworkInfo`, `AssetTransferInfo`; injectable `Clock`
- [x] Error hierarchy (`domain/errors.py`)
- [x] Interfaces: `IRestMarketData`, `IWebSocketOrderbook`, `IMarketMetadata` (markets, fees, transfer status), `BaseExchangeAdapter`, `BaseDEXProvider` (stub for V3), `INotifier`
- [x] Repository protocols (added with persistence, 1.6)
- [x] Exchange registry / factory (register adapters by name, no orchestrator changes on add)

### 1.4 Async CEX Connectors
- [x] Shared base: ccxt REST + ccxt.pro WS, error translation, bounded retries (no retry on rate limits), Decimal boundary parsing
- [x] `BybitAdapter`
- [x] `BinanceAdapter`
- [x] `OKXAdapter`
- [x] `GateIOAdapter`
- [x] `KuCoinAdapter`
- [x] Market metadata: lot steps, minimums, taker fees (account tier with keys, static-fee flag), deposit/withdraw status, network fees & contract addresses
- [x] Common symbol intersection & periodic metadata refresh (scanner, 1.7)
- [x] ~~Orderbook snapshots → Redis hot cache~~ — books are fetched on demand and evaluated in-process (no stale-cache risk); Redis is used for cooldowns & heartbeat
- [x] Adapter tests with recorded fixture payloads
- [x] Safety: runtime GET-only guard on authenticated ccxt clients + AST test against fund-moving calls (risk audit)
- [x] Log scrubbing of signatures/keys/tokens for structlog and stdlib records
- [x] Per-pair account taker fee via `fetch_trading_fee` on alert candidates (OKX; KuCoin markets already carry public per-pair fees), 6h cache, bounded retries — audited: SAFE TO PROCEED

### 1.5 Net Spread Engine (R) — audited: SAFE TO PROCEED
- [x] Depth walker: VWAP for buy (asks) / sell (bids) at reference notional; reject if insufficient depth
- [x] Fee model: taker fees on both legs, fee asset handling
- [x] Transfer cost model: cheapest common network withdrawal fee, deposit/withdraw availability check, network aliases, contract-address conflict detection
- [x] `NetSpreadEstimator`: gross spread → net spread (%, USD) with full cost breakdown
- [x] Staleness & clock-skew guard
- [x] Threshold filter (both % and USD) + ticker pre-filter (`CandidateFinder`)
- [x] Per-route alert cooldown / dedup (Redis `SET NX EX`, released when dispatch fails)
- [x] Unit tests with hand-computed scenarios (incl. edge cases: empty book, thin book, suspended withdrawals, symbol collision)

### 1.6 Persistence (PostgreSQL)
- [x] Async engine & session factory
- [x] Models: `MarketPair`, `SpreadSnapshot` (sampled), `SpreadEvaluation` (with cost breakdown), `AlertLog`, `ExchangeHealth`
- [x] Indexes for time-series queries; retention policy (snapshots, health, non-profitable evaluations)
- [x] Alembic setup + initial migration
- [x] Repository implementations + integration tests

### 1.7 Redis / Celery / Scanner — audited: SAFE TO PROCEED
- [x] Celery app (Redis broker), task routing: `alerts`, `maintenance` queues; role-scoped lazy settings + fail-fast at worker start
- [x] Beat schedule: retention cleanup (metadata/fee refresh runs inside the scanner, which owns exchange keys)
- [x] Alert tasks with retries (429 `retry_after`, infra autoretry) & idempotent alert log; stale alerts expire
- [x] Claim-before-send (SENDING row) to avoid duplicate Telegram messages on ack-late redelivery; event expiry
- [x] Scanner orchestrator (async: ticker sweep → candidates → per-route book fetch with deadline → estimator → DB → alert queue), exchange health with hysteresis, rate-limit pauses, heartbeat, graceful SIGTERM
- [x] WebSocket hot-set: stream books for recently profitable routes (bounded, TTL, resync on invalid book); WS-based alerts re-confirmed on REST — audited: SAFE TO PROCEED

### 1.8 Telegram Notifier
- [x] `TelegramNotifier(INotifier)` on httpx Bot API, HTML parse mode, 429 `retry_after`, token never in errors
- [x] Opportunity alert template: 🔀 pair, buy/sell exchanges, prices, gross vs net spread, fee/slippage/transfer breakdown, est. profit on $1,000, book age, blockquote summary
- [x] System alerts: exchange disconnect/reconnect, scanner start/stop (rendered in the alerts worker; scanner publishes structured events)
- [x] Escaping & snapshot tests of rendered messages; unverified-transfer and estimated-fee labels always shown

### 1.9 Docker (local)
- [x] Multi-stage `Dockerfile` (uv, non-root user, slim runtime, read-only rootfs compatible)
- [x] `docker-compose.local.yml`: postgres, redis, migrator, scanner, worker-alerts (Telegram), worker-maintenance, beat
- [x] Healthchecks for all services; `depends_on: condition: service_healthy` / `service_completed_successfully` (migrator)
- [x] Per-service environment exposing only required variables (one `.env`, YAML anchors per domain; enforced by `tests/unit/test_compose.py`)
- [x] Smoke test: stack up → all healthy → evaluations stored → alert task delivered to Telegram API (fake token → `Unauthorized`, no token in logs) → graceful stop
- [ ] User check: real Telegram token → start message + alerts received

### 1.10 Stage 1 Exit
- [x] `make check` green, coverage `engine/` ≥ 90 % (engine 95–100 %, total 92 %)
- [x] `/audit-risks` verdict SAFE TO PROCEED (config, engine, adapters, scanner/workers — all findings fixed or tracked here)
- [ ] 24h local soak run with real Telegram + read-only keys; review false-positive rate from DB (user) — superseded by the multi-day soak in 1.5.10

---

## Stage 1.5 — Signal Quality & Profit Validation (Read-Only, local)

**Why.** A 1.5 h keyless run (2026-10-18) produced 25 alerts. 21 of them were "dead" spreads:
- ZIL Binance→OKX and ONE OKX→Binance/KuCoin: the native networks are suspended on Binance,
  so the ~1 % spread persists for tens of minutes and cannot be closed;
- the scanner saw `transfer_status=unknown` and re-alerted every 10 min.

Only ERA showed short, plausible episodes. Stage 1.5 makes signals trustworthy and measures
the real profit potential (paper inventory) before any trading code (Stage 2).

**Decisions (confirmed by user):**
- add MEXC and Bitget; HTX excluded (sanctions);
- dead routes are excluded automatically, on the fly;
- one alert per episode, plus a re-alert on growth;
- full paper-inventory and rebalancing simulation;
- daily Telegram digest;
- `SPREAD_REQUIRE_VERIFIED_TRANSFER` default flips to `true`.

Hard rule unchanged: the bot never withdraws or transfers. Rebalancing is **simulated only**;
real rebalancing stays manual.

### 1.5.0 User guide → `docs/guides/stage-1-local-setup.md` (Russian, file only)
- [x] §3.6 MEXC, §3.7 Bitget read-only keys (Bitget passphrase), `.env` example, checklist; HTX not supported
- [ ] User: read-only keys for all 7 exchanges in `.env`

### 1.5.1 New exchanges: MEXC, Bitget (R) — audited: SAFE TO PROCEED
- [x] `MexcAdapter` (ccxt `mexc`) and `BitgetAdapter` (ccxt `bitget`, passphrase required) as registered `CcxtExchangeAdapter` subclasses:
  - follow `adapters/cex/okx.py` / `kucoin.py`;
  - set REST/WS depth limits and the static-fee flag;
  - WS public POST allowlist only if the exchange needs a public token endpoint.
- [x] Credentials:
  - `MEXC_API_KEY/SECRET`, `BITGET_API_KEY/SECRET/PASSPHRASE` in `ExchangeCredentials`, `.env.example` and compose (scanner only, enforced by `test_compose.py`);
  - `EXCHANGES_ENABLED` default gains `mexc`, `bitget`.
- [x] Recorded fixture payloads:
  - markets, tickers, order book, currencies with networks/statuses/fees, trading fee;
  - adapter tests.
- [x] Safety:
  - read-only guard on REST + WS clients;
  - the AST no-fund-movement test covers the new modules;
  - live public smoke (tickers, books, WS);
  - MEXC spot WS is protobuf: `protobuf==5.29.5` runtime dependency;
  - Bitget `extraWithdrawFee` (percentage on top of the flat fee) → network fee unknown.
- [x] README exchange list and architecture diagram updated.

### 1.5.2 Transfer-status coverage & network matching (R) — audited: SAFE TO PROCEED
- [ ] With keys, statuses come from ccxt `fetch_currencies` on all 7 exchanges. Verify each adapter yields:
  - per-network deposit/withdraw flags;
  - withdrawal fee;
  - contract address where published.
  - Done without keys: parsers checked against ccxt 4.5.88 (Bybit/OKX publish no contract in
    currency data; OKX `fee` falls back to `maxFee`); Gate/KuCoin/Bitget/Binance-public verified live.
  - **Pending (user keys):** live check for OKX, Bybit, MEXC via the coverage log.
- [x] Public fallback when a key is missing:
  - narrow `ITransferStatusSource`;
  - Binance public capital config (`GET /bapi/capital/v1/public/capital/getNetworkCoinAll`), GET-only, timeout, refreshed with metadata;
  - Gate.io / KuCoin / Bitget are already public through ccxt.
- [x] `NETWORK_ALIASES` (`engine/transfer.py`):
  - only proven synonyms;
  - chain migrations (e.g. ZIL vs ZILEVM, Zilliqa 2) stay distinct unless the contract/chain matches;
  - a table test built from recorded network codes of all 7 exchanges (Gate/KuCoin/Bitget/Binance recorded; OKX/Bybit/MEXC to add with keys);
  - two networks of one asset collapsing into one code → ambiguous (UNKNOWN), never overwritten;
  - OKX-style contract suffixes compared as suffixes (never `contract_verified`).
- [x] Per-exchange transfer-status coverage (% of scanned assets with known status):
  - logged after each metadata refresh;
  - included in the start event.

### 1.5.3 Alert policy: verified routes only (R) — audited: SAFE TO PROCEED
- [x] `SPREAD_REQUIRE_VERIFIED_TRANSFER` default `true`:
  - Telegram alerts only for `VERIFIED` transfer paths;
  - `UNKNOWN` evaluations are still stored (fully priced, status `transfer_unverified`,
    `meets_thresholds`) for the digest/episodes; they take no WS hot-set slots;
  - `UNAVAILABLE` excluded as before.
  - Update `.env.example`, compose and the guide table (+ note on stale local `.env`; effective value logged at start).
- [x] Keep the 5 % unverified gross cap and the 20 % hard cap.

### 1.5.4 Opportunity episodes (R) — audited: SAFE TO PROCEED
- [x] Table `opportunity_episodes` (Alembic migration):
  - route `symbol, buy_exchange, sell_exchange`;
  - `opened_at`, `last_seen_at`, `closed_at`;
  - `first/peak/last_net_usd`, `peak_net_pct`, `evaluations`;
  - `transfer_status`, `transfer_network`;
  - `alerted_at`, `alerted_net_usd` (re-alert baseline for 1.5.5), `realerts`, `close_reason` (`gap` / `quarantined` / `restart`), `survived_latency`;
  - partial unique index: one open episode per route.
- [x] `EpisodeTracker` (scanner):
  - a profitable evaluation opens or extends the route's episode;
  - the episode closes after `EPISODE_CLOSE_GAP_S` (default 60) without a profitable evaluation;
  - the evaluation row gets an `episode_id` FK.
- [x] Restart safety: on start, open episodes older than the gap are closed with `restart`. Close is idempotent.
- [x] "Survived latency" metric: was the route still profitable on a REST re-check ≥ `PAPER_LATENCY_MS` after detection?
- [x] Unit tests (open / extend / close / gap boundary / restart) and repository integration tests.

### 1.5.5 One alert per episode
- [x] The episode id becomes the alert dedup key and replaces the per-route Redis cooldown as the primary guard. `SPREAD_ALERT_COOLDOWN_S` remains as a floor (between first alerts of a route's episodes; Redis dedup key `alert:episode:{id}:{n}`; no episode → legacy route cooldown).
- [x] Re-alert only when the episode's peak net USD grows by ≥ `ALERT_REALERT_GROWTH_PCT` (default 50) over the last alerted value.
- [x] "Episode closed" message for alerted episodes: duration, peak $ / %, evaluations, survived-latency flag. Expires like system events.
- [x] Templates in `notifications/`, HTML-escaped, snapshot tests; alert-log claim semantics preserved.

### 1.5.6 Automatic quarantine of dead routes (R)
- [x] An episode open longer than `QUARANTINE_PERSIST_MIN` (default 15) **without** a `VERIFIED` transfer path quarantines the route for `QUARANTINE_TTL_H` (default 24). This is the ZIL/ONE pattern.
- [x] A route whose transfer status becomes `UNAVAILABLE` is quarantined immediately. The quarantine lifts early when the status turns `VERIFIED` on a metadata refresh.
- [x] Storage and status:
  - Redis key with TTL (source of truth for the scanner), mirrored to a DB table `route_quarantine` for the digest;
  - evaluations of quarantined routes are stored with status `quarantined` and never alerted
    (ticker-level records: quarantined routes take no candidate/order-book slots).
- [x] One expiring system event per quarantine start (route, reason, duration). No repeats.
- [x] Manual overrides `SCANNER_SYMBOLS_WHITELIST` / `SCANNER_SYMBOLS_BLACKLIST`: verify behaviour, document in the guide.
- [x] Unit tests: persistent-unverified → quarantined; verified persistent → not quarantined; expiry; early lift.

### 1.5.7 Paper inventory & rebalancing simulation (R)
- [ ] `PaperSettings` (`PAPER_` prefix):
  - `ENABLED=true`;
  - `USDT_PER_EXCHANGE=1000`;
  - `COIN_PER_ROUTE_USD=1000` (virtual coin inventory seeded at first-seen mid price, counted as capital);
  - `TRADE_NOTIONAL_USD=1000`;
  - `LATENCY_MS=2000`;
  - `REBALANCE_THRESHOLD_PCT=20` (of the starting balance);
  - `REBALANCE_DELAY_MIN=30`.
- [ ] `PaperPortfolio` (pure Decimal, new `simulation/` package, no I/O). On an episode open or re-alert it simulates the trade:
  - uses the REST re-check book taken after `LATENCY_MS`;
  - buys on A and sells on B with the same depth walker, fees and lot rounding as the estimator;
  - updates USDT and coin balances on both venues;
  - if a balance is short, skips the trade with reason `insufficient_usdt` / `insufficient_coin` / `rebalance_in_flight`.
- [ ] Rebalancing:
  - when a balance drops below the threshold, schedule a **virtual** transfer:
    - coin A→B, or USDT B→A;
    - via the cheapest `VERIFIED` network;
    - cost = the real withdrawal fee from metadata;
  - the funds are locked for `REBALANCE_DELAY_MIN`;
  - no network path → the route is blocked and reported.
  - **No real transfer: the simulation has no exchange access.**
- [ ] P&L split:
  - realized arbitrage profit;
  - rebalance costs;
  - inventory mark-to-market (price risk of held coins);
  - capital deployed;
  - return on capital.
- [ ] Persistence: `paper_trades`, `paper_rebalances`, `paper_balance_snapshots` (Alembic) + repositories.
- [ ] Unit tests with hand-computed scenarios:
  - trade;
  - insufficient balance;
  - threshold-triggered rebalance with fee;
  - lock period;
  - MTM after a price move;
  - no verified network.

### 1.5.8 Daily Telegram digest
- [ ] Celery beat task at `DIGEST_TIME` (default `09:00`) in `DIGEST_TZ` (default `Europe/Moscow`), configurable; `DIGEST_ENABLED=true`.
- [ ] Content for the last 24 h:
  - episodes: total / verified / unverified / quarantined;
  - episodes that survived latency;
  - median / max duration;
  - top-5 routes by peak net $;
  - paper P&L: trades, skipped by reason, realized $, rebalance $, MTM $, capital, ROC %;
  - quarantined routes;
  - exchange uptime;
  - transfer-status coverage per exchange.
- [ ] HTML template (escaped, `<b>`, `<blockquote>`, separators), snapshot test; repository aggregate queries with integration tests.
- [ ] Retention covers the new tables (`MaintenanceSettings`).

### 1.5.9 Coverage observability
- [ ] Per-sweep log/metrics:
  - routes per exchange pair;
  - candidates;
  - evaluated symbols;
  - quarantined count.
- [ ] Keep `SCANNER_MIN_QUOTE_VOLUME_USD=50000`; revisit the value with soak data.

### 1.5.10 Stage 1.5 Exit
- [ ] `make check` green; `/audit-risks` SAFE TO PROCEED for 1.5.1–1.5.7
- [ ] Multi-day soak (≥ 3 days) with read-only keys on all 7 exchanges; laptop must not sleep (or run on a VPS) (user)
- [ ] Go / no-go for Stage 2 from the digests:
  - target ≥ 5–10 **verified** episodes per day with net ≥ $5 that survive ≥ 2 s latency;
  - paper P&L positive after rebalance costs and MTM.

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
- [ ] No withdraw/transfer methods in any interface; startup check refuses keys with withdrawal permission (Binance apiRestrictions, Bybit query-api, OKX account/config perm, KuCoin api-key)
- [ ] Paper-trading / dry-run mode (default ON)

### 2.2 Risk Limits (R)
- [ ] Max position size per trade / per symbol / per exchange
- [ ] Daily loss limit & global kill switch (Redis flag + Telegram command)
- [ ] Max concurrent open executions; per-exchange circuit breaker on error rate
- [ ] Risk settings group isolated to executor container
- [ ] Separate Postgres roles per service (migrator=owner, scanner=insert/select, workers=limited)

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
