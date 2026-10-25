# Network transfer-time table review (crypto-specialist, 2026-10-25)

Reviewed: `src/nexus/engine/network_times.py` (card `docs/tasks/tool/T3-alert-data-model.md`).
Scope: read-only public metadata. No code edited.

## Verdict
**Usable after corrections.** Most fast-chain values are fine (they are dominated by processing, not
chain time). Wrong or too optimistic: POLYGON, LTC, ADA, ZKSYNC, OP, BASE, MANTLE, SOL (slightly).
Several inline comments carry outdated block times / confirmation counts (BEP20 "~3 s", TRC20
"19-20 conf"). Important networks seen on venues and in `tests/fixtures/networks/codes.json` are
missing (STATEMINT, SUINEW, TON2, OPBNB, SONIC, SEIEVM, CELO, KAVAEVM, PLASMA, SCROLL, STARKNET,
RON, XTZ, ...). Two design issues (see "Design notes"): Binance's public `estimatedArrivalTime` is
not trustworthy for BTC, and withdrawal processing should be a separate term.

## Sources (all accessed 2026-10-25)
- **[K]** KuCoin public `GET https://api.kucoin.com/api/v3/currencies/{USDT,USDC,ETH,BTC,LTC,DOGE,XRP,ADA,DOT,ATOM,BCH,ETC,XLM,ALGO,ZK,MNT}`:
  `preConfirms` = confirmations to credit, `confirms` = to unlock for withdrawal. No key needed.
- **[B]** Binance public `https://www.binance.com/bapi/capital/v1/public/capital/getNetworkCoinAll`:
  `minConfirm` (credit), `lockConfirm` (unlock), `estimatedArrivalTime`, `estimatedUnlockTime`
  (minutes). No key needed. Undocumented web endpoint, may change without notice.
- **[O]** OKX: no public per-network table; confirmations are only in authenticated
  `GET /api/v5/asset/currencies` (`minDepArrivalConfirm`, `minWdUnlockConfirm`). Secondary only:
  eco.com "USDT confirmation time by network 2026" (TRC20 19, ERC20 64, BEP20 15, Polygon 100;
  unverified) and OKX 2023 press note cutting ETH deposits 64 -> 32 blocks
  (fintechfutures.com/?p=15309451).
- **[Y]** Bybit: help center (bybit.com/en/help-center/article/Bybit-Deposit-FAQ) publishes no
  table; per-chain counts only on the logged-in deposit page and authenticated
  `GET /v5/asset/coin/query-info` (`confirmation`, `safeConfirmNumber`).
- **[G]** Gate: public `GET /api/v4/wallet/currency_chains` has no confirmation counts; deposit
  page only. Not verified.
- Block times: BNB Chain blog "Fermi hard fork accelerates BSC to 0.45 second block times"
  (active 2026-01-14); docs.ton.org/ecosystem/subsecond (Catchain 2.0, ~0.4 s blocks since
  2026-04-09). Others from general chain knowledge (ETH 12 s, Polygon PoS ~2 s, Arbitrum ~0.25 s,
  OP/Base/Mantle 2 s, Solana slot ~0.4 s, BTC 10 min, LTC 2.5 min, DOGE 1 min, ADA ~20 s, ETC ~13 s,
  XMR ~2 min, Cosmos Hub ~6 s, Polkadot Asset Hub ~6 s).

So credit-confirmation figures are verified for **Binance and KuCoin only**; OKX/Bybit/Gate values
need a read-only key (OKX/Bybit) or manual deposit-page check. Treat the table as a
Binance/KuCoin-calibrated estimate.

## Per-network review (chain time to deposit CREDIT, excluding exchange withdrawal processing)

| Code | Block time | Credit confs B / K (others) | Chain time typical | Pessimistic note | Old | New |
|---|---|---|---|---|---|---|
| ERC20 | 12 s | 6 / 12 (OKX 32-64 [O]) | 1-3 min | OKX 64 conf ~13 min; gas spikes delay inclusion | 5 | 5 |
| BEP20 | 0.45 s | 1 / 15 (OKX 15 [O]) | <1 min | rare; reorg-free fast finality | 2 | 2 |
| POLYGON | ~2 s | 200 / 200 | ~7 min | 300 conf unlock; congestion 15 min | 5 | **8** |
| ARB | ~0.25 s | 120 / 120 | <1 min | unlock B 36 min, K 1900 blocks | 3 | 3 |
| OP | 2 s | 25 / 100 | 1-3.5 min | unlock B 30 min | 3 | **4** |
| BASE | 2 s | 1 / 100 | 0-3.5 min | unlock B 40 min | 3 | **4** |
| AVAXC | ~1-2 s | 12 / 32 | <1 min | - | 2 | 2 |
| ZKSYNC | ~1 s | 1 (B est 5 min) / 100 | ~5 min | **B unlock 1440 min (24 h)**, K 16000 conf | 3 | **5** |
| LINEA | ~2 s | n/a | ~2-3 min (est.) | unverified | 5 | 5 |
| MANTLE | 2 s | n/a / 100 | ~3.5 min | K unlock 700 conf | 3 | **5** |
| KAIA | 1 s | 1 / n/a | <1 min | - | 2 | 2 |
| CRO | ~1 s | n/a | ~1 min (est.) | unverified | 2 | 2 |
| TRC20 | 3 s | 1 / 3 (OKX 19 [O]) | <1 min | - | 2 | 2 |
| SOL | 0.4 s slot | 1 / 200 slots | 0-1.5 min | congestion drops txs, resubmits | 1 | **2** |
| XRP | 3-5 s | 1 / 12 | <1 min | memo/tag errors are the real risk | 2 | 2 |
| XLM | ~5 s | 1 / 1 | <1 min | memo required | 2 | 2 |
| TON | ~0.4 s (2026-04) | 1 / 1 | <1 min | memo required | 2 | 2 |
| NEAR | ~0.6 s | 1 / 5 | <1 min | - | 2 | 2 |
| APT | <1 s | 1 / 1 | <1 min | - | 2 | 2 |
| SUI | <1 s | 1 / 1 | <1 min | - | 2 | 2 |
| ALGO | ~2.8 s | 1 / 8 | <1 min | - | 2 | 2 |
| HBAR | ~3-5 s finality | 1 / 1 | <1 min | memo required | 2 | 2 |
| EOS | ~0.5 s | 1 / n/a | <1 min | rebranded Vaulta (A) 2025, memo | 2 | 2 |
| ATOM | ~6 s | 10 / 15 | 1-1.5 min | memo required | 4 | **3** |
| DOT | ~6 s | 3 (relay) / n/a | <1 min | relay chain DOT transfers being phased out, see STATEMINT | 4 | 4 |
| ADA | ~20 s | 30 (B est 11) / 30 | ~10-11 min | 20 min under load | 10 | **12** |
| BTC | 10 min | 1 / 1 (unlock 2-3) | 10-20 min incl. mempool wait | 60+ min with fee spikes; B `estimatedArrivalTime`=1 is wrong | 30 | 30 |
| LTC | 2.5 min | 3 (B est 13) / 12 | 13-30 min | 40 min | 15 | **25** |
| DOGE | 1 min | 6 / 12 | 6-12 min | 36 conf unlock (K, B) | 15 | 15 |
| BCH | 10 min | 2 / 3 (BCHN) | 20-30 min | 60 min | 30 | 30 |
| ETC | ~13 s | 70 (B est 14) / 300 | 15-65 min | K 300 conf ~65 min; B unlock 500 conf ~115 min | 30 | **45** |
| XMR | ~2 min | 3 (B) / n/a | 6-25 min | 10-block spend lock; most venues 10-15 conf | 25 | 25 |

### Missing networks to add (seen on these venues / in fixture codes)

| Code (after normalize) | Evidence | Chain time typical | New |
|---|---|---|---|
| STATEMINT (Polkadot Asset Hub) | B 3 conf; K 30 conf (~3 min); DOT/USDT/USDC | 1-3 min | 4 |
| TON2 | K chainId `ton2` (USDT); same chain time as TON | <1 min | 2 |
| SUINEW | Gate, many assets in fixture; same chain time as SUI | <1 min | 2 |
| OPBNB | B 1 conf, est 5 min; fixture | ~5 min (B est) | 5 |
| SONIC | B 1 conf (unlock 5); K 10 conf | <1 min | 2 |
| SEIEVM | B 1 conf; fixture | <1 min | 2 |
| CELO | B est 7 min, unlock 22 | ~7 min | 8 |
| KAVAEVM | B 1 conf; K 20 conf (~2 min) | <2 min | 3 |
| PLASMA | B 1 conf; K 20 conf | <1 min | 2 |
| SCROLL | B 1 conf, **unlock 154 min** | ~1 min | 3 |
| STARKNET | B est 3 min, **unlock 180 min** | ~3 min | 5 |
| MANTA | B 1 conf, unlock 134 min | ~1 min | 3 |
| RON | B 12 conf, est 12 min | ~12 min | 12 |
| XTZ | B 4 conf; K 10 conf (~8 s blocks) | ~1-1.5 min | 3 |
| XDC | K 64 conf (~2 s) | ~2 min | 3 |
| CFX | K 500 conf (~0.5 s) | ~4 min | 5 |
| KCC | K 20 conf (~3 s) | ~1 min | 2 |
| MONAD | K 120 conf (~0.4 s) | ~1 min | 2 |
| WORLDCHAIN | B est 3 min, unlock 30 | ~3 min | 4 |
| AVAX (X-Chain) | B network `AVAX` 1 conf | <1 min | 2 |
| LIGHTNING | B `LIGHTNING`, K `btcln` 1 conf | seconds | 1 |
| SEGWITBTC | B separate network next to BTC | as BTC | 30 |

## Code / alias issues
1. **Comments wrong**: BEP20 "~3 s blocks" -> 0.45 s since 2026-01-14; TRC20 "19-20 conf" is OKX
   only (B 1, K 3); POLYGON "64-128 conf" -> 200 at B/K; BTC "2-3 conf" -> 1 to credit, 2-3 to unlock.
   Docstring claims OKX/Bybit help pages were checked; they publish no such table (see [O], [Y]).
2. **BCHN** (KuCoin chain name for BCH): add alias `"BCHN": "BCH"` if ccxt does not already map it;
   verify with the collision test over `codes.json`.
3. **POL**: Binance displays Polygon as POL with network id MATIC (alias exists). If any venue emits
   network `POL` / `POLYGONPOS` / `MATICPOS`, add alias -> `POLYGON` (check collision test first).
   Do not confuse with the coin "MATIC (Polygon Old)" on Binance.
4. **Do NOT alias**: `AVAX` (X-Chain) vs `AVAXC`; `DOT` (relay) vs `STATEMINT`; `BTC` vs
   `SEGWITBTC`/`LIGHTNING`; `TON` vs `TON2`; `SUI` vs `SUINEW` (all coexist on one venue). Give them
   their own table rows instead (times are chain-level, so equal values are fine).
5. **EOS -> Vaulta**: the token was renamed A (Vaulta) in 2025; the network code may appear as `A`
   or `VAULTA` on some venues. Add a row only after it shows up in fixture metadata.
6. **FTM**: Fantom migrated to Sonic; FTM networks are mostly deposit-closed. Leave unlisted
   (unknown) rather than claim a time.
7. `KAIA` alias from `KLAY` is fine; `ZKSYNC2`/`ZKSYNCERA` -> `ZKSYNC` fine (K chainId `zksync2`).

## Exchange-side withdrawal processing (separate from chain time)
Not measured here (no keys, no withdrawals - ADR 0001). Qualitative, from venue help pages and
practice: automated withdrawals at Binance/OKX/KuCoin/Bybit/Gate usually broadcast within
**1-5 min**; first/large/unusual withdrawals go to risk review: **30 min to several hours**;
wallet maintenance shows as withdraw disabled/"busy". Gate and KuCoin have more frequent manual
reviews on small-cap tokens (anecdotal, unverified).
Recommendation: model it as a separate term, e.g. `WITHDRAW_PROCESSING_MIN = 3` (typical) shown as
"approx", instead of folding it into each network row. The "New" column above includes roughly
1-2 min of processing for fast chains (so a 2 means "<1 min chain + processing").

## Design notes for backend-lead
- **Exchange estimate sanity**: `arrival_source=exchange` beats the table. Binance's public
  `estimatedArrivalTime` is 1 min for BTC (1 conf, really ~10+ min) and 1 min for SOL/TRX etc.
  Use `max(exchange_estimate, table_value)` when both exist, or ignore exchange values below the
  table for PoW chains.
- **Unlock time matters for capital rotation, not arrival**: Binance zkSync Era unlock 24 h,
  Starknet 3 h, Scroll 2.5 h, Manta 2.2 h, ETC ~2 h, ARB 36 min. Funds are credited (can trade)
  but cannot be withdrawn again until unlock. Worth a later field (`unlock_min`) - both B and K
  publish it publicly.
- Live alternative: KuCoin `preConfirms` and Binance `minConfirm` are public, so arrival could be
  computed as `confirmations x block_time` per venue; then the table would store block times only.
  Not needed for T3.

## Paste-in table (replace the dict literal body)

```python
NETWORK_ARRIVAL_MIN: Final[dict[str, Decimal]] = {
    code: Decimal(minutes)
    for code, minutes in {
        # EVM chains and L2s (credit confs: Binance / KuCoin public metadata, 2026-10-25)
        "ERC20": 5,  # 12 s blocks, 6 (Binance) - 12 (KuCoin) confs; OKX up to 32-64
        "BEP20": 2,  # 0.45 s blocks since Fermi (2026-01), 1-15 confs
        "OPBNB": 5,  # Binance estimate 5 min
        "POLYGON": 8,  # ~2 s blocks, 200 confs (~7 min)
        "ARB": 3,  # ~0.25 s blocks, 120 confs
        "OP": 4,  # 2 s blocks, 25-100 confs
        "BASE": 4,  # 2 s blocks, 1-100 confs
        "AVAXC": 2,  # 12-32 confs
        "ZKSYNC": 5,  # Binance estimate 5 min; withdrawal unlock up to 24 h
        "LINEA": 5,  # unverified
        "MANTLE": 5,  # 2 s blocks, 100 confs (KuCoin)
        "SCROLL": 3,
        "STARKNET": 5,  # Binance estimate 3 min
        "MANTA": 3,
        "WORLDCHAIN": 4,
        "CELO": 8,  # Binance estimate 7 min
        "SONIC": 2,
        "SEIEVM": 2,
        "KAVAEVM": 3,
        "PLASMA": 2,
        "MONAD": 2,
        "RON": 12,  # Binance: 12 confs, estimate 12 min
        "KAIA": 2,
        "CRO": 2,  # unverified
        "KCC": 2,
        "XDC": 3,
        "CFX": 5,  # KuCoin 500 confs (~0.5 s)
        # fast non-EVM chains
        "TRC20": 2,  # 3 s blocks, 1-3 confs (OKX ~19)
        "SOL": 2,  # 0.4 s slots, 1-200 slots
        "XRP": 2,
        "XLM": 2,
        "TON": 2,  # ~0.4 s blocks since 2026-04
        "TON2": 2,  # KuCoin second TON chain, same chain time
        "NEAR": 2,
        "APT": 2,
        "SUI": 2,
        "SUINEW": 2,  # Gate, same chain time as SUI
        "ALGO": 2,
        "HBAR": 2,
        "EOS": 2,
        "AVAX": 2,  # Avalanche X-Chain (not AVAXC)
        "XTZ": 3,
        "ATOM": 3,  # ~6 s blocks, 10-15 confs
        "DOT": 4,  # relay chain
        "STATEMINT": 4,  # Polkadot Asset Hub, 3-30 confs
        "ADA": 12,  # ~20 s blocks, 30 confs
        # slow proof-of-work and legacy chains
        "BTC": 30,  # 10 min blocks, 1 conf to credit (2-3 to unlock) + mempool wait
        "SEGWITBTC": 30,
        "LIGHTNING": 1,
        "LTC": 25,  # 2.5 min blocks, 3 (Binance) - 12 (KuCoin) confs
        "DOGE": 15,  # 1 min blocks, 6-12 confs
        "BCH": 30,  # 10 min blocks, 2-3 confs
        "ETC": 45,  # ~13 s blocks, 70 (Binance) - 300 (KuCoin) confs
        "XMR": 25,  # 10-block spend lock, 3-15 confs
    }.items()
}
```
Also update the module docstring: sources are Binance/KuCoin public metadata (accessed 2026-10-25)
plus chain block times; OKX/Bybit/Gate not verified (key or deposit page needed).

## Remaining gaps
- OKX, Bybit, Gate credit confirmations unverified (needs read-only keys at U3, then read
  `minDepArrivalConfirm` / `confirmation`). Re-check the table then.
- LINEA, CRO, KAIA, XMR rows rely on block time only.

## Кратко (RU)
Таблица в целом годится, но часть значений занижена: POLYGON (5 -> 8 мин, биржи ждут 200 блоков),
LTC (15 -> 25), ETC (30 -> 45), ADA (10 -> 12), ZKSYNC/OP/BASE/MANTLE (+1-2 мин), SOL (1 -> 2).
В комментариях устаревшие данные (BSC теперь 0,45 с на блок, а не 3 с). Не хватает сетей, которые
реально встречаются на биржах: STATEMINT (Polkadot Asset Hub), TON2, SUINEW, OPBNB, SONIC, CELO,
SCROLL, STARKNET, RON и др. — готовая таблица для вставки выше. Подтверждения проверены только по
публичным данным Binance и KuCoin; OKX/Bybit/Gate без ключей проверить нельзя. Время обработки
вывода на бирже (обычно 1-5 мин, при ручной проверке — часы) лучше считать отдельно от времени сети.
Оценке «от биржи» Binance для BTC (1 мин) верить нельзя — брать максимум из оценки биржи и таблицы.
