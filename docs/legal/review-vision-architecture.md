# Legal / compliance review — vision and target architecture (preliminary)

Date: 2026-10-23. Author: lawyer agent. Status: preliminary, for orchestrator and user.
**Not legal advice.** This is desk research from public sources by a non-lawyer agent. Every
point marked *unverified* must be confirmed by a human lawyer/accountant or an official source
before it is relied on for money decisions.

Reviewed: `CLAUDE.md`, `docs/product/vision.md`, `docs/architecture/target.md`,
`docs/decisions/0001,0002,0006,0007` (0003-0005 are technical, no legal content),
`docs/pipeline/intake.md`. `docs/legal/` was empty before this file.

Facts taken from the repo (not re-verified): user is a Russian citizen, lives in Argentina, has no
Argentine DNI yet (expected ~2027-04); cannot onboard bitget/mexc (ADR 0002). Core set:
binance, bybit, gateio, kucoin, okx. Stage 1 = public read-only data plus read-only keys for fee
and deposit/withdraw status. No order/withdrawal/transfer code (ADR 0001). DEX = seam on paper.

## 1. Verdict

**No blocker for Stage 1 and the iteration loop** (public/read-only market data, paper trading,
analytics, Telegram alerts to the user only). Nothing in the vision or architecture is unlawful
as written.

**Pre-GO gates (must be cleared before UF can say GO; any of them can turn into a blocker):**

| ID | Gate | Why it can block |
|---|---|---|
| G1 | KYC/residence on each core account is truthful and consistent (Argentina, not Russia; global entity, not an EU entity) | EU sanctions bar EU providers from custody for Russian nationals without EU/EEA/CH residence permit (Reg. 833/2014 art. 5b(2)-(3)); misdeclared residence = ToS breach = freeze risk with inventory locked |
| G2 | Server/VPS location is not a restricted jurisdiction for any core venue (at least: US, UK, Singapore, EU/EEA for binance.com since 2026-07-01, Canada, Hong Kong, sanctioned regions) | Access from a restricted location breaches ToS even for public data; for keyed/trading access it is a freeze trigger |
| G3 | Argentine tax position known (tax residency start date, rate, record keeping) and Russian tax/currency-control position known | Net-return GO number must be after tax; unknown tax = unknown cost (vision A3/A7) |
| G4 | No account in another person's name, no multi-accounting, no use of third-party KYC for bitget/mexc | Explicit ToS prohibition (e.g. OKX ToS cl. 9.1); fraud/AML exposure |

## 2. Findings on the vision (`docs/product/vision.md`)

| # | Item | Assessment | Change needed |
|---|---|---|---|
| V1 | GO criterion includes "no blocking legal verdict" | Correct. But "legal" is not yet defined as checkable items. | Recommend: GO requires gates G1-G4 above ticked in `docs/legal/` (a checklist file), not just "no blocker found". |
| V2 | "after every cost" list (section 3) omits **income tax** | Argentine tax on crypto gains (15 % schedular rate per ARCA for foreign-currency / foreign-source results, *rate selection unverified for this case*) is a real cost and changes the 2 %/month bar materially. | Add "income tax (or explicit statement that GO is pre-tax)" to the cost list. Owner: quant-analyst + user's accountant. |
| V3 | Scope "Out": HTX (sanctions), custody of others' money, selling signals | Good. Keep. | Also list: A7A5 and other sanctioned tokens; Garantex/Grinex; Convert-type endpoints (see T4). |
| V4 | Manual rebalancing (section 7, ADR 0001 unchanged) | Legally the lowest-risk option. Operational/AML risk remains: frequent deposits/withdrawals between exchanges trigger source-of-funds reviews, Travel Rule questions (Argentina PSAVs apply UIF travel rule, *Res. UIF 49/2024 — unverified*), temporary freezes. | Stage 2 guide must tell the user: same-name accounts only, keep withdrawal records, answer Travel Rule prompts truthfully ("own wallet/own account"). Model freeze/delay as a cost in quant scenarios. |
| V5 | Iteration loop (ADR 0007), e.g. "pre-funded two-sided inventory" | Lawful. Note it increases exposure to account freeze / exchange insolvency (vision A5). No legal change. | none |
| V6 | Pivot 1 portfolio | No legal issue. Do not publish API keys, account IDs, balances, KYC data; pick a LICENSE (open item). Naming exchanges is nominative use. | none |
| V7 | Pivot 2 analytics tool for traders | **Needs a legal opinion before any sale.** (a) exchange market-data redistribution limits (OKX ToS cl. 8.1 bars distributing/selling the Services; Binance data terms *not readable, unverified*); (b) giving trading signals/analysis to third parties for a fee may fall under Argentine capital-markets rules on investment advice (CNV, Ley 26.831 — *unverified applicability*); (c) consumer/tax registration. | Keep vision's caveat; add "data licence check per venue" as a precondition. |
| V8 | Pivot 3 research dataset | Aggregated, derived statistics (episode counts, durations, spread distributions) are lower risk than raw book redistribution, but each venue's ToS on data must be checked. | Publish only aggregates, no raw order-book dumps, until checked. |
| V9 | Pivot 4 funding-rate / DEX | Funding-rate implies derivatives — some venues restrict derivatives by residence (Argentina status *unverified*); Russian-national restrictions differ per product. DEX adds sanctions screening (section 4). | New legal review per pivot hypothesis. |

## 3. Findings on the architecture (`docs/architecture/target.md`)

| # | Item | Assessment | Change needed |
|---|---|---|---|
| A1 | Read-only keys in `scanner` container, withdrawals disabled, IP whitelist | Aligned with exchange security guidance. IP whitelist ties keys to the VPS IP -> VPS location matters (G2). | Devops guide: choose VPS region against each core venue's restricted list; record the check in `docs/legal/`. |
| A2 | Public data via official APIs (ccxt) | Using documented public REST/WS endpoints within rate limits is normal use. **Scraping the web UI would breach ToS** (typical "no automated access except via API" clauses). Exceeding rate limits -> suspension (OKX ToS cl. 5.9). | Security/backend to confirm no HTML/UI scraping exists (not checked here: code is out of my scope). Keep ccxt rate limiting on; architecture section 5 bounds already help. |
| A3 | `CORE_EXCHANGES` filter for GO analytics | Fine. bitget/mexc adapters using **public** data only are not a ToS problem by themselves; no account is needed. | none |
| A4 | Reserved Stage 2 executor | Must not use Binance **Convert API**: Binance states it "is not suitable for purposes including price arbitrage, high frequency trading" (source 8). Spot order API is the intended channel. Market-abuse clauses (wash trading, self-matching, spoofing; OKX ToS cl. 3.1(p), 4.13(b)) matter for executor design. | Add to section 7: "spot order endpoints only; no Convert/OTC/RFQ endpoints for arbitrage; no self-crossing; respect rate limits". risk-manager to include in `docs/risk/`. |
| A5 | Data retention (`paper_*`, `spread_*` purge 7-90 d) | Fine for Stage 1. For Stage 2, **orders/fills/transfers are tax records**: Argentine tax claims prescribe in 5 years for registered taxpayers (Ley 11.683 art. 56 — *unverified current text*). | Stage 2 executor tables: no purge; export path for the accountant. |
| A6 | Asset-identity registry (DEX seam) | Also a compliance tool: lets the universe exclude sanctioned assets (A7A5) and wrong-network deposits. | Add optional denylist field (`sanctioned: bool`) when the registry is built. |
| A7 | Telegram alerts, digest | Only to the user; no third-party audience. If a channel is ever made public, V7 applies. | none |
| A8 | DEX seam only | No current legal exposure. | See section 4 for the future review. |

## 4. ToS risk summary (CEX)

Representative clauses verified on OKX ToS (source 9); other venues assumed similar — *unverified*,
check each before Stage 2.

- **API usage / bots:** allowed via official API, subject to rate limits; abuse -> suspension.
- **Scraping public data:** use APIs, not website scraping. Public endpoints from a restricted
  country IP may return HTTP 451/403 and count as access from a restricted location.
- **Multi-account:** prohibited without express agreement (OKX cl. 9.1). Use official
  sub-accounts only. Never use relatives'/friends' KYC (e.g. to reach bitget/mexc now).
- **Arbitrage:** cross-exchange spot arbitrage on own funds is not a prohibited practice in the
  ToS reviewed; prohibited are manipulation, wash trading, front-running. Exception: Binance
  Convert API (A4).
- **Account freeze discretion:** broad (OKX cl. 7.6: suspend "at any time, in our sole
  discretion", may freeze assets). Inventory on 5 venues = 5 freeze risks; cap per-venue
  inventory in Stage 2 (risk-manager).
- **Russian nationals, per venue (dated or secondary sources, all *unverified as of today*):**
  - binance: 2022 rule exempted Russians abroad with proof of address from EU-sanction limits
    (source 2); Binance exited Russia in 2023 (*from memory, unverified*); binance.com stopped
    EU services after MiCA withdrawal, 2026-07-01 (sources 10-11).
  - bybit: global ToS lists Russian-occupied Ukrainian regions, not Russia; **Bybit EU** refuses
    Russian citizens even with EU residence (source 3). Bybit Global limits EEA access from
    2026-07-01 (source 12).
  - okx: product restrictions for Russia-verified users (2023), no general ban found (source 1).
  - kucoin, gate: no Russia ban found; only P2P bank restrictions (sources 4-5).
    **Superseded for gate by Addendum A** (Gate lists Argentina and Russia as Restricted Locations).
  - Russian nationality is a KYC risk factor; enhanced due diligence and sudden policy changes
    are likely. This is the single largest legal-operational risk for capital at GO.
- **Argentina registration of venues:** binance and bybit appear in the CNV PSAV register per
  secondary sources; okx/kucoin/gate not confirmed (source 6). Since RG CNV 1058/2025, foreign
  PSAVs serving Argentines "directly" must register via a local branch/company (source 7). The
  legal burden is on the venue, not the user, but an unregistered venue can be blocked or exit
  Argentina -> forced migration of funds. Registered PSAVs report client data to ARCA
  (RG 4614/2019 as amended — *unverified*), so activity on them is visible to the tax agency.

## 5. DEX / sanctions (for the post-GO DEX revisit; nothing to do now)

- EU 19th package (2025-10-23) bans EU persons from transactions involving A7A5 (source 13). The
  user is not an EU person, but EU-entity venues and many aggregators apply EU/OFAC lists.
- OFAC SDN address screening of counterparties/contracts; front-end and aggregator API ToS
  often restrict jurisdictions — to be checked per provider when DEX is revisited.
- Self-custody wallets and decentralised protocols without an identifiable provider are outside
  the CNV PSAV regime (source 7) — the user's own DEX activity is not a registration trigger.

## 6. Tax and personal-status notes (for a human accountant)

- Argentina: foreigners with permanent residence are tax residents from the start; with temporary
  residence after 12 months of stay (LIG art. 116, source 14). Crypto disposal gains of
  individuals: 5 %/15 % schedular (Argentine source) or 15 % (foreign source) per ARCA (source 15);
  Bienes Personales applies to crypto holdings (secondary source). High-frequency trading may be
  treated as a business (third category) — *unverified*.
- Russia: Russian citizens are currency residents; foreign-account notification and annual
  reports under 173-FZ may apply, with exemptions if > 183 days abroad (source 16, secondary).
  Russian tax residency depends on days in Russia (183-day rule). Whether a Russia-Argentina
  double-tax treaty is in force: *unknown*.

## 7. Questions for a human lawyer / accountant

1. From which month is the user an Argentine tax resident, and is the arbitrage income 15 %
   schedular foreign-source or business income?
2. Are crypto holdings on foreign exchanges subject to Bienes Personales for the user this year?
3. What Russian obligations remain (foreign-account notifications, ODDS reports, NDFL) given the
   user's days in Russia? Is there a Russia-Argentina tax treaty in force?
4. Is the user's KYC residence proof (without DNI) acceptable and correctly recorded at each core
   venue, and which legal entity holds each account?
5. If pivot 2 (paid analytics) is chosen: does it require CNV registration as an adviser, and
   what data licences are needed per venue?

## 8. Sources (accessed 2026-10-23)

1. ForkLog, "OKX restricts services for Russian citizens" (2023-06-19): https://forklog.com/en/okx-restricts-services-for-russian-citizens/
2. The Block, Binance EU-sanction measures for Russian users (2022-04-21): https://www.theblock.co/linked/142788/latest-eu-sanctions-force-binance-to-crack-down-on-russian-users
3. Komersant.ua, Bybit EU restrictions for Russians (undated): https://komersant.ua/en/kryptobirzha-bybit-slidom-za-bankom-revolut-zaprovadyla-obmezhennia-dlia-rosiian ; The Block on Bybit ToS restricted list: https://www.theblock.co/post/298758/bybit-seems-to-open-up-registration-and-authentication-to-chinese-users-report
4. ForkLog, KuCoin and OKX tighten P2P for Russians: https://forklog.com/en/kucoin-and-okx-tighten-p2p-trading-for-russians/
5. DataWallet, Gate restricted countries (secondary): https://www.coinperps.com/ru/learn/gate-io-restricted-countries
6. DiarioBitcoin, Binance in CNV PSAV register: https://www.diariobitcoin.com/sur-america/argentina/binance-se-registra-como-proveedor-de-servicios-de-criptomonedas-en-argentina/ ; CriptoNoticias PSAV list: https://www.criptonoticias.com/regulacion/argentina-alternativa-legalizada-operar-bitcoin/
7. Marval O'Farrell Mairal, RG CNV 1058/2025 and foreign PSAVs: https://www.marval.com/Publicacion/novedades-para-registrar-entidades-extranjeras-como-psav-17170?lang=es ; Beccar Varela: https://beccarvarela.com/novedades/resolucion-general-cnv-n1058-regulacion-de-proveedores-de-servicios-de-activos-virtuales-psav/
8. Binance Developers, Convert API introduction: https://developers.binance.com/en/docs/products/convert/Introduction
9. OKX Terms of Service (cl. 2.2, 3.1(p), 4.13(b), 5.9, 7.6, 8.1, 9.1): https://www.okx.com/help/terms-of-service
10. Binance blog, "Important Update for Our European Users": https://www.binance.com/en/blog/regulation/4457979419755346760
11. Yahoo Finance, Binance withdraws MiCA application in Greece (2026-06): https://finance.yahoo.com/markets/crypto/articles/binance-withdraws-mica-license-application-173752458.html
12. ForkLog, MiCA transitional period expires (2026-07-01): https://forklog.com/en/mica-transitional-period-expires-in-the-eu/
13. Simmons & Simmons, EU 19th sanctions package: https://www.simmons-simmons.com/en/publications/cmh3mkt82003kve38l89o55as/overview-of-eu-s-19th-sanctions-package-against-russia
14. Quinterno Fidanza, Argentine tax residency (LIG art. 116): https://quinternofidanza.com/blog/residencia-fiscal-argentina.html
15. ARCA, criptoactivos — impuesto a las ganancias: https://arca.gob.ar/economia-digital/criptoactivos/impuesto-a-las-ganancias.asp
16. private.law wiki, Russian currency residency reporting (secondary): https://wiki.private.law/en/russia-foreign-account-reporting
17. EU Reg. 833/2014 art. 5b(2)-(3) text as quoted by Luxembourg Ministry of Finance and Skadden FAQ: https://www.skadden.com/-/media/files/publications/2022/04/us-uk-and-eu-impose-new-sanctions-and-export-controls/faqssanctionsrussiacryptoassets_en.pdf (consolidated EUR-Lex text not checked — *unverified current wording*)

## Addendum A — 2026-10-23: per-venue account status (preliminary, not legal advice)

Trigger: new user facts (citizenship, KYC location, declared residence, Bybit hold). Facts and
item statuses live in [`go-gates-checklist.md`](go-gates-checklist.md) (F5-F10, G1.1-G1.9,
G4.2); sources L1-L12 are listed there (accessed 2026-10-23).

**Correction to section 4:** "kucoin, gate: no Russia ban found" is **no longer accurate for
gate**. Gate User Agreement (last updated 2026-07-22) cl. 2.5 lists both **Argentina and Russia**
among Restricted Locations (L5, *automated extraction — human re-read required*). Consequences:
gateio is likely outside service scope for an Argentina resident -> G1.2 `blocked` pending a
written answer from Gate; propose excluding gateio from the GO set (same rule as Bybit, G1.7).
Open point for the orchestrator/architect: `CORE_EXCHANGES` (ADR 0002) includes gateio; Stage 1
public data calls from Argentina may also count as access from a restricted location (G2.2).

| Venue | Assessment | Recommendation |
|---|---|---|
| binance | Russia-resident accounts remain under the 2022 sanctions regime (EUR 10,000 cap, withdrawal-only above; Binance said in 2023 limits apply in full; CommEX closed 2024 and Binance kept existing Russian users) — *2026 status unverified* (L2, L3). Declared residence Russia is stale since the user lives in Argentina. Binance provides an in-account residence change with proof of address, possibly a KYC reset (L1). One verified account per person (L4, secondary). | **Update residence on the existing account**; do not open a second one. New account only after the old one is closed with Binance's written consent. Not usable for Nexus until updated. |
| bybit | Hold of one transfer pending compliance is within Bybit's ToS discretion (typical source-of-funds review, L12 anecdotal). Russia, Argentina, Montenegro, Georgia, Armenia are not on Bybit's excluded list (L10). A non-Argentine declared residence matters for G1: data must be current and truthful, so G1.5 cannot be `done` until residence = Argentina (or Bybit explains it cannot be changed). | Stay in the single ticket; answer truthfully with source-of-funds material; ask for reason category, timeline, residence-update path. No new KYC, no new account (L11). Escalation beyond support: Q4a for a human lawyer. |
| kucoin | No Russia/Argentina restriction found (L7, secondary; official terms not readable). | Confirm residence field = Argentina. |
| okx | Neither Russia nor Argentina restricted (L8); Russia only for fiat payments; product limits for Russia-verified users; ToS duty to update data, no multi-accounts (L9). | Confirm residence field = Argentina; list restricted products. |
