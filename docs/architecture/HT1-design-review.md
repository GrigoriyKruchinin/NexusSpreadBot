> OBSOLETE (NO-GO 2026-10-25, ADR 0010): HT1 cancelled; kept as history. Linked spec/card/handoff were removed in T12 (see git history).

# HT1 design review: hedged-transfer paper strategy

- Author: architect, 2026-10-25. Inputs: `docs/quant/hedged-transfer-spec.md` (spec), card
  `docs/tasks/HT1-hedged-transfer-paper.md`, handoff `docs/handoffs/quant-to-backend-lead-2026-10-25.md`,
  `docs/legal/futures-access.md` s. 1, ADR 0001/0003/0004/0005, code at `cd714eb`.
- ADR draft: [`docs/decisions/0009-perp-market-data-and-hedged-paper-strategy.md`](../decisions/0009-perp-market-data-and-hedged-paper-strategy.md) (proposed).
- **Verdict: ACCEPT with changes** (C1-C14 below). The economics in spec sections 3-9 can stay as they are.
  The architecture needs the changes below, and the quant must make a small spec amendment for
  C1/C5/C6/C8 before step S11 (config). Steps S0-S10 can start now.

## 1. Findings from the code (why changes are needed)

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F1 | The daily digest and the GO report list **every** row of `paper_portfolios` as a spot-inventory set | `persistence/repositories.py:852-892` (`_portfolios`), `reports/go_repository.py:66-87` (`load_sets`) | Card item 7 says "runs reuse `paper_portfolios`". With that, `ht_*` would show up as a B15 set with 0 trades and P&L = minus rebalance fees. worker-alerts is **not** recreated at deploy, so its old digest code cannot filter the row out. |
| F2 | `PaperBook.sets` drives per-set top-N candidate selection and cap stats | `scanner/service.py:494-513`, `scanner/paper.py` `PaperBook.sets/members/record_alert` | An HT trader inside `PaperBook.traders` adds a set to candidate selection, `paper_cap_stats` and the D-08 watchdog. That changes how the 4 running sets behave and what they record. |
| F3 | The run hash covers `dataclasses.asdict(EstimatorConfig)` plus the strategy map | `scanner/paper.py` `definition()` / `_strategy_payload()`, `container.py:96-136` | Any new field on `EstimatorConfig`/`PaperConfig`, or a new key in `strategy`, restarts all 4 soak runs. |
| F4 | No test pins the current hashes | `grep config_hash tests/` | Card AC5 ("HT on == HT off") passes even if both hashes change by the same amount. It is too weak on its own. |
| F5 | The safety AST test forbids any call matching `.*transfer.*` | `tests/unit/test_safety.py:26-44` | `list_transfer_routes`, `transfer_duration(...)` and similar names fail CI. Name new call targets `transit_*`, or allowlist them with a security sign-off. |
| F6 | The sweep awaits `paper.on_sweep` inline. Alert-time paper trades run as `_spawn`ed tasks | `scanner/service.py:448-456`, `:762`, `:796-835` | If HT work sits on the sweep path, slow perp or DB I/O delays the soak sweep. |
| F7 | A failed metadata refresh sets `transfers[name] = None`, and the universe has no per-venue load time | `scanner/service.py:352-363`, `scanner/universe.py` | `METADATA_STALE` (45 min) needs a per-venue `transfers_loaded_at_ms`. The `None` case already maps to `TRANSFER_BLOCKED`, which is correct. |
| F8 | ccxt throttling is per client instance. Server-side limits are per IP (and per endpoint on OKX) | ccxt `enableRateLimit`, `ccxt_base._client_config` | Separate perp clients never queue behind spot calls in our process. Only the shared OKX endpoint buckets count (see 3). |
| F9 | The app connects as the schema owner. `nexus_ro` has default SELECT privileges | `scripts/sql/bootstrap_backup_roles.sql:37-38` | New tables need no grant migration, and backups include them automatically. |
| F10 | No service checks the alembic revision at runtime | `grep alembic src/` | Old worker containers keep working against a DB that has new tables (additive). |

## 2. Perp market-data boundary

**Port** `src/nexus/interfaces/perp.py` defines `IPerpMarketData(ABC)`. It is narrow and read-only, and it
has no account, order, leverage or margin methods:

```python
async def load_perp_markets(self) -> Sequence[PerpMarket]            # linear USDT perps only
async def fetch_perp_tickers(self) -> Mapping[str, PerpTicker]       # all, one request
async def fetch_perp_order_book(self, symbol: str, depth: int) -> OrderBook
async def fetch_funding(self, symbols: Sequence[str] | None) -> Mapping[str, FundingInfo]  # None = all
async def fetch_mark_klines(self, symbol: str, since_ms: int, until_ms: int) -> Sequence[MarkKline]  # 1 m, paged
async def fetch_funding_history(self, symbol: str, since_ms: int, until_ms: int) -> Sequence[FundingPayment]
async def fetch_leverage_tiers(self, symbol: str) -> Sequence[LeverageTier] | None    # None = not public
async def close(self) -> None
```

- **Domain types** `src/nexus/domain/perp.py`: `PerpMarket`, `PerpTicker`, `FundingInfo`, `MarkKline`,
  `FundingPayment`, `LeverageTier`. They are frozen and use Decimal throughout. `PerpTicker`/`FundingInfo`
  carry `received_at_ms`, stamped at request start (ADR 0005). `FundingInfo.rate` keeps the ccxt sign.
  `PerpMarket` holds `base`, `contract_size` (base units per contract), `amount_step` (contracts),
  `min_qty`, `max_leverage | None`, `mmr | None`, `active`, `delisting`. `OrderBook` is reused: its amounts
  are converted to **base units** inside the adapter, so the portfolio never sees contracts.
- **Adapters** `src/nexus/adapters/perp/`: `ccxt_perp.py` (base), `okx_swap.py`, `kucoinfutures.py`,
  `binanceusdm.py`. They use a separate `perp_registry`, not `exchange_registry`, because ADR 0004's core
  list is about spot venues. bybit/gateio perps are **not built in HT1** (C12).
- **Client hardening:**
  - The client config **never** includes `apiKey`/`secret`/`password`. The constructor takes no
    credentials parameter.
  - `install_read_only_guard(client, "<venue>:perp")` with an empty POST allowlist (HT1 uses no WS).
  - Options `fetchCurrencies: False` (otherwise ccxt calls private currency endpoints) and, on OKX,
    `fetchMarkets: {"types": ["swap"]}`.
  - Test (AC6): every client has a falsy `apiKey`, the guard flag is set, and a POST/DELETE through
    `request()` and through an implicit API method raises `ReadOnlyViolationError`.
- **Feed component** `src/nexus/scanner/perp_feed.py` `PerpFeed`. It owns the polling loop, the latest
  tickers/funding per venue, a per-venue backoff/health state (its own instance, so it never pauses spot
  venues and never emits spot `ExchangeDown` events: log + metric only) and the basis sampler (section 5).
  A perp outage on venue H disables HT entries that need H (`PERP_DATA_STALE`). It never touches the spot
  scanner.

## 3. Cadence and rate-limit budget (must not degrade the soak sweep)

Current spot load per venue: 1 all-tickers call per 10 s sweep, candidate books (up to 30 routes, WS
first, REST fallback, `max_concurrent_requests_per_exchange = 4`), metadata every 30 min.

HT polling (defaults from spec 13):

| call | cadence | binance (`fapi`, own host, own 2400 w/min IP budget) | okx (shared host, per-endpoint IP buckets) | kucoin (`api-futures`, own futures public pool ~2000 w/30 s) |
|---|---|---|---|---|
| all perp tickers | 30 s | bookTicker w5 -> 10 w/min | `/market/tickers` instType=SWAP: 1 / 30 s; bucket 20 / 2 s shared with spot's 1 / 10 s -> 0.13 / s of 10 / s = **1.3 %** | allTickers ~w5 -> ~10 w/min |
| funding + mark | 60 s | premiumIndex (all) w10 -> 10 w/min | `/public/mark-price` 1 / min; `/public/funding-rate` per instrument, candidates + open positions only, cache 60 s | contracts/active ~w10 -> 10 w/min |
| perp book | on alert (per H candidate, max 2-3) and on exit | depth(20/50) w2 | `/market/books` 40 / 2 s, shared with spot REST books | depth20 ~w5 |
| 1 m mark klines, 24 h | pre-check, incremental cache per (H, coin), 15 min | 1 call (limit 1500, w10), then 1 small call / 15 min | **100 rows per call -> 15 calls for a cold 24 h**, then 1 call / 15 min; bucket 20 / 2 s | ~3 calls cold (max ~500 rows), then 1 / 15 min |
| open-position liquidation kline check (C7) | 5 min per open position (max 4) | <= 0.8 / min | <= 0.8 / min | <= 0.8 / min |
| markets / tiers | 30 min (metadata cadence); tiers on pre-check, cache 1 h | exchangeInfo w1 | instruments + position-tiers | contracts/active (reused) |

- **Steady state per venue:** about 20-25 weight/min on binance fapi (~1 % of its own budget), ~1.3 % of the
  shared OKX tickers bucket, and ~1 % of the KuCoin futures pool. Peak after a burst of alerts on cold coins
  (OKX klines): ~15 calls spread over >= 1.5 s by the perp client's own throttle. No shared in-process queue
  with spot (F8).
- **Extra spot load from HT:** a post-latency REST book on A and B per alert (one fetch shared by all HT
  sets, section 4), an exit book on B per arrival/retry, and one shadow-exit book. These go through the
  scanner's existing `_fetch_book(..., allow_stream=False)`, so they respect the per-exchange semaphore and
  the 429 pause. At the observed alert rate (~60 first-alert episodes / 21 h, plus re-alerts) this is
  < 1 request/min per venue on average, against 6 tickers/min plus candidate books today.
- **Sweep latency impact: none by construction.** The sweep only calls the sync, in-memory
  `hedged.observe_spot(tickers)` (C4). No HT network or DB await happens on the sweep path.
- The published limits above are the architect's working numbers. Steps S2-S4 check each one against the
  venue documentation and write it into the adapter docstring. The 429 handling (pause the perp venue for
  `rate_limit_backoff_s`, no retry storm) is tested with the fake client.

## 4. Runtime wiring and coexistence with the 4 running runs (C2, C3, C4)

```
Scanner.sweep ──tickers──► PaperBook (4 spot sets, unchanged)
      │            └─────► HedgedBook.observe_spot(tickers)       (sync, memory only)
Scanner._alert_episode ──► _spawn(_paper_trade)                   (unchanged)
      └──────────────────► _spawn(HedgedBook.on_alert(AlertContext))  (new, only if HT enabled)
PerpFeed task (spawned in Scanner.run after paper.start; cancelled on stop)
      └── every 30/60 s ─► HedgedBook.on_perp_tick(now)  -> liquidation watch, funding, arrivals,
                                                            exits, USDT rebalances, 15-min snapshots
```

- **`HedgedBook`** (`scanner/hedged.py`) is a sibling of `PaperBook`, not a member. It holds one
  `HedgedTrader` per HT set (own lock, pools, positions, rows). It is **not** in `PaperBook.traders` and
  **not** in `[paper] venue_sets`. Candidate selection, cap stats, the D-08 watchdog and the digest stay
  exactly as they are.
- **Membership:** an HT set names its parent spot set (`excl_conditional`). `on_alert` runs for the HT set
  only if both legs are in the parent's venues **and** the parent held the route in its top-N this sweep
  (the same `portfolio_ids` the scanner already computes in `_membership`). HT therefore sees exactly the
  alert stream of `excl_conditional`.
- **Alert flow (one task per alert, shared by all HT sets):**
  1. Sleep `latency_ms`.
  2. In **one** `gather`, fetch the A and B spot REST books (through the scanner book fetcher) and the perp
     books of every eligible H.
  3. Price and run the pre-checks per HT set under its lock.
  4. Commit.

  No exchange I/O happens while an HT lock is held. Klines/tiers for the pre-check are prefetched during
  the latency sleep from the cache. If they are not ready when the books arrive, the attempt is skipped
  (C5), not delayed: a delay would age the books.
- **Read access:** the universe is read through a `Callable[[], MarketUniverse]`, because the universe
  object is replaced at each refresh. Spot books come through an injected `BookFetcher` callable, perp data
  through `PerpFeed` getters. HT never imports `Scanner`.
- **Isolation:** `HedgedBook` fan-out uses `gather(return_exceptions=True)` and re-raises non-`Exception`
  errors, as `PaperBook` does. A failing HT set is logged (`hedged_*_failed`) and disabled for the process
  when resume fails. Spot paper never sees HT exceptions.
- **The 4 runs resume unchanged (AC5, strengthened as C9):**
  1. S0 pins the **literal** definition hashes of `all`, `excl_conditional`, `excl_bybit`, `excl_gateio`
     computed from the committed `config/nexus.toml` at HEAD. Before deploy, the orchestrator cross-checks
     them with the config hashes in the host `make go-report` output (read-only).
  2. The golden test asserts the pinned values with HT on and with HT off.
  3. No new field on `EstimatorConfig`/`PaperConfig`, no new key in the spot `strategy` map, no change to
     `PAPER_*` settings. HT settings live in their own group, `PaperHedgedSettings` (`PAPER_HEDGED_*`,
     TOML table `[paper_hedged]`; the `PaperSettings` TOML table `[paper]` is unaffected).
- **Network metadata change is behaviour-neutral for the scanner (C10):** the new `NetworkInfo` fields are
  optional with default `None`. A regression test runs every existing network fixture and asserts that all
  pre-existing fields are equal before and after. `select_transfer_route` is unchanged. The new
  `list_transfer_routes` is a separate pure function.

## 5. Basis history (C6)

- Sampler: on every perp ticker refresh, for every (coin, B, H) where B is a spot venue of any HT set and H
  is an eligible hedge venue with an active perp, it takes `basis_rel = (bid_B - bid_H) / mid_H` from the
  latest spot ticker (sweep, <= 10 s old) and the new perp ticker. A sample is dropped if either side is
  stale or crossed. Dropped samples are not stored and are counted.
- Storage: a per-key ring buffer `array('q')` of **fixed-point integers** (1e-8 of the relative basis).
  This is exact and contains no float (conventions), and it is converted to Decimal on read. Capacity:
  720 samples (6 h / 30 s), one buffer shared by all HT sets. Universe: coins in
  `MarketUniverse.common_symbols` that have a perp on H. Upper bound ~1,500-5,000 keys x 5.8 KB =
  **9-29 MB**. A unit test asserts the key count x capacity bound and a startup log prints the key count.
  Without this, `deque[Decimal]` would need ~80 KB per key (up to ~400 MB).
- The quant must confirm one estimator detail: the spec uses the absolute basis (price units). Relative
  basis x the current perp price gives the same E_R and sigma_R to first order and is more stationary.
  Median/std are computed only at the pre-check, never per tick.
- After a restart the buffer is empty, so `BASIS_WARMUP` applies for 30 min, as the spec says. Rebuilding
  from klines is optional and out of HT1.

## 6. Persistence (additive migration, own namespace) (C2)

One Alembic revision (down_revision `b15a7c3e91d2`). It **only creates** tables and indexes. No existing
table, column, default or index changes.

| table | key columns | indexes / constraints | purpose |
|---|---|---|---|
| `paper_hedged_runs` | id, portfolio_id (varchar 32), parent_set, hedge_venues (text), started_at, capital_usd, config_hash (64) | ix (portfolio_id, started_at) | Run registry (same `ensure_run` semantics as `paper_portfolios`, separate table: F1) |
| `paper_hedged_positions` | id, run_id FK, portfolio_id, **position_key (unique)**, episode_id null, status, skip_reason null, symbol, base, buy_ex, sell_ex, hedge_ex, network, t0, arrives_at, shadow_at, closed_at; q_buy, q, q_h, w, a, b0, f0, b1, f1 (avg of exit fills), cost_usd, margin_usd, p_liq, mmr, leverage, tau_draw_min, tau_p50_min, tau_p95_min, stuck; S, R, D, U, P, F, L, RB, liq_loss, total; flags (late_exit, hedge_unpriced, forced) | ix (portfolio_id, t0); partial ix (run_id) WHERE status IN open states; unique position_key | One row per attempt (SKIPPED included) and per position; the final P&L lines |
| `paper_hedged_events` | id, position_id FK, kind (FUNDING, EXIT_FILL, LIQUIDATION, FORCED_EXIT, SHADOW_EXIT, ARRIVAL), at, qty, price, amount_usd, rate, note | **unique (position_id, kind, at)**; ix (position_id) | Append-only ledger: idempotent funding booking after a restart, partial exits, reconciliation (AC8) |
| `paper_hedged_rebalances` | the same columns as `paper_rebalances` + run_id | ix (portfolio_id, started_at), ix (portfolio_id, status) | Virtual USDT moves (separate from `paper_rebalances`: digest F1) |
| `paper_hedged_snapshots` | id, run_id, captured_at, equity, idle_usd, in_transit_usd, margin_usd, rebalance_usd, open_basis_mtm_usd, directional_mtm_usd | ix (portfolio_id, captured_at) | 15-min equity series (time-weighted report) |
| `paper_hedged_snapshot_pools` | snapshot_id FK, venue, usdt, margin_locked | pk (snapshot_id, venue) | Per-venue pools for restore |

- `position_key = sha256(run_hash, t0_ms, route, hedge_ex)[:32]` is made **before** insert. It seeds the
  transit draw (spec 7 says `position_id`; a DB id does not exist yet at draw time) (C13).
- Restore: latest snapshot + pools, open positions (partial index), in-flight HT rebalances, and the last
  booked event per position.
- Money columns use the existing `Money` (Numeric) type. Timestamps are timestamptz.
- Retention: none in HT1. The volume is small (~96 snapshot rows/day + attempts). Positions and events are
  GO evidence and are never purged. worker-maintenance stays untouched.
- Integration tests run on `nexus_test` only: upgrade/downgrade and a round trip of a full position.

## 7. Async correctness (target.md section 5 applied)

1. Every perp await is bounded: ccxt `timeout` (10 s) + an outer `asyncio.timeout`. Every DB call goes
   through the existing session timeouts.
2. Background work: `PerpFeed.run(stop)` and the `on_alert` tasks go through `Scanner._spawn` (bounded set,
   cancelled and awaited on stop). The loop catches `Exception` per iteration (logged, backoff) and
   re-raises `CancelledError`.
3. Lock discipline: the per-HT-set `asyncio.Lock` covers only simulate + commit. Network fetches happen
   before the lock. As in `PaperTrader.execute`, the state is deep-copied before mutation and restored if
   the commit fails ("memory never ahead of DB").
4. Order between `on_perp_tick` and `on_alert` is serialized by the same set lock. The commit time is
   strictly increasing (`_tick`), as in `PaperTrader`.
5. Clock: wall time only via `Clock` (book/ticker ages, funding times as exchange epoch ms compared with
   `Clock.now_ms`). Sleeps and timeouts use monotonic time. Never call `time.time()` in `scanner/` or
   `simulation/`.
6. Determinism: the RNG is `random.Random(int.from_bytes(sha256(...)))` per position. There is no global
   random, so unit tests need no sleeps (fake clock + fake perp port).
7. Restart / gap replay runs in order: liquidation scan over the gap (kline high >= P_liq) -> funding times
   in the gap from history (`events` unique key makes this idempotent) -> arrival -> exit on the first fresh
   books after the restart, flagged `late_exit` with the downtime (C14). The exit is never priced at the
   arrival-time books it did not see.

## 8. Failure modes (skip, never fabricate)

| failure | behaviour |
|---|---|
| perp tickers/funding stale on H (> 60 s / > 15 min) | entries needing H: `PERP_DATA_STALE`; others continue |
| klines/tiers not available at pre-check | skip with a distinct code (proposed `PERP_HISTORY_MISSING`, C5); no default sigma |
| perp book fetch fails or is stale at entry | `STALE_BOOK` (the existing guard covers all three legs) |
| transfer metadata missing/failed refresh (`None`) or older than 45 min | `TRANSFER_BLOCKED` / `METADATA_STALE` (F7: per-venue load time) |
| mark price missing at a poll | liquidation check uses `max(ask, last mark <= 60 s)`, plus the 5-min kline-high check (C7) |
| H perp unpriceable at exit / forced exit | position stays open, `hedge_unpriced` flag, funding keeps accruing from history; quant defines the final booking after `max_hold_h` (C8) |
| B deposit disabled at arrival | `ARRIVED`, re-checked each metadata refresh, `FORCED_EXIT` at 24 h (spec 7) |
| DB commit fails | memory rolled back to the deep copy; logged; retried next tick |
| resume fails for an HT set | that HT set is disabled for the process (logged); spot paper unaffected |
| perp venue 429 | that perp venue paused `rate_limit_backoff_s`; spot venue health untouched |

## 9. Changes required (verdict list)

| id | change | owner |
|---|---|---|
| C1 | Hedge venues per the legal verdict. Two HT sets are pre-registered: **`ht_excl_conditional`**, hedge = okx, kucoin (the GO hypothesis), and **`ht_excl_conditional_bn`**, hedge = binance, okx, kucoin (context only, eligible for GO only after G1.1a + G5.3). Both start on day 1 so the binance variant has history if the residence changes. bybit/gateio perps: none. The quant amends spec 2, 12, 13, 14 (recompute the prior without binance perps: T loses its deep hedge) and the Bonferroni note in 11 (2 HT hypotheses). | quant (spec), backend-lead (config) |
| C2 | Own persistence namespace (section 6). Do not reuse `paper_portfolios` / `paper_rebalances` (F1). | backend-lead |
| C3 | `HedgedBook` is a sibling of `PaperBook`, not in `traders`/`sets`/`venue_sets` (F2). | backend-lead |
| C4 | HT runs off the sweep path: sync `observe_spot`, an own `PerpFeed` loop, a spawned `on_alert`, and one gather for all legs (F6). | backend-lead |
| C5 | Pre-check history (24 h 1 m mark klines, tiers) is prefetched during the latency sleep and kept in an incremental cache (OKX pages 100 rows). Not ready -> skip `PERP_HISTORY_MISSING` (new code). | quant (code name), backend-lead |
| C6 | Basis buffer: fixed-point relative basis in `array('q')`, bounded key universe, memory test. The quant confirms the relative-vs-absolute estimator. | quant, backend-lead |
| C7 | Liquidation watch: `max(ask, mark)` at each poll **plus** a 1 m mark-kline high check every 5 min per open position (a 30 s poll misses wicks). | backend-lead |
| C8 | Rule for an unpriceable hedge at exit/forced exit: keep open + flag; the quant defines the final booking (e.g. at the last mark + 2 x slippage, flagged) for positions open > `max_hold_h` + 6 h. | quant |
| C9 | AC5 strengthened: literal pinned hashes (S0) + the pre-deploy cross-check with the go-report hashes; no new fields in the hashed configs. | backend-lead, orchestrator |
| C10 | `NetworkInfo` extension: regression test that pre-existing fields are identical on all fixtures; `select_transfer_route` untouched. | backend-lead |
| C11 | Safety test: add `list_transfer_routes` to `_ALLOWED_CALLS` (security sign-off); add `set_?leverage`, `set_?margin\w*`, `set_?position_?mode`, `(add\|reduce)_?margin` to `_FORBIDDEN_CALL`; name new model calls `transit_*`. | backend-lead, security |
| C12 | No bybit/gateio perp adapters in HT1 (YAGNI; the legal verdict is context only). | backend-lead |
| C13 | `position_key` (pre-insert, deterministic) seeds the draw instead of the DB id. | backend-lead |
| C14 | Late exit after downtime: exit on the first post-restart books, `late_exit` flag + downtime in the report. | backend-lead, quant (report) |

## 10. Step plan

The step list with acceptance criteria is in the HT1 card (section "Implementation steps (architect
review)"). Each step is one commit, keeps `make check` green and deploys safely on its own: HT stays
`enabled = false` in the TOML until S13.
