# Expansion venues — legal desk review (batch 1 and batch 2)

- Date: 2026-10-23 (all sources accessed this day). Author: lawyer agent.
- Scope: the ten venues of batches 1-2 in
  [`docs/reports/exchange-expansion-candidates.md`](../reports/exchange-expansion-candidates.md) section 6:
  BingX, XT.com, Toobit, Bitfinex, Phemex (batch 1); WEEX, DigiFinex, Deepcoin, Poloniex, LBank (batch 2).
- User profile used: **Russian citizen (RF passport), resident in Argentina, Argentine DNI not yet issued**
  (facts F5, F6, F10 in [`go-gates-checklist.md`](go-gates-checklist.md)).
- **Not legal advice.** Preliminary desk research by a non-lawyer agent. Every point needs a human re-read
  of the live terms at sign-up; items for a human lawyer are in section 6.
- Legend: **[V]** read on an official venue page today (via automated extraction, so quotes are short
  segments; a human should re-read before relying); **[V-snip]** official page, seen only as a search
  snippet; **[S]** secondary source (aggregator/press); **[U]** not found / unverified.

## 1. Summary verdicts

Verdict classes: **OK now** (register with own passport, full KYC, residence = Argentina) ·
**after DNI** · **do not register** · **public data only** (no account; public API only).
"Public data only" is also the default for *every* venue until the crypto-specialist's public probe shows
real depth (report section 6 principle) — the verdict says whether registration is legally acceptable
once it is worth it.

| Venue | Russia named? | Argentina named? | Basis of restriction | Key legal finding | Verdict |
|---|---|---|---|---|---|
| BingX | no [V] | no [V] | resident **or passport holder** of listed countries [V] | Russia not listed, so the passport clause does not bite; one account only; no commercial use of data | **OK now** |
| XT.com | no [S] | no [S] | residence/location [S] | official agreement not readable (403); secondary lists consistent | **OK now, conditional** on user reading the prohibited-countries clause at sign-up |
| Toobit | no (only occupied UA regions) [V] | no [V] | residence [V]; non-EU users contract with Future Planet PTE. Ltd. (Cayman) [V] | "programmatic trades without approval" prohibited -> fine for read-only, needs written approval before Stage 2 | **OK now** (read-only); Stage 2 needs approval |
| Bitfinex | no [S] | no [S] | citizens or residents of Prohibited Jurisdictions (Cuba, NK, Iran, Syria, Crimea) per Bitfinex Terminal ToS [V, other product] | main ToS JS-rendered, not read; low legal risk; keyed use blocked anyway by POST-guard decision | **public data only** now; registration acceptable later after human re-read |
| Phemex | no [V] | no [V] | **citizen, resident or located in** a Restricted Territory [V] | only contracting entity named is **Phemex Poland sp. z o.o.** (EU) [V] -> EU Reg. 833/2014 art. 5b risk for an RF national without EU residence; price data may be used only for trading *through Phemex* [V] | **public data only**; do not register until Phemex confirms in writing a non-EU entity |
| WEEX | **yes** - "Belarus, Russia and Russian-controlled regions of Ukraine" (ToS 2026-07-07) [V] | no [V] | **residence** ("Residents of the Excluded Jurisdictions...") [V] | contradicts the candidates report ([S] "no Russia"); residence-based so textually eligible, but KYC on an RF passport invites classification as Russia; weak reputation | **after DNI** (public data until then) |
| DigiFinex | not found [S/U] | not found [S/U] | unknown | official terms 403; only old (2020) entity text seen | **public data only** (re-check if probe pays off) |
| Deepcoin | no [S] | no [S] | residents [S] | official terms not readable; no transfer metadata anyway | **public data only** (re-check if probe pays off) |
| Poloniex | no [V-snip] | no [V-snip] | IP-level block of listed countries [V-snip] | not itself sanctioned, but **sanctions-adjacent**: same owner group as HTX (UK-designated May 2026, EU transaction ban from 2026-08-23); reported HTX reserve flows to Poloniex [S]; 2023 OFAC settlement [S] | **public data only; do not register / no funds** |
| LBank | **yes** - "+7 Russia, Kazakhstan: platform services unavailable" (notice effective 2025-12-27) [V]; accounts "registered in Russia" withdrawal-only since 2025-05-27 [S] | no [V] | phone region / registration country [V]; "national or resident" for sanctioned states [V] | Russia-linked users excluded in practice | **do not register** (public data only); re-ask after DNI |

No venue of the ten is on the Russian "undesirable organisations" list per search (only WhiteBIT among
exchanges, Prosecutor General 2026-01-23, Minjust list 2026-02-02) [S; registry not queried directly].
No venue of the ten appears in the EU 21st package crypto list or the UK HTX designation [S].

## 2. Per-venue notes

### 2.1 BingX
- Customer Agreement (latest update 2025-03-19), entity **Nieve Cruz PA Corporation** [V]:
  - s. 3: user is not "a resident or passport holder in any of the countries listed in the Restricted
    Jurisdictions within our Disclaimer"; not on sanctions lists [V]. -> nationality **and** residence test.
  - Disclaimer list (latest update 2023-12-11): Afghanistan, Burundi, Cambodia, Canada, CAR, China
    (Mainland), Cuba, DRC, Hong Kong, Iran, Laos, Macau, Myanmar, Netherlands, North Korea, Panama,
    Singapore, Somalia, UK, US (+ territories), Crimea/Donetsk/Luhansk. "subject to change and may vary from
    service to service" [V]. Same list in BingX Mini terms (2026-02-10) [V]. **Neither Russia nor Argentina.**
  - s. 5.1 one active account only; s. 8.3 multiple accounts for "illegal arbitrage" forbidden [V].
  - s. 8.3 prohibits "cracking the interface protocol and trading the program API", except the **public API**
    interface [V] -> use only documented API (ccxt does). s. 6.2 bans scrapers/robots on the site [V].
  - s. 6.1 no "resale or commercial use" of the Services; s. 6.2 commercial use of BingX data only with
    written consent; no redistribution [V] -> pivot 2 needs a licence.
- Note: Panama is on the list while the entity is "PA" — irrelevant to the user, flagged for completeness.
- Verdict **OK now**. The passport clause would become blocking if BingX ever adds Russia: re-check list at
  sign-up and on each ToS change.

### 2.2 XT.com
- User Agreement at xtsupport.zendesk.com returned HTTP 403; xt.com geo-block page names no countries [V].
- Secondary (xtguide.com 2026-07-29; cryptowinrate 2026-09-30): US, Canada, Mainland China, Cuba, North Korea,
  Singapore, Sudan, Venezuela, Crimea; list "non-exclusive"; duty to notify if user becomes resident of a
  restricted country; termination for concealed residence [S]. One aggregator also claims all EU/EEA are
  restricted [S] (irrelevant to the user). Seychelles-based [S].
- Data/API clauses: not read [U].
- Verdict **OK now, conditional**: user opens the agreement in a browser during sign-up and confirms Russia
  and Argentina are absent (record per evidence rules of the checklist).

### 2.3 Toobit
- Terms of Use (effective 2024-07-01, page stamp 2026-06-16) [V]:
  - Contracting party: EU/EEA residents -> Elyndret sp. z o.o. (Poland); **all other users -> Future Planet
    PTE. Ltd. (Cayman Islands)** [V]. (Corrects the candidates report, which said Australian entity [S].)
    The user must be onboarded as non-EU -> Cayman entity, so art. 5b is not engaged.
  - s. 13.3 no services to a 39-item list incl. Belarus, Türkiye, Uzbekistan, "Russian-controlled regions of
    Ukraine"; **not Russia, not Argentina** [V]. Wording is residence/region based; no "citizen" test [V].
  - s. 24.3(b) prohibits "high-frequency or programmatic trades without approval from the Platform";
    s. 24.3(e) no excessive API requests/bypassing rate limits; s. 13.2(o) no frequent intensive trading with
    unauthorised tools [V] -> **Stage 2 bot trading needs written approval** from Toobit.
  - s. 16.1(b) material "not to be further distributed without the written consent"; s. 13.1 no resale /
    third-party access; s. 6.4(e) no commercial use of the Site [V] -> pivot 2 needs consent.
- Verdict **OK now** for account + read-only key. Add "written approval for programmatic trading" to Stage 2
  preconditions (risk-manager).

### 2.4 Bitfinex
- Legal pages (`/legal/exchange/terms`, `/legal/general/api-terms`, `/legal/general/market-data`) are
  JS-rendered; only navigation was extracted [U]. Bitfinex publishes separate **API Terms** and **Market Data
  Terms** [V, titles only] -> pivot 2 must read both.
- Bitfinex Terminal Terms (bitfinexcom GitHub): "Prohibited Person" = US Persons, Government of Venezuela,
  **citizens or residents** of Prohibited Jurisdictions, Sanctioned Persons; Prohibited Jurisdictions = Cuba,
  North Korea, Iran, Syria, Crimea [V, for a different Bitfinex product — indicative only].
- Secondary 2026 lists: Canada, Cuba, Iran, Japan, North Korea, Syria, UK, US + occupied UA regions; no
  Russia/Argentina [S]. 2022: CTO said Bitfinex would not ban ordinary Russian users absent legal compulsion [S].
- Entity iFinex Inc. (BVI) [V footer]. Verdict **public data only** now (POST-guard decision blocks keys anyway);
  legal risk of registering later looks low after a human re-read of the Exchange Terms.

### 2.5 Phemex
- Terms of Use (updated 2025-07-10) [V]:
  - s. 1.26 Restricted Territories: UAE, US, UK, Ontario, Québec, Alberta, Saskatchewan, Afghanistan, Angola,
    Australia, Burundi, CAR, China, Cuba, Crimea, DRC, Ethiopia, Eritrea, Guinea, Guinea-Bissau, Haiti,
    Hong Kong, India, Iraq, Iran, Ivory Coast, Lebanon, Liberia, Libya, Mali, Myanmar, Nicaragua, North Korea,
    Palestine, Seychelles, Rwanda, Sierra Leone, Somalia, South Africa, South Sudan, Sudan, Syria, Venezuela,
    Yemen, Zimbabwe + catch-all. **No Russia, no Argentina** [V].
  - s. 10.1(p): user is "not a citizen, resident of, or located in" a Restricted Territory [V] — strictest
    test of the ten (nationality + residence + location). Russia not listed, so passes today; would block
    immediately if Russia were added.
  - s. 1.22: the only entity named is **PHEMEX POLAND SP. Z O.O.** (Katowice) [V]; non-EU entity not found in
    the readable part; governing law Singapore, SIAC arbitration [V].
    **Risk:** if the account would be held by an EU entity, EU Reg. 833/2014 art. 5b(2) bars crypto wallet,
    account or custody services to Russian nationals not holding EU/EEA/CH residence (see G1.8; *current
    wording unverified*). Treated as a potential blocker until disproved.
  - s. 6.6: price information obtained from Phemex may not be disseminated, used "other than for your own
    use", or used "in relation to any trading or dealing of Virtual Assets otherwise than through Phemex
    Exchange" [V]. s. 7.2: API "solely for the purposes of Transaction on Phemex"; no other commercial use of
    API data [V]. s. 10.2: no automated means not provided by Phemex [V].
    **Effect:** a literal reading makes using Phemex prices to decide trades on *other* venues a breach;
    cross-venue arbitrage with one Phemex leg is a grey zone; pivot 2/3 redistribution is clearly barred
    without consent. Public-data scanning by a non-account-holder is arguably still "use of the Services".
- Verdict **public data only** (and even that is grey under s. 6.6). Before any registration: written answer
  from Phemex (a) which entity serves an RF national resident in Argentina, (b) whether cross-exchange
  arbitrage using Phemex market data is permitted. If (a) = EU entity -> **do not register**.

### 2.6 WEEX
- Terms of Use (last updated 2026-07-07) [V]:
  - cl. 1.1(d)(ii) Excluded Jurisdictions: Canada, South Korea, US (+ territories), China (Mainland),
    Hong Kong, Singapore, UAE, North Korea, Cuba, Iran, Sudan, **Belarus, Russia** and Russian-controlled
    regions of Ukraine, Somalia, Myanmar, Venezuela + catch-all. "**Residents** of the Excluded Jurisdictions are
    not permitted to open Accounts"; duty to inform if you become a resident [V]. No Argentina.
  - cl. 1.1(d)(iii) OFAC, US Commerce, EU Consolidated, UN lists screened [V].
  - cl. 2.2(a) one account unless agreed [V]. cl. 8(e) no robots/scrapers/scripts to extract data;
    cl. 8(h) no commercial use of IP; cl. 8(l) no authorising third parties to use information [V] -> pivot 2
    barred without consent; API use relies on WEEX's own published API (no separate API terms found).
  - Governing law Saint Vincent and the Grenadines, ICC arbitration in Kingstown [V]; legal entity not named.
- **Correction** to candidates report (said Russia not listed [S]).
- Restriction is by residence, so an Argentina resident is textually eligible. Practical risk: KYC with an RF
  passport and possible +7 phone/RF history may lead WEEX to classify the user as Russia -> freeze. Also
  "KYC optional" marketing and conflicting licence claims (report) lower trust.
- Verdict **after DNI** (KYC with Argentine document and Argentine address); public data until then.

### 2.7 DigiFinex
- Official Terms of Use (zendesk) 403; snippet: content protected by Singapore law; older exchange terms
  (rev. 2020-03-03) name DigiFinex Limited [V-snip]. Secondary: US, Singapore, Canada, China "and others";
  11 countries + 1 region [S]. Russia/Argentina not found [U].
- Verdict **public data only**; if the probe shows value, user reads the terms at sign-up and lawyer re-checks.

### 2.8 Deepcoin
- Official terms not readable (zendesk 403, deepcoin.com JS). Secondary (CoinMarketCap): residents of
  Hong Kong, Cuba, Iran, North Korea, Crimea, Sudan, Malaysia, Syria, US + territories barred [S]; conflicting
  governing-law claims (Canada vs Seychelles) [S]; Dubai HQ [S].
- Verdict **public data only** (no transfer metadata, so a key adds little); re-check if probe pays off.

### 2.9 Poloniex
- Official "Prohibited Countries" help article (403 for the agent; snippet): Afghanistan, Burma, Chinese
  Mainland, Crimea, Cuba, DRC, Iran, Iraq, Ivory Coast, Libya, Mali, North Korea, Palestine, Somalia, Sudan,
  Syria, Yemen, Zimbabwe, US + territories (futures add Burundi, Morocco); "blocked at the IP level"
  [V-snip; date unknown]. **No Russia, no Argentina.**
- Sanctions adjacency [S]:
  - UK designated Huobi Global S.A. (HTX operator) in May 2026 for services to A7 and Garantex; EU 21st package
    (Reg. 2026/1848, 2026-07-23) transaction ban on "HTX / HUOBI GLOBAL SA" from 2026-08-23.
  - Poloniex is **not** in either list. Protos reports on-chain transfers of HTX reserves to Poloniex
    (allegation, not a finding). Poloniex paid USD 7.6M to OFAC (2023) for 2014-2019 sanctioned-region
    transactions.
  - Consequences for the user (not an EU/UK person): no direct sanctions breach found. Practical risks:
    (a) a future EU/UK step against the Sun group would trap funds; (b) withdrawals from Poloniex to
    Binance/OKX etc. may be flagged by their chain analytics as HTX-adjacent -> holds like the Bybit one (F7);
    (c) EU-entity counterparties already block HTX flows.
- Verdict **public data only; do not register / no funds**. Re-assess only if the probe shows unique value and
  a human lawyer agrees.

### 2.10 LBank
- User Service Agreement (page stamp 2026-07-22), "LBK Exchange" [V]: registration not accepted from 34
  places (incl. Azerbaijan, Kyrgyzstan, Uruguay, US, Canada, Mainland China, Hong Kong); Disclaimer list adds
  Belarus; sanctioned-state test is "national or resident" (Cuba, Iran, NK, Sudan, Syria) [V]. No Russia,
  no Argentina in the agreement. Multiple accounts for profit-seeking banned; no reproduction/commercial use
  of materials [V].
- SMS restrictions notice (effective 2025-12-27, page 2026-04-10): "**+7 Russia, Kazakhstan, etc.**" under
  "regions where platform services are unavailable" [V].
- 2025-05-27: accounts registered in Russia/Ukraine/Kazakhstan limited to withdraw/cancel/close; new
  registrations stopped [S, bitcoin.com syndications].
- Taken together, LBank does not serve Russia-linked users; whether an RF passport holder abroad is "linked"
  is undefined -> high refusal/freeze risk.
- Verdict **do not register** (public data only). Re-ask support in writing after DNI.

## 3. Russia-side exposure (applies to all ten)

- **Undesirable organisations:** none of the ten found; WhiteBIT remains excluded (report section 5) [S].
  Participation in an undesirable organisation's activity is an administrative offence, repeat = criminal
  (art. 20.33 KoAP / 284.1 UK RF) [S]. Re-check the Minjust list before each registration.
- **New RF crypto law** (reported as 282-FZ of 2026-08-04 "On digital currencies and digital rights", main
  provisions from 2026-09-01, licensed-intermediary requirement and criminal liability for unlicensed
  intermediaries from 2027-07-01; residents to notify the tax service of foreign crypto wallets/accounts
  within one month) [S, sources conflict, law text not read]. Liability appears aimed at intermediaries, not at
  users of foreign venues, but **each new account may be a notifiable foreign account/wallet** for an RF
  currency resident. More venues = more filings. -> Q6 below. Ties to G3.6.
- **Sanctions:** the user is not an EU/UK/US person; risk arises only through EU-entity counterparties
  (Phemex, see 2.5) and through HTX-adjacent flows (Poloniex).

## 4. Public market data and pivot 2

- Stage 1 (personal, read-only scanning via documented public API endpoints within rate limits): consistent
  with BingX s. 8.3 (public API carve-out), Toobit, WEEX, LBank texts read; site scraping is banned everywhere
  read (BingX 6.2, Toobit 13.2(k)/6.4(c), WEEX 8(e), Phemex 12.2) — we use APIs only (ccxt).
- **Exception — Phemex s. 6.6/7.2:** own-use only and only for trading through Phemex; see 2.5.
- **Pivot 2/3 (selling analytics or datasets):** every text read restricts redistribution or commercial use
  without written consent (BingX 6.1-6.2, Toobit 16.1(b)/13.1/6.4(e), Phemex 6.6/13.1, WEEX 8(h)/(l), LBank IP
  clause); Bitfinex has dedicated Market Data Terms (not read). -> written data licence per venue before any
  sale or public channel (extends V7/V8 of the vision review).

## 5. Actions

1. Keep all ten on **public data only** until the public probe ranks them (report section 6).
2. When a venue earns registration: BingX, Toobit -> register with own passport, residence Argentina, one
   account; XT -> same after the user reads the prohibited clause at sign-up. Record per checklist evidence rules.
3. Phemex: written question to support (entity; arbitrage use of data) before any account.
4. WEEX: wait for DNI. LBank: do not register; written question after DNI. Poloniex: no account, no funds.
5. Bitfinex, DigiFinex, Deepcoin: human re-read of live terms if the probe justifies keys.
6. Toobit (and any venue) in Stage 2: obtain written approval for programmatic trading where required.
7. Orchestrator: crypto-specialist report rows for WEEX (Russia listed), LBank (+7 unavailable [V]) and
   Toobit (Cayman entity, not Australian) are superseded by this file.

## 6. Questions for a human lawyer

- Q6: Under the new RF crypto law (282-FZ, *unverified*) and 173-FZ, must an RF citizen living in Argentina
  notify the Russian tax service of each foreign exchange account / wallet, and is using unlicensed foreign
  venues after 2027-07-01 an offence for the user himself?
- Q7: Phemex — if the contracting entity is Phemex Poland sp. z o.o., is serving an RF national resident in
  Argentina prohibited by Reg. 833/2014 art. 5b(2), and does s. 6.6 forbid cross-exchange use of its prices?
- Q8: Is holding funds on a venue owned by the same group as a UK-designated / EU-banned entity (Poloniex vs
  HTX) a sanctions risk for a non-EU person, and does it raise AML exposure on other accounts?
- Q9: For WEEX/LBank-style rules ("Residents of Russia", "+7 Russia services unavailable"), does an RF
  passport holder resident in Argentina fall outside them, and what evidence should the user keep?

## 7. Sources (accessed 2026-10-23)

- E1. BingX Customer Agreement (latest update 2025-03-19): https://bingx.com/en/support/articles/12803820985231 ;
  older version: https://support.bingx.com/hc/en-001/articles/360033286474-Customer-Agreement [V-snip]
- E2. BingX Disclaimer (latest update 2023-12-11): https://bingx.com/en/support/articles/11263347398927 ;
  BingX Mini Terms (2026-02-10): https://bingx.com/en/support/articles/15154351408783
- E3. XT: https://xtsupport.zendesk.com/hc/en-us/articles/900001631023-User-Agreement (403) ;
  https://www.xt.com/en/restrict ; secondary: https://xtguide.com/blog/xt-com-supported-and-restricted-countries/ ;
  https://www.cryptowinrate.com/xt-com-restricted-and-supported-countries-2026/
- E4. Toobit Terms of Use: https://www.toobit.com/support/toobit-terms-of-use ; mirror: https://tostracker.app/document/toobitcom-tos
- E5. Bitfinex legal index (JS): https://www.bitfinex.com/legal/exchange/terms/ ; API docs: https://docs.bitfinex.com/docs/introduction ;
  Bitfinex Terminal terms: https://github.com/bitfinexcom/bitfinex-terminal/tree/master/terms-of-use ;
  secondary: https://www.cryptowinrate.com/bitfinex-restricted-and-supported-countries ; 2022 stance:
  https://journalducoin.com/exchanges/guerre-ukraine-bitfinex/
- E6. Phemex Terms of Use (updated 2025-07-10): https://phemex.com/help-center/phemex-terms-of-use ;
  PT version: https://phemex.com/pt/help-center/termos-de-uso-da-phemex
- E7. WEEX Terms of Use (2026-07-07): https://www.weex.com/help/articles/4417379529241 ; Legal Statement:
  https://www.weex.com/help/articles/4417379598745
- E8. DigiFinex Terms of Use (403): https://digifinex.zendesk.com/hc/en-us/articles/360011580094-Terms-of-Use-DigiFinex ;
  secondary: https://www.cryptowinrate.com/digifinex-restricted-and-supported-countries-2026/
- E9. Deepcoin (secondary): https://www.coinmarketcap.com/exchanges/deepcoin ; https://www.cryptowisser.com/exchange/deepcoin-exchange/
- E10. Poloniex Prohibited Countries (snippet): https://poloniex.zendesk.com/hc/en-us/articles/4404183719191-Prohibited-Countries ;
  OFAC settlement: https://forklog.com/en/poloniex-to-pay-7-6-million-in-ofac-settlement/ ;
  HTX reserves at Poloniex: https://protos.com/we-found-htxs-reserves-at-poloniex/
- E11. HTX sanctions: https://finance.yahoo.com/markets/crypto/articles/eu-names-justin-suns-htx-142137832.html ;
  https://www.chainalysis.com/blog/eu-21st-russia-sanctions-package-crypto-patforms-july-2026/ ;
  https://www.trmlabs.com/resources/blog/eus-21st-package-extends-crypto-sanctions-to-third-countries
- E12. LBank User Service Agreement: https://www.lbank.com/support/articles/21436496711705 ; SMS restrictions
  (effective 2025-12-27): https://www.lbank.com/support/articles/48501046387737 ; 2025 Russia restriction:
  https://news.bitcoin.com/fr/la-plateforme-dechange-de-crypto-monnaies-lbank-suspend-les-inscriptions-aux-emirats-arabes-unis-prevoit-de-retirer-les-utilisateurs-en-russie-et-en-ukraine/
- E13. WhiteBIT undesirable: https://www.rbc.ru/politics/23/01/2026/697367209a79470d82b20250 ;
  https://www.finam.ru/publications/item/minyust-vnes-kriptobirzhu-whitebit-v-spisok-nezhelatelnykh-organizatsiy-v-rossii-20260202-1934/
- E14. RF crypto law (secondary, conflicting): https://www.garant.ru/article/2204420/ ; https://t-j.ru/crypto-law/
