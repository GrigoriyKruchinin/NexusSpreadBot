<div align="center">

<img src="docs/assets/nexus-logo.jpg" alt="Nexus Spread Scanner logo" width="180">

# Nexus Spread Scanner

**An asynchronous multi-exchange arbitrage spread scanner for centralized crypto exchanges.**

It watches spot markets on Bybit, Binance, OKX, Gate.io and KuCoin, estimates the **net**
spread after taker fees on both legs, order-book slippage and network transfer cost, and
alerts you on Telegram. Every evaluation is stored in PostgreSQL for later analysis.

![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)
![ruff](https://img.shields.io/badge/lint-ruff-D7FF64)
![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/V1-read--only%20scanner-success)

</div>

> **Safety.** The bot never withdraws or transfers funds. Version 1 is read-only: every
> authenticated exchange client is wrapped in a runtime guard that blocks any non-GET request,
> and a static (AST) test forbids fund-moving calls in the source tree.

**Status:** Stage 1 (MVP: detector + alerts) implemented — see [todo.md](todo.md).
Supported exchanges: Bybit, Binance, OKX, Gate.io, KuCoin (spot, USDT/USDC quotes).

## Architecture

```mermaid
flowchart LR
    subgraph Exchanges
        BY[Bybit] & BN[Binance] & OK[OKX] & GT[Gate.io] & KC[KuCoin]
    end
    subgraph scanner [scanner container]
        AD[Exchange adapters<br/>ccxt, read-only guard] --> CF[CandidateFinder<br/>ticker pre-filter]
        CF --> BK[Order books<br/>per-route, deadline]
        BK --> NE[NetSpreadEstimator<br/>fees, slippage, transfer]
    end
    Exchanges --> AD
    NE -->|evaluations, snapshots| PG[(PostgreSQL)]
    NE -->|cooldown, heartbeat| RD[(Redis)]
    NE -->|alert task id| RD
    RD -->|alerts queue| WA[worker-alerts<br/>Telegram notifier]
    WA --> TG[Telegram]
    WA --> PG
    BT[beat] -->|maintenance queue| WM[worker-maintenance<br/>retention]
    WM --> PG
```

| Service | Role | Receives secrets |
|---|---|---|
| `migrator` | `alembic upgrade head`, then exits | Postgres |
| `scanner` | market data → net spread → DB → alert queue | Postgres, read-only exchange keys |
| `worker-alerts` | renders and delivers Telegram messages | Postgres, Telegram token |
| `worker-maintenance` | retention cleanup | Postgres |
| `beat` | schedules maintenance | none (broker URL only) |

Each container loads only its own settings class (`nexus.config.roles`) and receives only
its own variables from compose; this is enforced by `tests/unit/test_compose.py`.

### Net spread model

For a reference notional `N` (default $1,000):

1. Walk the **asks** on the buy venue for `N`, round down to the lot step, re-walk for the
   exact cost `C`.
2. Buy taker fee is charged in base; optionally subtract the cheapest common-network
   withdrawal fee (cost of rebalancing inventory — nothing is ever transferred).
3. Walk the **bids** on the sell venue for the remaining base (rounded down); sell taker fee
   is charged in quote → proceeds `P`.
4. `net = P − C`, `net% = net / C · 100`. An alert requires **both** `net% ≥ 0.3` and
   `net ≥ $5` (configurable).

Order books come from REST by default. Both legs of a route that just showed a positive net
spread join a bounded **WebSocket hot-set** (`SCANNER_WS_*`) and are evaluated on streamed books
while they stay fresh; otherwise the scanner falls back to REST.

False-positive guards: stale/skewed books, crossed books, exchange minimums, suspended
deposits/withdrawals (`transfer_unavailable`), a hard gross-spread cap, and a stricter cap
unless both the transfer path and the token contract are verified (ticker collisions).

## Quickstart (local, Version 1)

Setup guide (Russian): [docs/guides/stage-1-local-setup.md](docs/guides/stage-1-local-setup.md).

```bash
cp .env.example .env && chmod 600 .env   # Telegram token/chat id, DB password, optional keys
make up-local                            # build and start the stack
make ps-local                            # all services should be healthy
make logs s=scanner
```

## Development

```bash
uv sync
make check              # ruff + mypy --strict + unit tests
make test-integration   # repositories against PostgreSQL (POSTGRES_* env)
make revision m="..."   # new Alembic migration
```

Project layout:

```
src/nexus/
  config/         per-domain settings groups and per-container role loaders
  domain/         Decimal value objects, spread results, events, errors
  interfaces/     ABCs: market data, repositories, notifier, coordination
  adapters/cex/   ccxt-based adapters + registry (add an exchange here)
  engine/         depth walker, transfer routes, estimator, candidate pre-filter
  scanner/        orchestrator, universe, exchange health
  persistence/    SQLAlchemy models, repositories, Alembic migrations
  notifications/  Telegram notifier and HTML templates
  workers/        Celery app, tasks, dispatcher
  services/       alert delivery and retention use cases
  container.py    composition root
```

### Adding an exchange

Create `src/nexus/adapters/cex/<name>.py` with a registered
`CcxtExchangeAdapter` subclass (set `ccxt_id`, depth limits, passphrase requirement),
import it in `adapters/cex/__init__.py`, add its `<NAME>_API_*` variables to `.env.example`
and compose, and record test fixtures. No orchestrator change is needed.
