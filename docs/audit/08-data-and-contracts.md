# 08 - Data and contracts (read-only audit)

Scope: `src/nexus/persistence/*`, migrations, `interfaces/*`, `infra/redis_store.py`, retention, settings.
No database was queried; volume numbers are estimates from defaults and are marked `[unverified]`.
Severity: H/M/L. Confidence: H/M/L.

## 1. Schema inventory (Postgres, 6 Alembic revisions, linear chain)

Chain: `50378c407de2` (initial) -> `31d6ec08eba5` (fees_estimated) -> `cde4915a67be` (episodes) -> `230f6005f417` (quarantine + `unverified_since`) -> `df290430d1e4` (paper) -> `40c869df951f` (metadata stats).

| Table | Rows grow with | Indexes | Retention |
|---|---|---|---|
| `market_pairs` | markets (upsert by `(exchange,symbol)`) | unique `(exchange,symbol)` | none needed (bounded) |
| `spread_snapshots` | top-K (20) routes per sweep | `captured_at`, `(symbol,captured_at)` | 7 d |
| `spread_evaluations` | up to 30 candidates + parked rows per sweep | `evaluated_at`, `(status,evaluated_at)`, `(symbol,evaluated_at)`, `episode_id` | 30 d, but PROFITABLE kept forever |
| `opportunity_episodes` | per route episode | partial unique open route, `opened_at` | 90 d (closed only) |
| `alert_log` | per alert | unique `evaluation_id` | cascades from evaluations |
| `exchange_health` | one row per exchange call outcome per sweep | `(exchange,checked_at)` | 7 d (uses snapshot window) |
| `route_quarantine` | per quarantine | `started_at`, route | 90 d by `expires_at` |
| `paper_trades` | per paper execution | `executed_at` | none |
| `paper_rebalances` | per virtual transfer | `started_at`, `status` | none |
| `paper_balance_snapshots` | holdings x snapshots | `captured_at` | 7 d, keeps latest set |
| `exchange_metadata_stats` | exchanges per refresh (30 min) | `(exchange,captured_at)` | 7 d |

All money columns are unbounded `NUMERIC` (exact Decimal round trip, `models.py:36`). Naming convention is deterministic. Timestamps are `timestamptz`.

## 2. Findings

| # | Finding | Where | Evidence | Sev | Conf |
|---|---|---|---|---|---|
| D1 | `spread_evaluations` is the growth hotspot: about 60 columns, 4 indexes, written every sweep for every evaluated candidate, including non-profitable and parked (quarantined) routes. Estimate at defaults (10 s sweep, 30 candidates): up to roughly 260k rows/day, about 7-8M rows at 30-day retention, multi-GB with indexes. Each extra index multiplies write amplification | `models.py:90-138`, `service.py:374-377`, `groups.py:196-200` | `[unverified]` real volume depends on how many candidates pass the fee-bound filter | M | M |
| D2 | `ix_spread_evaluations_evaluated_at` is needed for purge but `(status, evaluated_at)` and `(symbol, evaluated_at)` are speculative (no query in repo filters by them except digest/purge). Candidate for drop or replace by a partial index `WHERE status='profitable'` | `models.py:94-98` | grep of queries in `repositories.py` | L | M |
| D3 | Purge indexes mismatch: `exchange_health` and `exchange_metadata_stats` are purged by `checked_at/captured_at` alone but only have composite indexes led by `exchange`, so the purge DELETE scans the table (no standalone time index) | `models.py:202,302`; `repositories.py:911-930` | | M | H |
| D4 | Retention purge runs all deletes in one transaction, unbatched, hourly: a first run after backlog (or after retention shrinkage) can lock/bloat heavily and hold a long transaction. No `VACUUM`/autovacuum tuning, no partitioning | `repositories.py:903-940`; `maintenance.py` | | M | M |
| D5 | Time-series tables (`spread_evaluations`, `spread_snapshots`, `exchange_health`) are good candidates for time partitioning (drop partition instead of DELETE) | schema | design recommendation | L | M |
| D6 | PROFITABLE evaluations are kept indefinitely and `opportunity_episodes` purge sets `episode_id` to NULL via `ON DELETE SET NULL`, which updates every referencing evaluation row (FK index exists, so ok) | `models.py:134-138` | | L | M |
| D7 | `paper_trades` and `paper_rebalances` have no retention; low volume, but unbounded | `repositories.py:892-940` | | L | H |
| D8 | `exchange_health` writes one transaction (one INSERT) per exchange call, outside the per-sweep batch; about 7+ small transactions per sweep, and failures inside the metadata load path add more. Should be batched per sweep | `service.py:810-835`, `repositories.py:613-633` | | L | H |
| D9 | Good: evaluations, snapshots, markets (1000/batch upsert), paper commit and metadata stats are batched in a single transaction each; paper commit is atomic | `repositories.py:150-230,471-509` | | info | H |
| D10 | Pools: scanner pool 5 + overflow 5 (`groups.py:34-35`, `db.py:27-34`). Concurrent writers are the sweep plus spawned latency/paper tasks; acceptable. No `pool_timeout`, no asyncpg `command_timeout`/`connect_timeout`, no `statement_timeout` or `lock_timeout`; a stuck DB blocks the sweep (and hence heartbeat) without a bound | `db.py` | | M | M |
| D11 | Celery tasks create a fresh NullPool engine per task (`container.py:199,219,233`): safe across event loops, costs a connection handshake per alert. Fine at current volume | `container.py` | | L | H |
| D12 | Alembic migrations are autogenerated (`# ### commands auto generated ###` left in), have downgrades, and integration tests run `upgrade head` (`tests/integration/conftest.py:35`). No `alembic check` / model-vs-migration drift test in unit suite | `migrations/versions/*`, `tests/integration/conftest.py` | `[unverified]` drift today | L | M |
| D13 | `alert_log.status` / `spread_evaluations.status` / `close_reason` / `reason` are free `String` columns without CHECK constraints or enum types; contract lives only in Python enums | `models.py:107,164,189` | | L | H |
| D14 | `symbol`, `exchange` strings repeated per row (no dimension tables); fine for scale, adds row width on the hot table | `models.py:100-107` | | L | M |
| D15 | `fees_estimated` has a `server_default`, but `taker_fee_is_default` and `active` in `market_pairs` do not; harmless | `models.py:60` | | L | H |
| D16 | Alert-claim contract: `claim` returns True only for new or FAILED; SENDING rows are never recovered (documented at `interfaces/repositories.py:170-177`). No reaper for stale SENDING rows | `repositories.py:559-577` | | L | H |
| D17 | Rows older than the retention window are only deleted if `maintenance` worker and `beat` run; no alert if purge fails repeatedly (no metric); `purge_old_rows` retries 3 times on infra errors only | `workers/tasks.py:143-150` | | M | M |

## 3. Interfaces / contracts versus code

| # | Finding | Where | Evidence | Sev | Conf |
|---|---|---|---|---|---|
| I1 | Interfaces are narrow and segregated: `IRestMarketData`, `IWebSocketOrderbook`, `IMarketMetadata`, `ITradingFeeSource`, `ITransferStatusSource`; there is no withdraw/transfer method anywhere (matches the safety rule) | `interfaces/market_data.py` | | info | H |
| I2 | `BaseExchangeAdapter` does not include `IWebSocketOrderbook`/`ITradingFeeSource`; the scanner discovers them with `isinstance` on ABCs (`streams.py:55-59`, `service.py:920,936`). Works because ABCs are nominal, but the capability contract is implicit, not registered or declared | `streams.py`, `service.py` | | L | H |
| I3 | `interfaces/repositories.py` imports `engine.candidates.RouteQuote` and `simulation.portfolio.*`, so ports depend on engine/simulation types | `interfaces/repositories.py:17-18` | | L | H |
| I4 | `interfaces/dex.py` is declared but nothing implements or imports it; `ITradeExecutor` mentioned in docstring does not exist yet | `interfaces/dex.py`, `market_data.py:3` | | info | H |
| I5 | Contract gap: `IRestMarketData.fetch_tickers` says "missing symbols are omitted", but the ccxt adapter treats an empty `symbols` as "all" (`if (wanted and ...)`) and always downloads all tickers regardless of the list | `ccxt_base.py:476-497` | harmless today, surprising semantics | L | H |
| I6 | Contract: `fetch_order_book` raises `ExchangeError` subclasses; `OrderBook` validation errors are converted to `ExchangeDataError` for REST/WS (`ccxt_base.py:558-559`), yet `streams.py:128` also catches `DataValidationError`, which cannot occur from the adapter; dead branch, but `scanner.service._evaluate` does catch `DataValidationError` | | | L | M |
| I7 | `OrderBook.streamed` flag + `received_at_ms`/`timestamp_ms` semantics (exchange ts vs local) are documented in the dataclass docstring; consumers rely on `min()` of both for age | `domain/models.py:36-82` | | info | H |
| I8 | Event payload contract between scanner and worker: `event_to_payload` / `event_from_payload` JSON dicts passed through Celery args (`dispatch.py`, `alerts.py:111`). Producer and consumer ship in one image, so versions match, but during a rolling restart a queued old-format payload can reach a new worker. No payload version field was found | `domain/events.py`, `workers/dispatch.py` | `[unverified]` (did not read all of `events.py`) | L | M |

## 4. Redis keys and pub/sub

| Key / channel | Type | TTL | Writer / reader | Notes |
|---|---|---|---|---|
| `nexus:cooldown:alert:{route_key}` | string `SET NX EX` | `alert_cooldown_s` (600 s) | scanner | atomic gate, released on dispatch failure |
| `nexus:cooldown:alert:episode:{id}:{n}` | string | 24 h | scanner | per-episode alert dedup |
| `nexus:cooldown:quarantine-announced:{route}:{reason}` | string | 7 d | scanner | announcement throttle |
| `nexus:heartbeat:scanner` | string | 120 s | scanner writes, `nexus healthcheck` reads | value = epoch ms |
| `nexus:quarantine:{route_key}` | string JSON `SET NX PX` | until expiry | scanner | read with `SCAN` + `MGET` every refresh |
| Celery broker (db 1) | lists/hashes (kombu) | task lifetime | scanner publishes, workers consume | unacked set + visibility timeout 1 h default |

| # | Finding | Where | Evidence | Sev | Conf |
|---|---|---|---|---|---|
| R1 | No pub/sub is used. The CLAUDE.md target ("redis.asyncio for hot orderbook cache / pub-sub") is not implemented: books are cached in process memory (`streams.py:_books`) only. Not a defect, a plan-vs-code divergence | grep `publish\|subscribe` empty | | info | M |
| R2 | `RedisQuarantineStore.active` runs `SCAN` over all `nexus:quarantine:*` keys; fine for tens of keys, but it is invoked on each refresh (`_refresh_quarantine` per sweep) and on every sweep with `count=500`. O(keys of whole keyspace) per sweep on a shared Redis | `redis_store.py:80-103`, `service.py:442-450` | `[unverified]` call frequency inside `QuarantineManager.refresh` | L | M |
| R3 | Key namespace `nexus:` is consistent; cooldown namespace and Celery use separate DBs (0 and 1) but the same instance and persistence settings (`appendonly yes`, `save 60 1000`) | `docker-compose.local.yml:31,50,140` | | L | H |
| R4 | Quarantine state lives in Redis (source of truth) and history in Postgres (`route_quarantine`); losing Redis resets quarantines and the 24 h per-episode dedup keys, causing a possible burst of repeated alerts. AOF mitigates | `redis_store.py`, `models.py:213` | | L | M |
| R5 | Only a local compose file exists in the repository; production Redis/Postgres configuration (maxmemory, auth, network exposure, backups) is not auditable from the repo | `docker-compose.local.yml` | `[unverified]` | M | M |
| R6 | Postgres port is published in the local compose (`ports:` under postgres, line ~129); acceptable for local, must not carry over to prod | `docker-compose.local.yml:129` | | L | M |
| R7 | No backup/restore procedure or `pg_dump` job found in repo | repo tree | `[unverified]` could live outside repo | M | L |

## 5. Recommendations (ordered)

1. Add a standalone time index (or drop the composite) so `exchange_health`/`exchange_metadata_stats` purges use an index; batch purge deletes (`LIMIT` loops or partition drop). (D3, D4)
2. Reduce `spread_evaluations` write volume: persist non-profitable evaluations sampled or only above a gross-spread floor; drop unused indexes. Measure real row counts first. (D1, D2)
3. Set `connect_args` timeouts (`command_timeout`, `timeout`) and `pool_timeout` on the async engine. (D10)
4. Batch `exchange_health` inserts per sweep. (D8)
5. Add a versioned payload field for Celery messages and an alembic drift check in CI. (I8, D12)
6. Add a metric or log alarm for `alert_log` rows stuck in SENDING and for repeated purge failures. (D16, D17)
7. Add production compose/IaC (or document it) with Redis `maxmemory`, auth and Postgres backups. (R5, R7)
