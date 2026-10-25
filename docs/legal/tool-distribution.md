# Tool distribution, market-data redistribution and LICENSE input (T13)

- Date: 2026-10-25 (sources accessed this day). Author: lawyer agent. Card: `docs/tasks/tool/T13-lawyer-tool-distribution.md`.
- Product under review: Nexus as a **self-hosted, open spread-alert tool**. Each operator runs it on own machine, pulls
  public data (and optionally read-only-key data: fees, deposit/withdraw status) from binance, okx, kucoin, bybit,
  gateio, and posts alerts to **their own** Telegram channel. No trading, no withdrawals (ADR 0001, NO-GO report).
- **Not legal advice.** Preliminary desk research by a non-lawyer agent; automated extraction gives short quotes only.
  A human must re-read the live terms before relying on them. Questions for a human lawyer: section 8.
- Legend: **[V]** read today on the official page; **[S]** secondary source quoting the official text; **[U]** not
  readable/unverified.

## 1. Verdict in one table

Three use modes: **A** = private channel/chat, only the operator reads it; **B** = closed channel shared with other
people (friends, small group), free; **C** = public channel (anyone can join), free; **C+** = any monetisation
(paid access, ads, referral links, donations tied to the channel).

| Venue | Key clause | A private | B shared | C public | C+ paid/ads |
|---|---|---|---|---|---|
| okx | API Agreement s. 9.4 (2026-07-28) [V]: Market Data "solely for your own personal, non-commercial trading"; no "redistribute, publish, display, or otherwise make Market Data available to any third party" without written consent; applies "equally to Market Data accessed through public endpoints" | OK | **breach** | **breach** | **breach** |
| kucoin | Terms of Use (2025-01-24) Art. 89-91 [V]: no one may "publicly disseminate, change, distribute, release or publicly publish" platform content without written consent; no commercial use | OK | grey (private sharing, not "public") | **breach** | **breach** |
| binance | Terms of Use s. III.1.b [S, 2023 text; live page JS-only, U]: without written consent prohibited: "Data feeding or streaming services that make use of any market data of Binance" and services that "profit from (including through advertising or referral fees)" Binance data | OK | grey | **high risk** (a public price channel can be read as a "streaming service") | **breach** |
| bybit | API Terms and Conditions (2026-01-16) s. 6.7, 6.9 [S; PDF timed out, U]: no "repackaging or reselling" of "API or Service Data"; no commercial exploitation of the APIs | OK | grey | grey-to-high (republishing Service Data = repackaging) | **breach** |
| gateio | User Agreement (2026-07-22) s. 16.2 [V]: licence "solely as necessary to ... use our Services" "for non-commercial or personal use"; EU-entity version also bars "public display" [S] | OK | grey | grey-to-high | **breach** |

**Summary verdict**
1. **Publishing the code (open-source repo) is not a ToS breach** for any venue: the repo contains no exchange data;
   each operator fetches data under their own relationship with the venue. Comparable public projects exist (ccxt MIT,
   Freqtrade GPL-3.0, Hummingbot Apache-2.0). Conditions: documented API only, rate limits respected (ccxt limiter on),
   no web scraping (Gate 1.3(h)/2.11 [V], KuCoin Art. 90 [V], OKX 9.4 [V]), no exchange logos.
2. **Mode A (own private channel) is OK** on all five: this is the "own personal use" every licence allows. This is the
   default the product must ship with and the README must recommend.
3. **Mode C (public channel) breaches OKX and KuCoin outright** and is high risk on Binance; Bybit/Gate are grey. Alerts
   carry raw buy/sell prices (T4 template), i.e. Market Data, not only derived numbers. Removing prices and showing only
   the spread % lowers but does **not** remove the risk (OKX 9.4 covers data "made available" in any form; derived data
   is still built from it). A public channel needs **written data licences** from each venue it shows.
4. **Mode C+ (any money from the channel) breaches all five** without a licence, and adds investment-advice /
   signal-service questions (section 5).
5. Consequence of a breach (all five): termination of the API licence/account at the venue's discretion; for an account
   holding funds this is a freeze risk (see `review-vision-architecture.md` s. 4). Practical enforcement against a
   small free channel is unlikely but not zero; the risk sits with **the channel operator**, not with the code author.

## 2. What the tool and the docs must do (input for T4, T9, T10)

- T4 / config: default and documented mode = **private channel** of the operator. No built-in "public broadcast"
  feature, no ads/referral placeholders in templates, no exchange logos. Venue names in text are nominative use (OK).
- T4: disclaimer goes into the **pinned message** (text in s. 3.2), not every alert (as the card says). A one-line footer
  per alert is optional, not required by any ToS read.
- T9 / security: the "keys never leave your machine" statement (s. 3.3) is only true if the code (a) sends keys only to
  the venue's own API host, (b) never logs/echoes them or sends them to Telegram, (c) has no telemetry/phone-home.
  Security must confirm before T10 publishes the statement.
- T10 README: sections "Disclaimer", "Exchange terms" (s. 3.4), "API keys" (s. 3.3), "License".
- Operator duties that the README must push to the operator (not solvable in code): their own location must not be a
  restricted jurisdiction for the venue they query (Gate lists Argentina and Russia as restricted, see Addendum A of
  `review-vision-architecture.md`; binance.com does not serve the US/UK/EU etc.), and keys must be read-only.
- Owner's own instance: the owner (Argentina resident) uses Gate public endpoints; Gate restriction by location already
  flagged (G2.2 in `go-gates-checklist.md`). Unchanged by this review; keep the owner's channel private.

## 3. Texts (drafts, for T4/T10; English + Russian since alerts support en|ru)

### 3.1 README disclaimer (EN)
> **Disclaimer.** Nexus is free software provided "as is", without warranty of any kind (see LICENSE). It is an
> informational tool, **not financial, investment, legal or tax advice**, and not a recommendation to buy or sell any
> asset. Spreads shown are estimates from public order books and fee data; they can be wrong, stale or gone by the
> time you act. Transfers between exchanges take time, can be delayed or frozen, and prices move meanwhile. You alone
> are responsible for your decisions, for complying with each exchange's terms of service and with the laws of your
> country. Nexus is **not affiliated with, endorsed by or sponsored by** Binance, OKX, KuCoin, Bybit, Gate or Telegram;
> their names are used only to identify the services the tool connects to.

### 3.2 Pinned channel message (EN / RU)
> ℹ️ Automated spread alerts from a self-hosted Nexus instance. Information only, **not financial advice**; numbers are
> estimates and may be outdated. Not affiliated with any exchange. Use at your own risk. This channel is private; please
> do not forward or republish the alerts (exchange data terms).

> ℹ️ Автоматические уведомления о спредах от личной копии Nexus. Только информация, **не финансовый совет**; цифры —
> оценки и могут устареть. Не связано ни с одной биржей. Используйте на свой риск. Канал закрытый; пожалуйста, не
> пересылайте и не публикуйте эти сообщения (условия бирж на рыночные данные).

### 3.3 API keys statement (README; publish only after the T9/security check in s. 2)
> **Your keys stay with you.** API keys are optional and read-only. They are read from your local `.env` file, used only
> to sign requests sent directly to the exchange's own API, and are never logged, stored in the database, sent to
> Telegram or to the authors. Nexus has no telemetry. Create keys **without trading and without withdrawal permission**;
> enable IP restriction where the exchange offers it. Alert texts (prices, spreads) do go to Telegram, which you choose.

### 3.4 Exchange terms note (README)
> **Exchange data terms.** Market data belongs to the exchanges. Their API terms allow personal use; most of them forbid
> publishing, redistributing or monetising the data without a written licence (e.g. OKX API Agreement s. 9.4 covers
> public endpoints too). Run Nexus for yourself and post to a **private** channel. Do not make a public or paid channel
> out of it unless you hold the needed data licences. Respect rate limits; do not use Nexus from a country an exchange
> does not serve. The Nexus license covers the code only, not exchange data.

## 4. LICENSE recommendation

Dependencies are all permissive (ccxt MIT, SQLAlchemy MIT, alembic MIT, pydantic MIT, redis-py MIT, structlog MIT/Apache,
asyncpg Apache-2.0, celery BSD, httpx BSD, protobuf BSD) -> **no constraint**; any option below is compatible.
Redis server 8 (AGPL/RSAL/SSPL) and PostgreSQL run as separate Docker images, not shipped in the repo -> no effect.

| Option | What it means in practice | For this tool |
|---|---|---|
| **Apache-2.0** (recommended) | Anyone may use/modify/sell; must keep LICENSE + NOTICE (your name and disclaimer travel with forks); explicit patent licence; s. 6 gives no right to the project name; "AS IS" + liability limit | Best balance: open, business-friendly, trusted, protects the name and attribution; same family as Hummingbot |
| MIT | Shortest permissive licence; keep copyright notice only; no patent or trademark wording | Fine if the user wants maximum simplicity; slightly weaker than Apache on name/patents |
| AGPL-3.0 | Copyleft incl. network use: whoever runs a **modified** version as a service must publish the source | Deters someone turning it into a closed paid signal service; scares off companies; whether Telegram subscribers count as "remote users" (s. 13) is unclear |
| Source-available (PolyForm Noncommercial 1.0 / BSL 1.1) | Code visible, commercial use forbidden (BSL converts to open source after a date) | Mirrors the exchanges' "non-commercial" data terms, but not "open source" (OSI), less community trust; the exchange limits apply anyway regardless of the code licence |

Reasoning: the legal risk in this product is in **data use by operators**, not in the code; no code licence can grant or
remove exchange data rights. So the licence should mainly (1) disclaim warranty/liability, (2) keep attribution and the
disclaimer in forks, (3) not deter adoption. Apache-2.0 does all three. Choose AGPL only if preventing closed commercial
forks matters more than adoption. Whatever is chosen: add `LICENSE` at repo root, SPDX id in `pyproject.toml`
(`license = "Apache-2.0"`), copyright line with the user's name/handle and year.

## 5. Other distribution risks

- **Investment advice / signal services.** A free tool and a private channel: low risk. A public or paid signal channel may
  touch Argentine capital-markets rules (CNV, Ley 26.831; advisers) and, for EU audiences, MiCA market-abuse rules on
  disseminating information (Title VI) — *applicability unverified* (Q10, Q11). Do not run C/C+ without review.
- **Liability to third-party users.** "AS IS" + liability limitation in the licence and README; enforceability against
  consumers in some countries is limited (Q12). Free software with no contract and no payment lowers exposure.
- **Trademarks.** Name venues in text only; no logos; no "official"/"partner" wording. Check that "Nexus" is not confusing
  with an existing crypto brand before advertising the repo (many "Nexus" marks exist, e.g. Nexus Mutual) — *not checked*.
- **Rate limits / IP bans.** Many operators behind one public instance are not the model; each runs their own. Keep ccxt
  rate limiting on by default.
- **Restricted locations.** Operator's responsibility (README s. 3.4); the tool should not offer proxy/VPN geo-bypass
  features (both OKX 9.4 and Gate 1.3(h) forbid circumventing technical measures) — relevant to the backlog "proxy per
  exchange" idea.
- **Personal data.** The tool keeps no third-party personal data (only market data + own Telegram chat id); no privacy
  policy needed for self-hosting. A hosted public instance would change this.

## 6. Owner's own setup (today)
Private channel for the owner = mode A -> OK on all five. If the owner wants to invite others or open the channel later,
this is a new decision (mode B/C) and needs written consent at least from OKX and KuCoin.

## 7. Open items for the orchestrator
- LICENSE choice -> user (NEEDS_USER).
- T9/security: confirm the s. 3.3 statement holds in code before T10 publishes it.
- Bybit API Terms PDF and Binance live ToS not read directly today -> human re-read before any mode B/C.

## 8. Questions for a human lawyer
- Q10: Does a free public Telegram channel with arbitrage spreads count as investment advice/recommendation under CNV rules
  (Ley 26.831) for an Argentina-resident operator? Does charging for it change this?
- Q11: For EU subscribers, does such a channel fall under MiCA Title VI (investment recommendations / market abuse)?
- Q12: Are the "AS IS" / no-liability terms of Apache-2.0/MIT enforceable in Argentina for free software published on GitHub?
- Q13: Does showing only derived numbers (spread %, no prices) escape "Market Data" redistribution clauses (OKX 9.4,
  KuCoin Art. 89, Binance III.1.b)?

## 9. Sources (accessed 2026-10-25)
- D1. OKX API Agreement, last updated 2026-07-28, s. 9.2-9.5 [V]: https://www.okx.com/help/okx-api-agreement
- D2. OKX Historical Data Terms [S]: https://www.okx.com/en-us/help/historicaldata-terms-and-conditions
- D3. KuCoin Terms of Use, last updated 2025-01-24, Art. 88-92, 102 [V]: https://www.kucoin.com/announcement/en-terms-of-use
- D4. Gate User Agreement, last updated 2026-07-22, s. 1.3(h), 2.11, 16.1-16.2 [V]: https://www.gate.com/user-agreement ;
  Gate EU User Agreement [S]: https://www.gate.com/en-eu/legal/user-agreement
- D5. Binance Terms of Use (live page JS-rendered, not readable [U]): https://www.binance.com/en/terms ; s. III.1.b quoted in
  Superalgos issue #1019 (2021-05-28) [S]: https://github.com/Superalgos/Superalgos/issues/1019 ; Binance Vision Dataset
  Terms (historical datasets, CC BY-NC-SA 4.0, commercial use excluded) [S]: https://data.binance.vision/Binance_Vision-Terms_of_Use.pdf
- D6. Bybit API Terms and Conditions, 2026-01-16, s. 3.1, 6.6, 6.7, 6.9 [S via D7; PDF timed out]:
  https://www.bybit.com/common-static/compliance/legal/BYBIT/df1923006718fbba8ba70d7d762b9866.pdf
- D7. cryptomarkets.tools, "What exchange API terms actually let you do" (updated 2026-09-19) [S]:
  https://cryptomarkets.tools/guides/exchange-api-terms
- D8. Earlier reviews: `docs/legal/review-vision-architecture.md` (V6-V8, A7, Addendum A), `docs/legal/expansion-venues-review.md` s. 4.

---

## Кратко для пользователя (RU)

- **Публиковать код инструмента можно.** В репозитории нет данных бирж; каждый, кто запускает Nexus у себя, сам берёт данные
  у бирж по их правилам. Так же живут ccxt, Freqtrade, Hummingbot.
- **Свой закрытый канал (читаете только вы) — можно** на всех пяти биржах: это «личное использование», которое разрешают все.
- **Публичный канал — нельзя без письменной лицензии**: OKX (п. 9.4 API Agreement, прямо включая публичные эндпоинты) и
  KuCoin (ст. 89) запрещают публиковать их данные; у Binance — высокий риск; Bybit и Gate — «серая зона». Любые деньги с
  канала (платный доступ, реклама, рефссылки) — нарушение у всех пяти. Последствие нарушения — блокировка API/аккаунта.
- Убрать цены и оставить только % спреда — риск ниже, но не исчезает.
- Готовы тексты: дисклеймер для README, закреплённое сообщение канала (ru/en), фраза про ключи (публиковать после проверки
  security), заметка про условия бирж.
- **Лицензия:** рекомендую **Apache-2.0** (открытая, сохраняет ваше авторство и дисклеймер в форках, защищает название).
  MIT — проще, чуть слабее. AGPL — если важно, чтобы никто не сделал из форка закрытый платный сервис. Лицензия кода не
  даёт прав на данные бирж ни при каком выборе.
- Это не юридическая консультация; вопросы для живого юриста — раздел 8.
