# CLAUDE.md — Nexus Spread Scanner (`nexus-spread-bot`)

Multi-chain CEX/DEX arbitrage & spread scanner. Async Python, SOLID, fully dockerized,
Telegram notifications, FastAPI admin dashboard (V3).

## Language Policy (MANDATORY)

- **English:** all code, comments, docstrings, commit messages, `README.md`, architecture docs, agent/skill files.
- **Russian:** all interactive communication with the user (questions, explanations, CLI guides, summaries).
- **Exception:** user guides in `docs/guides/` are written in **Russian** (they are user-facing instructions).

## Hard Safety Rules (NON-NEGOTIABLE, confirmed by user)

1. **The bot never withdraws or transfers funds.** No code may call withdrawal, transfer,
   internal-transfer, sub-account-transfer, or address-management endpoints on any exchange.
   Exchange interfaces have no `withdraw`/`transfer` methods. Transfer *fee data* may be read
   (public/read-only metadata) for cost modeling only.
2. API keys: V1 read-only; V2 trade-only with **withdrawals disabled** and IP whitelist.
   The bot must refuse to start in trading mode if it can detect withdrawal permission on a key.
3. Inventory is pre-funded manually by the user on each exchange; the bot only alerts when
   rebalancing is needed.
4. Trading (V2) defaults to **paper/dry-run mode**; live mode requires an explicit setting.
5. Secrets never enter code, logs, Telegram, git, or chat.

## Workflow Gates

- Work strictly follows [todo.md](todo.md); never skip a stage.
- **Do not write application code until the user explicitly says "Start Implementation".**
- **User guides are saved as files, not written in chat.** Create/update a Russian Markdown guide
  in `docs/guides/` and give the user only a link plus a 1–3 line summary in chat:
  - **Before Stage 1:** `docs/guides/stage-1-local-setup.md` — read-only CEX API keys, Telegram bot via `@BotFather`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, local `.env` setup. No VPS content.
  - **Before Stage 2:** `docs/guides/stage-2-production-setup.md` — trade-only API keys (withdrawals DISABLED, IP whitelist), VPS setup, Docker Engine, production secrets.
  - **Before Stage 3:** `docs/guides/stage-3-dashboard.md` — admin password hash generation, dashboard access.
- Any change touching spread math, order execution, risk limits, secrets, or exchange credentials: run `/audit-risks` (delegates to the `risk-critic` agent) before considering it done.

## Autonomous Delivery Loop (agent owns the full cycle)

After the "Start Implementation" gate, for every todo.md item (or small coherent group of items)
the agent performs the whole loop itself without asking for confirmation:

1. **Implement** the item (code + tests + `.env.example`/docs updates).
2. **Verify:** `/check-code-quality` and `/run-tests` must be fully green
   (ruff format/check, mypy strict, pytest). Items marked `(R)` additionally need `/audit-risks`
   with verdict `SAFE TO PROCEED`.
3. **Tick** the completed item(s) `[x]` in `todo.md`.
4. **Ship:** run `/ship` — commit (Conventional Commits, English) and `git push origin main`.
5. Continue with the next item.

Rules:
- Never commit or push red code. If checks cannot be made green, stop and report to the user.
- Never commit `.env`, secrets, keys, or generated artifacts; review `git diff --cached` before committing.
- Never `--force` push, never `--no-verify`, never rewrite pushed history.
- One commit per todo item / logical unit; the `todo.md` tick goes into the same commit.
- If push fails (auth, non-fast-forward), stop and report; do not attempt destructive fixes.
- Stop and ask the user only for: missing secrets/keys, stage transitions that require a new guide,
  `BLOCKED` risk verdicts, or decisions that change trading behavior/thresholds.

## V1 Product Decisions (confirmed by user)

| Parameter | Value |
|---|---|
| Target CEX (V1) | Bybit, Binance, OKX, Gate.io, KuCoin (spot) |
| Alert threshold | net profit **≥ 0.3 %** AND **≥ $5** (both must hold) |
| Reference notional for depth/slippage | **$1,000** |
| Admin credentials (V3) | `.env` only: `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` (bcrypt). Never in code/chat. |

All of these are configurable via settings, never hard-coded.

## Tech Stack

- Python **3.12**, dependency management with **uv** (`pyproject.toml`, `uv.lock`).
- `pydantic` v2 + `pydantic-settings` (modular, per-container settings).
- PostgreSQL + SQLAlchemy 2.x (AsyncIO, `asyncpg`) + Alembic.
- Redis + Celery (beat + workers); `redis.asyncio` for hot orderbook cache / pub-sub.
- Exchange connectivity: `ccxt` (async, `ccxt.pro` WebSocket) behind our own adapter interfaces.
- Telegram: `aiogram` 3.x (HTML parse mode).
- FastAPI + Chart.js (V3).
- Quality: `ruff` (lint + format), `mypy --strict`, `pytest` + `pytest-asyncio`.

## Commands

> Targets are created in Stage 1 (`Makefile`). Until then they do not exist.

```bash
uv sync                       # install deps (incl. dev group)
make lint                     # ruff check .
make format                   # ruff format . && ruff check --fix .
make typecheck                # mypy src tests
make test                     # pytest -q
make test-cov                 # pytest --cov=src/nexus --cov-report=term-missing
make check                    # lint + typecheck + test (run before every commit)
make up-local                 # docker compose -f docker-compose.local.yml up -d --build
make down-local               # docker compose -f docker-compose.local.yml down
make logs s=<service>         # follow logs of a service
make migrate                  # alembic upgrade head (inside migrator container)
make revision m="message"     # alembic revision --autogenerate
```

Single test: `uv run pytest tests/unit/spread/test_estimator.py::test_name -q`

## Project Layout (target)

```
src/nexus/
  config/          # Pydantic settings groups: DatabaseSettings, RedisSettings, CelerySettings,
                   #   TelegramSettings, ExchangeCredentials, SpreadSettings, DashboardSettings, ...
                   #   + per-role loaders (MigratorSettings, SchedulerSettings, ScannerSettings, ...)
  domain/          # Pure models & value objects (Decimal-based): Symbol, OrderBook, Fees, Opportunity
  interfaces/      # ABCs / Protocols: IRestMarketData, IWebSocketOrderbook, ITradeExecutor,
                   #   BaseExchangeAdapter, BaseDEXProvider, INotifier, repositories
  adapters/
    cex/           # bybit.py, binance.py, okx.py, gateio.py, kucoin.py  (one class per exchange)
    dex/           # V3+
  engine/          # NetSpreadEstimator, depth/slippage walker, fee & transfer-cost models
  execution/       # V2: TradeExecutor, risk limits, order state machine
  notifications/   # Telegram notifier, HTML templates, formatters
  persistence/     # SQLAlchemy models, async session factory, repositories, alembic/
  workers/         # Celery app, tasks, beat schedule
  scanner/         # Orchestrator: wires adapters → cache → estimator → notifier
  dashboard/       # V3: FastAPI app, auth, analytics API, static Chart.js UI
  container.py     # DI container / composition root
docs/guides/       # User-facing setup guides (Russian)
tests/
  unit/  integration/  fixtures/
```

## Code Style & Architecture Rules

- **SOLID is enforced, not aspirational:**
  - New exchange = new adapter class implementing interfaces + registry entry. Orchestrator/engine code must not change (OCP).
  - Narrow interfaces (ISP): market data, WS orderbook, and trading are separate protocols.
  - Depend on abstractions; wire concrete classes only in `container.py` (DIP).
- **Money math:** always `decimal.Decimal`, never `float`. Quantize only at presentation boundaries.
- **Typing:** `mypy --strict` must pass. No `Any` without justification comment. Use `Protocol`/`ABC`, `Final`, `Literal`, `TypedDict`/pydantic models at boundaries.
- **Async:** no blocking I/O in async code. Every network call has a timeout. Use `asyncio.TaskGroup` for fan-out.
- **Errors:** custom exception hierarchy in `nexus/domain/errors.py`; never swallow exceptions silently; log with context.
- **Logging:** structured (`structlog`), never log secrets/API keys/signatures.
- **Config:** each container loads only its own settings subset. A scanner container must not have DB-admin or trading secrets; the migrator must not have exchange keys; etc.
- **Secrets:** only via env / Docker secrets. `.env` is git-ignored; keep `.env.example` in sync with every new setting.
- **Telegram messages:** HTML parse mode, escape all dynamic values (`html.escape`), emojis + `<b>` + `<blockquote>` + separators. Templates live in `notifications/templates/`.
- Docstrings: Google style, on all public classes/functions.
- Line length 100; imports sorted by ruff (isort rules).

## Testing Rules

- Unit tests for every engine/estimator function with hand-computed expected values (fees on both legs, slippage, transfer cost).
- Adapters tested against recorded fixture payloads (no live network in unit tests).
- Integration tests (Postgres/Redis) marked `@pytest.mark.integration`, run via docker compose.
- Never mock the spread math itself in tests.

## Agents & Skills (`.claude/`)

| Name | Kind | Purpose |
|---|---|---|
| `implementation` | agent | Implements todo.md items following this file's rules |
| `risk-critic` | agent | Adversarial review of trading/financial/security risk (read-only) |
| `/check-code-quality` | skill | ruff + mypy + structural SOLID checks |
| `/run-tests` | skill | Runs the test suite and summarizes failures |
| `/audit-risks` | skill | Trading & security risk audit via `risk-critic` |
| `/next-task` | skill | Runs the full delivery loop for the next unchecked todo.md item |
| `/ship` | skill | Verifies green state, commits with Conventional Commits, pushes to `origin main` |
