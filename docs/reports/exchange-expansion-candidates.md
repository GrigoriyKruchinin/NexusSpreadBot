# CEX expansion candidates (beyond the core five)

- Author: crypto-specialist
- Date / access date of all sources: 2026-10-23
- Request: user wants up to ~20 analysed spot CEXs (more venues = more spread opportunities) and
  will register / create read-only keys where possible (STATE.md, 2026-10-23 item (b)).
- Scope: desk research only. No API called, no account opened, no key used, no code changed.
- Excluded from ranking: current core `binance, bybit, gateio, kucoin, okx` (ADR 0002 / `CORE_EXCHANGES`).
  MEXC and Bitget are included with their status (ADR 0002: extension only).
- **Not legal advice.** KYC eligibility below is a desk check of public pages, mostly secondary
  aggregators, because most official ToS pages are JavaScript-rendered and could not be read by the
  agent. The lawyer must re-check every venue before the user registers (same process as G1).
- Legend: **[V]** verified on an official page or in ccxt source on the access date; **[S]** secondary
  source (aggregator / press); **[I]** inferred; **[U]** unverified (prior knowledge or not found).

## 1. Method

1. Candidate pool (~35): ccxt-supported spot CEXs with material spot volume on CoinGecko, plus venues
   commonly used by RF citizens abroad, plus the two extension venues (MEXC, Bitget).
2. Hard filters (any hit = excluded, section 5):
   - sanctions link (Garantex/Grinex, A7/A7A5, EU/UK/US designation of the venue);
   - venue that is illegal for an RF citizen to use (criminal exposure, e.g. "undesirable organisation");
   - venue closing / wound down in 2026;
   - official restricted list names **Russia** (as nationality or residence) or **Argentina**;
   - only domestic users served (KR, JP, TR, TH, ID, EU-only licences) or EU/EEA entity only
     (EU Reg. 833/2014 art. 5b, see G1.8);
   - no spot support in ccxt, or no ccxt support at all (custom adapter = deferred);
   - spot volume negligible (< ~100 BTC/24h).
3. Scoring of survivors: KYC likelihood (weight high) > ccxt quality (certified > pro > REST-only) >
   spot liquidity tier > read-only tooling (key introspection, transfer metadata) > reputation.
4. Data points:
   - ccxt flags: ccxt README table "certified / pro" (master branch) [V]; per-venue details from
     `ts/src/<id>.ts` in ccxt master [V] (endpoint paths, HTTP methods, `rateLimit`, order book caps,
     `fetchCurrencies` auth).
   - Liquidity: CoinGecko exchange ranking page, "24h Volume" column in **BTC**, read 2026-10-23 [V for
     the number shown; the number itself is exchange-reported and may include wash trading]. CoinGecko
     "Trust Score" given as a sanity check. Core venues for scale: Binance 84.4k, Bybit 21.7k, Gate 18.7k,
     OKX 18.6k, KuCoin 12.6k, MEXC 12.3k, Bitget 10.6k BTC.
   - Taker fee: base (lowest) tier spot taker; from ccxt static fee tables where noted [V for ccxt
     value, U for the live schedule]. Our scanner already reads account-tier fees when the key allows.
5. Our technical constraints that affect cost (from `src/nexus/adapters/cex/ccxt_base.py`):
   - `install_read_only_guard` blocks every non-GET request on authenticated clients. Venues whose
     **private read endpoints are POST** (Bitfinex, Kraken, LBank, Crypto.com, Bitstamp) cannot use a
     keyed call without a guard design change (exact-path POST allowlist for authenticated clients),
     which needs an ADR + security review. Public data on them still works.
   - Adapter must be ccxt `TICK_SIZE` precision mode (all venues checked below are TICK_SIZE [V]).
   - Key policy (A6) needs a GET self-introspection endpoint per venue, otherwise "attestation only".

### Engineering cost codes (per venue)

| Part | S (small) | M (medium) | L (large) |
|---|---|---|---|
| Adapter | subclass with ClassVars only (like `mexc.py`, ~25 lines + unit tests) | overrides needed (fees, passphrase, order book limits, transfer fallback) | no ccxt support / no spot in ccxt -> custom client |
| Key policy parser | GET endpoint returning scopes + IP list | GET endpoint with partial fields, or POST endpoint (guard change) | no endpoint -> user attestation only |
| Transfer metadata | public `fetchCurrencies` with per-network fee + flags | needs read-only key (GET), or fee missing in ccxt | not available in ccxt -> custom endpoint |

## 2. Ranked shortlist (20)

KYC column = eligibility of an **RF citizen residing in Argentina, no DNI yet**, from the venue's
restricted list. "RU" and "AR" = whether Russia / Argentina appear on that list.
Volume = CoinGecko 24h spot volume in BTC (trust score in brackets).

| # | Venue (ccxt id) | ccxt | Volume BTC (TS) | Taker (base) | RU listed | AR listed | KYC verdict | Key introspection | Transfer metadata | Cost A/K/T | Red flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | BingX (`bingx`) | **certified** + pro [V] | 5.6k (9) | ~0.1 % [U] | no [V] | no [V] | likely OK | `GET /openApi/v1/account/apiPermissions` [V path; fields U] | `capital/config/getall`, keyed GET [V] | S/S-M/M | 2024 hot-wallet hack (~$43-52M, reimbursed) [U] |
| 2 | XT.com (`xt`) | pro [V] | 13.9k (7) | ~0.2 % [U] | no [S] | no [S] | likely OK (all EU/EEA restricted, irrelevant) | `GET user/account/api-key` [V path; fields U] | public `wallet/support/currency` with `withdrawFeeAmount` [V] | S/S-M/S | 2024 hack (~$1.7M) [U]; trust 7 |
| 3 | Toobit (`toobit`) | pro [V] | 16.6k (9) | ~0.1 % [U] | no [S] | no [S] | likely OK (location-based list) [S] | `GET api/v1/account/checkApiKey` [V path; fields U] | public `api/v1/exchangeInfo` `chainTypes[]` fee + allow flags [V] | S/M/S | young venue (2022), Australian entity (Polish for EU) [S]; volume may be inflated |
| 4 | Bitfinex (`bitfinex`) | pro [V] | 2.2k (8) | 0.2 % [U] | no [S] | no [S] | likely OK (BVI entity, non-EU) [S] | `POST /v2/auth/r/permissions` [V] -> guard change | public `conf` endpoints incl. `pub:map:currency:tx:fee` [V] | S-M/M/S | Tether affiliate; 2016 hack history; order book limits only 1/25/100 [V] |
| 5 | Phemex (`phemex`) | pro [V] | 8.3k (7) | 0.1 % (ccxt static) [V] | no [S] | no [S] | likely OK | none found in ccxt [U] -> attestation | none in ccxt (`fetchCurrencies` no networks/fees) [V] | M/L/L | Jan 2025 hack (~$70-85M) [U] |
| 6 | LBank (`lbank`) | pro [V] | 21.8k (8) | 0.1 % (ccxt fallback) [V] | no (list) [S], **but** RU-registered accounts withdrawal-only since 2025-05-27 [S] | no [S] | **at risk** (depends on what "registered in Russia" means) | `POST supplement/api_Restrictions` [V] -> guard change | public `withdrawConfigs` [V] | M/M/S | all private reads are POST [V]; volume likely inflated |
| 7 | WEEX (`weex`) | pro [V] | 16.4k (9) | 0.1 % (ccxt default) [V] | no (only occupied UA regions) [S] | no [S] | likely OK; KYC optional on venue [S] -> do full KYC anyway (G4) | none dedicated (`GET api/v3/account/`) [V] -> attestation | public `api/v3/coins` `networkList` fee + flags [V] | S-M (passphrase)/L/S | "no-KYC" marketing, conflicting licence claims [S] |
| 8 | DigiFinex (`digifinex`) | **REST only** (no pro) [V] | 12.2k (8) | 0.2 % [V ccxt] | unknown [U] | unknown [U] | unverified | none found [U] -> attestation | public `currencies` `min_withdraw_fee` + status [V] | M (no WS)/L/S | `rateLimit` 900 ms [V] -> slow polling |
| 9 | Deepcoin (`deepcoin`) | pro [V] | 9.3k (7) | 0.15 % (ccxt static) [V] | no [S] | no [S] | likely OK; KYC optional for basic use [S] | none found [U] | none (`fetchCurrencies: false`) [V] | M (OKX-style, passphrase)/L/L | spot liquidity mostly derivatives-driven [U] |
| 10 | Poloniex (`poloniex`) | pro [V] | 8.4k (6) | 0.09 % (ccxt default) [V] | not in 2026 list [S]; 2018 sporadic RU suspensions [S] | no [S] | unverified | none found [U] | public `v2/currencies` fee + flags [V] | S/L/S | Justin Sun group; Nov 2023 hack (~$120M) [U]; trust 6 |
| 11 | MEXC (`mexc`) | **certified** + pro [V] | 12.3k (10) | 0.05 % (ccxt static) [V] | not in secondary lists [S]; **user: RF citizenship refused** | no [S] | **after DNI** (fact F2) | `apiKeyInfo` GET [V path; fields U] | `capital/config/getall`, keyed GET [V] | done (adapter exists)/M/K | VPN use -> freeze [S] |
| 12 | Bitget (`bitget`) | **certified** + pro [V] | 10.6k (10) | 0.2 % (ccxt static) [V] | **yes** - ToS "prohibited jurisdictions" Russia, Belarus, Kazakhstan [S]; user: refused | no [S] | **after DNI, and only if the rule is residence-based** | `GET /api/v2/spot/account/info` (`authorities`, `ips`) [path V; fields U] | public `v2/spot/public/coins` [V path] | done/S/S | 2026 account-specific service terminations reported [S] |
| 13 | Kraken (`kraken`) | pro [V] | 12.7k (10) | 0.26 % ccxt / ~0.40 % live [U] | **yes** - "Rusia" in prohibited regions [V]; RF citizens barred from new registration since 2022-10-14 [S] | no; Argentina served via CNV-registered branch [V] | **likely NO** (ask support in writing first) | `POST GetApiKeyInfo` [V] -> guard change | none in ccxt (fees not populated) [V] | M/M/L | private reads POST; 1 req/s public [V] |
| 14 | Bullish (`bullish`) | pro [V] | 11.5k (8) | [U] | [U] | [U] | unverified; retail onboarding restricted in many countries [S] | [U] | [U] | M/?/? | licensed (Gibraltar, BaFin, HK SFC) [S]; mostly BTC/ETH/USD(C) |
| 15 | Bitso (`bitso`) | **REST only** [V] | 0.33k (8) | [U] | [U] | n/a (Argentine PSAV) | **after DNI** [I] (local KYC) | [U] | [U] | M/?/? | low USDT liquidity; ARS pairs only interesting for fiat routes (out of scope) |
| 16 | BigONE (`bigone`) | REST only [V] | 7.8k (5) | [U] | [U] | [U] | unverified | [U] | [U] | M/L/? | July 2025 hack (~$27M) [U]; trust 5 |
| 17 | Coinbase Advanced (`coinbase`) | pro [V] | 15.6k (10) | **0.6-1.2 %** [V ccxt] | RF-linked screening since 2022 [S] | fiat services in AR ended 2026-01-31 [S] | unverified | `GET brokerage/key_permissions` [V] | not in ccxt visible code [U] | S/S/L | fee kills taker arbitrage at our size |
| 18 | Bitstamp (`bitstamp`) | pro [V] | 3.0k (9) | 0.40 % [V ccxt] | **yes** (residents) [S] | [U] | **likely NO** (EU/UK entities, art. 5b) [I] | none [U] | `POST fees/withdrawal/` [V] | S/L/M | private reads POST |
| 19 | Crypto.com Exchange (`cryptocom`) | **certified** + pro [V] | 5.5k (9) | ccxt static 0.5 % (live lower) [U] | **yes** - RU-tied accounts restricted 2022, citizens listed per RBC [S] | [U] | **likely NO** | none [U] | `private/get-currency-networks` POST [V] | S/L/M | all private reads POST [V] |
| 20 | Gemini (`gemini`) | pro [U] | 0.34k (8) | ~0.4 % [U] | [U] | [U] | unverified | [U] | [U] | M/?/? | low volume, high fee |

### Reading the table

- Only **BingX** combines "ccxt certified" with a plausible KYC path for the user today. All other
  certified venues are core, blocked for RF citizens (MEXC, Bitget, Crypto.com), dead on spot
  (HashKey Global: 2.9 BTC/24h) or DEX (Hyperliquid, WOOFi Pro; DEX is ADR 0006 seam only).
- Ranks 1-10 are the realistic expansion set; 11-12 wait for the DNI; 13-20 are listed for
  completeness and are **not recommended now** (KYC likely refused, POST-only reads, or fees too high).
- High reported volume on smaller venues (Toobit, WEEX, LBank, XT, DigiFinex) does not prove usable
  depth. Rank by measured depth after the public probe (section 6, step 1) before asking for keys.

## 3. Per-venue notes

### 1. BingX
- ccxt certified + pro [V]. Spot order book: any limit up to 1000 [V]; depth endpoints cost 1;
  `rateLimit` 100 ms with a 2 s rolling window [V]. Private reads are GET [V].
- Key policy: `GET /openApi/v1/account/apiPermissions` and `GET /openApi/v1/account/apiRestrictions`
  exist in ccxt (cost 5) [V]; response fields (permission list, IP whitelist) **[U]** - confirm on a real
  read-only key at U3. Sub-account key model has `ipAddresses` [S].
- Transfer metadata: ccxt `fetchCurrencies` uses `capital/config/getall` and returns `{}` without a key
  [V] -> keyed read needed (Binance-style).
- KYC: official Risk & Compliance Disclosure (latest update 2023-12-11) lists 21 restricted
  jurisdictions, neither Russia nor Argentina [V]; list is "including but not limited to" [V]. KYC must
  match main country of residence [S]. Lawyer to re-read the current Terms.
- Reputation: May 2024 hot-wallet incident, users reimbursed [U]; publishes PoR [U].

### 2. XT.com
- ccxt pro [V]; spot depth max 500 [V]; `rateLimit` 100 [V]; private reads GET [V].
- Key policy: `GET user/account/api-key` [V path]; fields [U].
- Transfer metadata: **public** `wallet/support/currency` + `currencies` with per-network
  `withdrawFeeAmount` [V] -> no key needed for fees/status (like KuCoin).
- KYC: restricted list (secondary, updated 2026-09-30) = all EU/EEA states, US, Canada, mainland China,
  Singapore, South Korea, Cuba, North Korea, Sudan, Venezuela, Crimea; not Russia/Argentina [S].
- Reputation: Nov 2024 hack (~$1.7M, covered) [U]; CoinGecko trust 7.

### 3. Toobit
- ccxt pro [V]; Binance-clone API (`exchangeInfo`, `PRICE_FILTER`/`LOT_SIZE`, `listenKey`) [V] -> cheapest
  adapter. `rateLimit` 20 ms (50 req/s) [V]. Depth limit semantics unclear ("1-10" todo in ccxt) [V] ->
  measure.
- Key policy: `GET api/v1/account/checkApiKey` [V path]; whether it returns scopes/IP is [U].
- Transfer metadata: public `api/v1/exchangeInfo` -> `chainTypes[]` with `withdrawFee`, `allowWithdraw`,
  `allowDeposit` [V].
- KYC: Toobit Global PTY LTD (Australia) is the contracting party for non-EU users (ToS copy dated
  2026-06-16) [S]. Restricted list (secondary, updated 2026-09-30): 39 countries incl. Belarus, US,
  Vietnam, Philippines, Türkiye; not Russia/Argentina [S].
- Reputation: young venue; CoinGecko trust 9 but volume vs. brand recognition looks high [I].

### 4. Bitfinex
- ccxt pro [V]; order book only 1/25/100 levels [V]; `rateLimit` 250 ms [V].
- **All private endpoints are POST** [V] (`/v2/auth/r/...`). Key policy `auth/r/permissions` therefore
  needs an exact-path POST allowlist for authenticated clients -> security decision (see Risks).
  Public data and transfer fees are fine: `fetchCurrencies` uses public `conf` endpoints
  (`pub:map:currency:tx:fee`, `pub:info:tx:status`) [V].
- KYC: secondary 2026-07-07 list = sanctioned states + occupied UA regions, US, Ontario, some UK
  residents; Russia and Argentina not named [S]. Entity iFinex (BVI), non-EU [S].
- Value: deep BTC/ETH vs USD/USDT books, different user base from Asian venues -> different prices [I].

### 5. Phemex
- ccxt pro [V]; no trading-fee fetch (static 0.1 %) [V]; `fetchCurrencies` without networks/fees [V].
  `rateLimit` 120.5 [V]. Key introspection and transfer metadata would need custom endpoints [U].
- KYC: secondary list of 45 entries (incl. Australia, UAE, UK, US, South Africa, South Korea,
  Canadian provinces); not Russia/Argentina [S]. Terms "Restricted Territories" s. 1.26, revised
  July 2025 [S]; sign-up requires confirming not a citizen **or** resident of a restricted territory [S].
- Reputation: Jan 2025 hot-wallet hack [U].

### 6. LBank
- ccxt pro [V]; `rateLimit` 20 [V]; public `withdrawConfigs` [V]. **Private reads are POST** [V]
  (key policy `supplement/api_Restrictions`, fees `supplement/customer_trade_fee`).
- KYC **at risk**: from 2025-05-27 accounts "registered in Russia" (also Ukraine, Kazakhstan) are
  withdrawal-only and new sign-ups there stopped [S]. Unclear if this covers RF passport holders
  living elsewhere. 2026 list (33 countries) includes Uruguay, Kyrgyzstan, Azerbaijan; not Russia or
  Argentina [S]. Needs a written answer from support before registering.

### 7. WEEX
- ccxt pro, spot supported [V]; public `api/v3/coins` with per-network fee + flags [V]; spot depth
  15 or 200 [V]; passphrase required [V]; no key introspection [V].
- KYC: not Russia/Argentina [S]; markets itself as KYC-optional [S]. For G4 the user must still do full
  own-name KYC. Reputation: conflicting licence claims across sources [S] -> lower trust.

### 8. DigiFinex
- ccxt REST only (no ccxt.pro) [V] -> our WS path (`watch_order_book`) unavailable; REST polling with
  `rateLimit` 900 ms [V] limits symbols per cycle. Public currencies with `min_withdraw_fee` and
  deposit/withdraw status [V]. KYC rules not found [U].

### 9. Deepcoin
- ccxt pro, spot via `instType=SPOT` [V]; OKX-v5-style API, passphrase [V]; no `fetchCurrencies`,
  no trading-fee fetch (static taker 0.15 %) [V] -> no transfer metadata = routes never VERIFIED.
- KYC: not Russia/Argentina per CoinMarketCap list [S].

### 10. Poloniex
- ccxt pro [V]; public `v2/currencies` with `withdrawFee`, `withdrawalEnable`, `depositEnable` [V];
  `rateLimit` 5 ms [V]. No key introspection [U].
- KYC: 2026 secondary lists do not name Russia/Argentina [S]; 2018 reports of sporadic suspension of
  RU users [S]. Reputation red flags: Nov 2023 hack, Justin Sun group (same group as HTX, which is now
  EU/UK-sanctioned) [U] -> sanctions-adjacency risk; lawyer must look.

### 11. MEXC (extension, ADR 0002)
- Adapter exists (`src/nexus/adapters/cex/mexc.py`). Certified [V]. Currency data keyed [V]. ccxt has
  an `apiKeyInfo` GET path [V]; fields [U].
- KYC: user fact F2 - RF citizenship refused; secondary restricted lists do not name Russia [S], so
  the refusal is likely a KYC-document policy. Re-check after DNI (G4.3). Do not work around.

### 12. Bitget (extension, ADR 0002)
- Adapter exists. Certified [V]. `GET /api/v2/spot/account/info` returns `authorities` and `ips` [U] ->
  probably a full key policy check.
- KYC: Bitget terms list **Russia, Belarus, Kazakhstan as prohibited jurisdictions** [S, The Defiant];
  2026 reports of account-specific service terminations [S]. Even with DNI, eligibility depends on
  whether the rule targets residence or nationality -> lawyer must read the clause.

### 13-20 (not recommended now)
- **Kraken**: official geographic-restrictions page (updated 2026-09-30) lists "Rusia" as a region it
  does not serve and names a CNV-registered Argentine branch (Payward Trading Limited - Sucursal
  Argentina) [V]; RF citizens barred from new registration since 2022-10-14 [S]. Only worth a written
  support question. Private reads POST [V]; no fees in ccxt currencies [V].
- **Bullish**: licensed, real volume, but retail onboarding limited and country list not found [S/U].
- **Bitso**: Argentine PSAV; KYC with local documents expected [I] -> after DNI. REST only.
- **BigONE**: trust 5, 2025 hack [U].
- **Coinbase Advanced**: good tooling (`GET brokerage/key_permissions` [V]) but base taker 0.6 %+ [V]
  makes taker-taker spreads unreachable.
- **Bitstamp**: Russia restricted [S], EU/UK entities [I], POST reads [V], taker 0.4 % [V].
- **Crypto.com**: restricts Russia-tied accounts since 2022 [S]; all private reads POST [V].
- **Gemini**: low volume, high fee [U].

## 4. MEXC / Bitget status summary

| Venue | Today | Trigger to revisit | What the lawyer checks |
|---|---|---|---|
| MEXC | no account (refused RF citizenship, F2) | Argentine DNI issued (F10) | current ToS + KYC document list; no workaround (G4.3) |
| Bitget | no account (refused, F2); ToS lists Russia as prohibited [S] | DNI issued | whether "prohibited jurisdiction" = residence or nationality; if nationality -> stays excluded |

## 5. Excluded venues (with reason)

| Venue | Reason | Source |
|---|---|---|
| **HTX** (ex-Huobi) | **UK sanctions (May 2026) on Huobi Global S.A. for support to A7 (Russia-linked payments firm, A7A5 issuer network) and Garantex**; EU 21st package (2026-07-23) transaction ban from 2026-08-23 | The Block; Yahoo Finance (L-S2, S3) |
| **EXMO** | EU 21st package transaction ban (with Rapira, BitPapa, Aifory Pro, WhiteBird, NoOnecrypto, Exnode) | The Block (S2) |
| Garantex / Grinex / Meer / A7A5 venues | sanctioned / A7A5 trading venues | Elliptic, Cointelegraph (S4) |
| **WhiteBIT** | declared "undesirable organisation" in Russia -> criminal exposure for RF citizens (user rule: legal penalties = stop); also bans Russian users | Decrypt (S5) |
| Bitrue | Russia restricted in ToS s. 6 (secondary) | Hummingbot, PureVPN (S6) |
| CoinEx | closing: spot stopped 2026-09-29, platform closes 2026-12-22 | Decrypt, Finance Magnates (S7) |
| BitMart | trading ended 2026-08-26, closes 2027-01-31 | Finance Magnates (S7) |
| BitMEX | closed 2026-09-23 | ryder.id, BitMEX (S7) |
| AscendEX | wind-down announced July 2026 | ryder.id (S7) |
| WOO X | spot volume 0.54 BTC/24h, trust 3 | CoinGecko (S1) |
| HashKey Global | spot volume 2.9 BTC/24h; pivot to derivatives (July 2026) | CoinGecko (S1), press |
| BloFin, BYDFi | no spot in ccxt (`spot: false`) | ccxt source (S8) |
| Upbit, Bithumb, Coinone, bitFlyer, Coincheck, BtcTurk, Bitkub, Indodax, Bitvavo, Bybit EU, Gate EU | domestic-only or EU entity | general / G1.8 |
| Ourbit, Bitunix, KCEX, CoinW, Hotcoin, Pionex, Tapbit, Biconomy, Azbit | not in ccxt (custom adapter = L); several show volume that looks inflated | ccxt README (S8), CoinGecko |

## 6. Suggested onboarding order (batches of ~5)

Principle: **public data first, keys later.** Order books and (for XT, Toobit, Bitfinex, WEEX,
DigiFinex, Poloniex, LBank) transfer fees are public, so a venue can join the scanner without any
account. Ask the user to register only where the public probe shows real depth and spread hits.
This also keeps the number of accounts (G4 exposure, KYC data spread) minimal.

**Step 0 (lawyer, before any registration):** re-read official ToS of batch 1 venues for Russia /
Argentina / nationality wording, as done for Gate (G1.2).

| Batch | Venues | Why | Keys? | Engineering (est.) |
|---|---|---|---|---|
| **1** | BingX, XT.com, Toobit, Bitfinex (public only), Phemex | best KYC likelihood + ccxt pro (BingX certified) + mid/high volume + public transfer data for 3 of 5 | BingX, XT, Toobit after probe; Bitfinex only after the POST-guard decision; Phemex = attestation only | 5 adapters S-M; key parsers: BingX/XT/Toobit S-M (fields to confirm at U3), Bitfinex M, Phemex none |
| **2** | WEEX, DigiFinex, Deepcoin, Poloniex, LBank | volume present, weaker tooling or KYC/reputation doubts | only if batch-1 probe proves added venues pay off; LBank only after written support answer; Poloniex only after lawyer sanctions-adjacency check | adapters S-M; DigiFinex REST-only; Deepcoin no transfer data; key policy mostly attestation |
| **3 (after DNI)** | MEXC, Bitget, Bitso; re-ask Kraken, Bullish | KYC blocked today | yes, if KYC passes without workaround | MEXC/Bitget adapters exist; key parsers S-M; Bitso/Kraken/Bullish M |
| not planned | Coinbase, Bitstamp, Crypto.com, Gemini, BigONE | fees, KYC or reputation | no | - |

Realistic total: core 5 + batch 1 (5) + batch 2 (5) + MEXC/Bitget = **17**; reaching 20 needs
batch 3 KYC to succeed. Note: currently 2 core venues are conditional (Bybit hold, Gate G1.2), so the
GO set may be smaller than the analysed set.

### Per-venue engineering checklist (applies to every new venue)
1. Adapter subclass + registry entry; set `max_order_book_limit` / `order_book_limits`,
   `static_market_fees`, `requires_passphrase` from section 3; unit tests with recorded fixtures.
2. Config: not in `CORE_EXCHANGES`; new group (e.g. `EXPANSION_EXCHANGES`) so GO numbers can be
   reported with and without it (same pattern as Bybit/Gate decision).
3. Key policy (A6): parser per venue (fail closed), or explicit "attestation only" entry.
4. Transfer metadata: confirm `fetchCurrencies` fee/flags mapping; venues without it stay UNKNOWN.
5. Symbol mapping check (ccxt `commonCurrencies` renames) against core venues, contract address
   match for same-ticker tokens (`_extract_contract`).
6. Rate-limit budget: total REST budget per cycle grows with venues; WS-only for REST-slow venues.

## 7. Open items to verify at U3 / by lawyer

- All "fields [U]" of key introspection endpoints (BingX, XT, Toobit, MEXC, Bitget).
- Official ToS re-read for batch 1 and 2 (most KYC rows are [S]).
- Live base taker fees (most are ccxt static values).
- Whether Toobit/WEEX/LBank volumes reflect real depth (public probe).

## Sources (all accessed 2026-10-23)

- S1. CoinGecko exchange ranking (pages 1-2): https://www.coingecko.com/en/exchanges ; https://www.coingecko.com/en/exchanges?page=2
- S2. HTX / EXMO EU 21st package: https://theblock.co/post/409668/eu-adds-htx-to-russia-sanctions-list-barring-transactions-starting-aug-23 ; https://www.crowdfundinsider.com/2026/07/293760-eu-includes-crypto-platform-htx-in-latest-russia-sanctions-package-imposing-transaction-ban-from-late-august/
- S3. UK sanctions on HTX operator (A7, Garantex): https://finance.yahoo.com/markets/crypto/articles/uk-sanctions-justin-sun-htx-161023593.html ; HTX restricted list (secondary): https://www.coinperps.com/ru/learn/htx-restricted-countries
- S4. A7A5 venues: https://www.elliptic.co/blog/the-rise-of-a7a5-the-ruble-stablecoin-now-transfers-1-billion-per-day ; https://cointelegraph.com/news/russian-ruble-stablecoin-a7a5-grinex-link-garantex-ft
- S5. WhiteBIT undesirable in Russia: https://decrypt.co/355941/russia-bans-whitebit-crypto-exchange-undesirable-ukraine-support ; https://www.coinperps.com/learn/whitebit-restricted-countries
- S6. Bitrue Russia restriction (secondary): https://hummingbot.org/exchanges/bitrue/ ; https://www.purevpn.com/crypto/bitrue-with-a-vpn/russia
- S7. 2026 closures: https://decrypt.co/378324/coinex-shutting-down ; https://financemagnates.com/cryptocurrency/coinex-cashes-out-hong-kong-crypto-exchange-to-shut-after-nine-years ; https://www.financemagnates.com/cryptocurrency/exchange/bitmart-winds-down-trading-as-exchange-closures-pile-up/ ; https://ryder.id/blogs/post/two-crypto-exchanges-shut-down-in-one-week-is-yours-next
- S8. ccxt README (certified/pro table): https://raw.githubusercontent.com/ccxt/ccxt/master/README.md ; ccxt sources: https://github.com/ccxt/ccxt/tree/master/ts/src (`bingx.ts`, `xt.ts`, `toobit.ts`, `bitfinex.ts`, `phemex.ts`, `lbank.ts`, `weex.ts`, `digifinex.ts`, `deepcoin.ts`, `poloniex.ts`, `mexc.ts`, `bitget.ts`, `kraken.ts`, `coinbase.ts`, `bitstamp.ts`, `cryptocom.ts`, `backpack.ts`, `blofin.ts`, `bydfi.ts`)
- S9. BingX Risk & Compliance Disclosure (latest update 2023-12-11): https://bingx.com/en/support/articles/11263347398927 ; BingX KYC tiers: https://bingx.com/en/support/articles/33457408621593 ; apiPermissions path (third-party lib): https://hexdocs.pm/bingex/Bingex.User.html
- S10. XT restricted list (secondary, updated 2026-09-30): https://www.cryptowinrate.com/xt-com-restricted-and-supported-countries-2026/
- S11. Toobit ToS copy (2026-06-16): https://tostracker.app/document/toobitcom-tos ; restricted list (secondary): https://cryptowinrate.com/ru/restricted-countries/toobit/
- S12. Bitfinex restricted list (secondary, 2026-07-07): https://www.datawallet.com/ru/криптовалюта/bitfinex-supported-and-restricted-countries
- S13. Phemex restricted list (secondary): https://www.cryptowinrate.com/phemex-restricted-countries ; https://www.datawallet.com/es/cripto/phemex-supported-countries
- S14. LBank Russia/Ukraine/Kazakhstan restriction 2025-05-27: https://news.bitcoin.com/fr/la-plateforme-dechange-de-crypto-monnaies-lbank-suspend-les-inscriptions-aux-emirats-arabes-unis-prevoit-de-retirer-les-utilisateurs-en-russie-et-en-ukraine/ ; 2026 list (secondary): https://cryptowinrate.com/zh-cn/restricted-countries/lbank/?p=1940
- S15. WEEX (secondary): https://www.datawallet.com/es/cripto/weex-restricted-countries ; https://www.fxempire.com/exchanges/weex
- S16. Deepcoin restricted list: https://coinmarketcap.com/exchanges/deepcoin
- S17. Poloniex: https://bitcoinmagazine.com/markets/poloniex-revised-terms-use-shutters-services-several-countries ; https://cointelegraph.com/news/poloniex-pressure-sees-startup-go-viral-to-win-funds-back ; https://www.cryptowinrate.com/poloniex-restricted-and-supported-countries
- S18. Bitget prohibited jurisdictions / terminations: https://thedefiant.io/news/cefi/bitget-to-end-services-for-some-users-with-account-specific-deadlines
- S19. MEXC restricted lists (secondary): https://www.coinperps.com/ru/learn/mexc-restricted-countries
- S20. Kraken geographic restrictions (updated 2026-09-30): https://support.kraken.com/articles/360001368823-geographic-restrictions ; 2022 RF citizen ban: https://forklog.com/en/kraken-bars-russian-users-from-registering-accounts/
- S21. Crypto.com RU restrictions 2022: https://www.theblock.co/post/177184/blockchain-com-and-crypto-com-restricting-russian-tied-accounts
- S22. Bitstamp (secondary): https://www.datawallet.com/es/cripto/bitstamp-restricted-countries
- S23. Coinbase Argentina service end (secondary): https://www.mexc.com/it-IT/news/406037
- S24. Bullish (secondary): https://coinmarketcap.com/es/exchanges/bullish/
- S25. BloFin restricted list (secondary): https://www.coinperps.com/learn/blofin-restricted-countries
- S26. Bitso Argentina (press): https://ground.news/article/bitso-chooses-incode-to-verify-the-identity-of-its-users-in-latin-america
