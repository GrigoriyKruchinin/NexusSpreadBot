# Perpetual futures access for the hedged-transfer strategy (preliminary)

Date: 2026-10-25. Author: lawyer agent. Status: preliminary desk research, for orchestrator and user.
**Not legal advice.** Public sources only, many secondary. Every item marked *unverified* must be
confirmed by the venue in writing, a human lawyer or an accountant before money depends on it.

Context: [`go-gates-checklist.md`](go-gates-checklist.md) (facts F1-F10, gates G1-G4),
[`review-vision-architecture.md`](review-vision-architecture.md). ADR 0001 is unchanged: paper only;
no orders, no transfers, no trading-permission keys until GO plus explicit user confirmation.

## 0. Strategy under review

Buy spot on venue A and at the same time open a USDT-margined perpetual **short** of equal size (on B or A);
move the coin A -> B; sell spot on B and close the short. Capital ~10k USDT, leverage ~1-2x, hedge
only. Legal effect: each venue in the hedge leg now needs **derivatives** eligibility, not just spot.
Derivatives are where venues apply extra limits by country, extra KYC/suitability checks, and
broader rights to close positions.

## 1. Verdict per venue

| Venue | Verdict (perps for this user) | Main reason | Conditions to reach "allowed" |
|---|---|---|---|
| okx | **conditional (no blocker found)** | Risk & Compliance Disclosure (updated 2026-07-08) s. 3: derivatives are limited only for Australia, Brazil, South Korea, UK (plus fully restricted list). Russia is limited only for "fiat payment services". Argentina is not listed (S1). The 2023 limits for "verified users from Russia" covered Earn >99 % APY, Shark Fin and Dual products, not derivatives (S2). ToS (updated 2026-10-22): margin/derivatives "at our discretion" (4.2(b)), execution-only, user states they have enough knowledge (6.23-6.28), positions can be closed and assets frozen (6.77, 7.6), "socialized claw-back" (6.82) (S3). | G1.4 done (residence = Argentina, global entity, not OKX EU); derivatives section opens in the account with no region block; any quiz passed honestly; written support answer (G5.4) |
| kucoin | **conditional (no blocker found)** | Futures Terms of Use (updated 2026-03-16) s. 3.1: needs a verified account, any required **knowledge test / suitability check**, and excludes residents of countries where derivatives are restricted (examples given: Spain, Australia) (S4). Main Terms restricted list (secondary, art. 17(5)): no Russia, no Argentina (S5). Futures s. 8.1(f) bans manipulation, spoofing, wash trading, exploiting bugs; s. 10.1-10.2: freeze without notice and forced close (S4). Contracting entity not named on the page. | G1.3 done; entity confirmed as the global one (not a KuCoin EU entity); futures open in the account; support answer (G5.4) |
| binance | **conditional, blocked in practice until G1.1a** | The account is declared as Russia-resident (F8). Binance's 2022 rule for the EU 5th sanctions package: Russian nationals/residents with > EUR 10,000 in assets -> withdrawal-only; open futures had 90 days to close; no new positions. Russians abroad were exempt with proof of address, but a same-day update said users abroad **verified with Russian documents** are also limited (S6, S7). Binance said in 2023 the limits still apply (checklist L3); 2026 status *unverified*. ~10k USDT is at the EUR 10,000 line, so this rule matters even at our size. After a residence change the account may move to Binance's Argentine registered entity, whose product list (futures or not) is *unknown*. Binance says it does not offer derivatives where it has no licence or where they are banned (S8). Operational limits: > 20x not available in the first 30 days of a futures account (from 2025-12-07); > 5x not available to sub-accounts of regular users (from 2025-08-12) (S9). Both are irrelevant at 1-2x. | G1.1a done (residence = Argentina on the **same** account, no second account); after that the user reads the futures page and any limit banner; written support answer on Russian-passport + Argentina residence + USDT-M futures (G5.4) |
| bybit | **blocked for now** (operational, not a ToS ban) | Open compliance hold (F7) and a stale residence (G1.5). Bybit Global does not exclude Russia or Argentina (checklist L10); **Bybit EU refuses Russian citizens** (review src 3). Putting a hedge leg on a venue that is already holding funds = risk of a stranded short and margin. | G1.5 cleared (hold resolved, residence updated); then re-assess |
| gateio | **blocked** | User Agreement cl. 2.5 lists **Argentina and Russia** as Restricted Locations (checklist L5). Derivatives inherit this. | Written "yes" from Gate (G1.2); otherwise excluded |

Practical outcome for paper modelling: hedge legs on **okx and kucoin only**; binance added after
G1.1a plus G5.3; bybit/gateio excluded (same rule as G1.7).

## 2. Sanctions / nationality layer

- EU Reg. 833/2014 art. 5b(2): ban on EU providers giving crypto wallet/account/custody services to
  Russian nationals/residents. The EUR 10,000 cap was removed in Oct 2022 (Reg. 2022/1909) per the
  Maltese regulator FAQ and nalog.nl; some Luxembourg guidance still quotes the cap (S10, S11).
  *Consolidated EUR-Lex text not checked.* Exemption: holders of an EU/EEA/CH residence permit
  (does not apply to the user). **Effect:** the user must not be served by any EU/EEA entity of any
  venue (OKX EU, KuCoin EU, Bybit EU, any Binance EU entity). This is G1.8. Futures on a global
  entity are not affected by the EU rule itself. Global entities often still apply it voluntarily
  (Binance 2022).
- MiCA: relevant only to EU entities and EU residents. Binance stopped EU services on 2026-07-01
  (review src 10-11). It does not limit an Argentine resident on a global entity.
- Nationality stays a KYC risk factor (enhanced checks, sudden policy changes). For derivatives
  that risk is larger: venues can switch an account to "reduce-only" or close positions by force
  (KuCoin s. 5.4(c), 10.2; OKX 6.77, 7.6).

## 3. Argentina

- **CNV / PSAV.** RG CNV 1058/2025 (Mar 2025) set up registration, custody, AML and cybersecurity
  rules for PSAVs, local or foreign, that serve Argentines (S12). RG CNV 1172/2026 (issued
  2026-10-14, in the Boletín Oficial 2026-10-15) replaces the PSAV chapter. Among other things,
  its monthly report counts "contracts referencing virtual assets" at notional value, starting
  2026-11-01 (S13, S14). My reading (*inference*): PSAVs may deal in derivatives on virtual
  assets, and the CNV expects to see that volume. **No rule found that bars a resident individual
  from trading crypto derivatives on a foreign platform.** The duties fall on the platform. Risk to
  the user is indirect: an unregistered venue can be blocked by court order or leave Argentina
  (S15), which forces funds to move. The CNV regulates PSAVs, not the assets themselves, unless an
  asset is a security (S16). The local regulated BTC futures (Matba Rofex, 2023) were limited to
  qualified investors (S17). That shows CNV caution on retail crypto derivatives, but it does not
  bind offshore venues. *Full text of RG 1172/2026 not read (PDF not machine-readable to the agent).*
- **Registration status:** binance and bybit are in the PSAV register per secondary sources. okx and
  kucoin are **not confirmed** (S18). The user (or a lawyer) checks the official CNV register.
- **Tax (for the accountant, G3).** Questions the hedge creates on top of G3.1-G3.6:
  1. Category of perp P&L for an individual: a derivative result (the LIG covers derivatives
     explicitly; S19), foreign-source if the venue is offshore. Rate is 15 % schedular or another
     rate. *Unverified.*
  2. **Netting risk:** the spot leg makes a gain and the short makes a loss, or the reverse. If the
     law puts them in separate baskets ("quebrantos específicos": a loss of one kind may offset
     only gains of the same kind), the user pays tax on the winning leg and carries the losing
     leg forward. The net hedged trade could then pay tax on a gross gain. Can the short count as
     a hedge (cobertura) so that both legs net? **This can decide the after-tax GO number.**
  3. Funding payments, paid and received: what kind of income or cost are they?
  4. Bienes Personales on USDT held as futures margin.
  5. Habitualidad: frequent hedged trading could be treated as business (third category) income.
  6. Russian side (173-FZ reports, if they apply): do reports cover derivatives and funding flows?

## 4. ToS: arbitrage, API, deposit/withdraw cycles, several venues

| Topic | okx | kucoin | binance | Note |
|---|---|---|---|---|
| Cross-venue arbitrage / basis hedge | Not named as banned; bans wash trading, front-running, manipulation (3.1(p)), "unfair trading" and exploiting vulnerabilities (4.13(b)) | Not named as banned; bans manipulation, spoofing, wash trading, bug exploitation (Futures 8.1(f)) | ToS text not readable by the agent (*unverified*). Convert API "not suitable for ... price arbitrage" (review src 8): use spot/futures order endpoints only | Spot long + perp short on the same venue are different instruments with no self-matching. That is not wash trading. Avoid any self-crossing on one book. |
| API / bots | Allowed under the OKX API Agreement; repeated rate-limit breaches can lead to suspension (5.9) | Orders only via the official interface or approved APIs (Futures 5.1(a)) | Oct 2025: > 600 accounts banned for "unauthorized third-party tools", Alpha-focused (S20). Use only official API keys, no account sharing | Keep ccxt rate limiting on |
| Rapid deposit/withdraw cycles | No specific clause; AML clauses 3.1(k), 4.13(a)(iii); withdrawals can be suspended (4.1) | Freeze for suspected illegal activity or risk management (10.1) | Same pattern (*unverified text*) | Not banned, but it triggers source-of-funds checks (Bybit hold F7 is the live example). Same-name accounts only; keep TxIDs; answer Travel Rule prompts truthfully |
| Several venues | Fine. One account per venue; no extra accounts without consent (9.1) | Fine. Sub-account abuse is banned in promo programmes (S4 related page) | Fine. One verified account per person (checklist L4, secondary); sub-account leverage cap 5x | Official sub-accounts only |

Non-legal risk that must go to risk-manager: if venue B holds the incoming deposit (compliance
review, network delay), the short on B stays open. The hedge still holds, but margin must cover
adverse moves, funding and possible ADL (auto-deleveraging) / claw-back (OKX 6.82). At 1-2x, the
USDT margin on B is ~50-100 % of the notional, so the capital need roughly doubles.

## 5. Proposed new gate G5 (add to go-gates-checklist; derivatives, only if the hedge is used at GO)

| ID | Item (exact user action) | Evidence | Who | Status |
|---|---|---|---|---|
| G5.1 | For okx, kucoin (and binance after G1.1a): open the USDT-M futures page in the account. Write down only: available yes/no, any "not available in your region" text, any quiz or suitability step asked for. Do **not** activate trading or create trade-permission keys (ADR 0001) | Note: date, venue, yes/no, message wording | user | open |
| G5.2 | Note the contracting entity shown in the futures terms you accept in the account (global vs EU/local). Stop if it is an EU/EEA entity | Note: entity name | user; lawyer reads it | open |
| G5.3 | binance: no futures on the Russia-resident profile. After G1.1a, re-check G5.1 and any balance-limit banner (EUR 10,000 regime) | Note | user | open |
| G5.4 | Write to support (okx, kucoin, binance): "I am a Russian citizen, verified with a Russian passport, residing in Argentina. Am I eligible for USDT-margined perpetual futures, and are there limits on balance, leverage or products?" Keep the answer category only | Note: date, answer yes/no/limits | user | open |
| G5.5 | Answers from the accountant on section 3 tax items 1-6, above all netting of the spot and short legs | Written answer | accountant | open |
| G5.6 | Quizzes are answered by the user honestly, with no third-party help; no VPN or proxy to reach a derivatives product blocked by region (also G2.4) | User statement | user | open |
| G5.7 | Before any real hedge: risk-manager limits for margin buffer, per-venue exposure and the stranded-short case; quant includes funding and perp fees | Link to `docs/risk/` and quant report | risk-manager, quant | open |
| G5.8 | Re-check G5.1-G5.4 when the DNI is issued and at UF | Note | user + lawyer | open |

## 6. Questions for a human lawyer / accountant

- Q6a: Can a perp short opened as a hedge be treated as cobertura for Argentine income tax, so that
  the spot and futures results net? If not, how do derivative losses offset?
- Q6b: Does any Argentine rule (CNV, BCRA, UIF) limit a resident individual using offshore crypto
  derivatives? Is an unregistered offshore PSAV a legal risk to the client, not just to the PSAV?
- Q6c: After a Binance residence change to Argentina, which entity serves the account, and does
  that entity offer derivatives?

## 7. Sources (accessed 2026-10-25)

- S1. OKX Risk and Compliance Disclosure (updated 2026-07-08), s. 3: https://www.okx.com/help/risk-compliance-disclosure
- S2. ForkLog, OKX restricts services for Russian citizens (2023-06-19): https://forklog.com/en/okx-restricts-services-for-russian-citizens/
- S3. OKX Terms of Service (updated 2026-10-22), cl. 2.1-2.2, 3.1(k),(p), 4.1, 4.2(b), 4.13, 5.9, 6.23-6.28, 6.77, 6.82, 7.4-7.7, 9.1: https://www.okx.com/help/terms-of-service (first 100k chars read, automated extraction)
- S4. KuCoin Futures Terms of Use (updated 2026-03-16), s. 3.1, 5.1, 5.4, 6.1, 8.1(f), 10.1-10.2: https://www.kucoin.com/announcement/en-futures-terms-of-use ; KuCoin futures programme rules: https://www.kucoin.com/support/48142946142378
- S5. Datawallet, KuCoin restricted countries (updated 2026-08-04, secondary): https://www.datawallet.com/es/cripto/kucoin-países-restringidos ; KuCoin main Terms (not readable by the agent): https://www.kucoin.com/legal/terms-of-use
- S6. ForkLog, Binance imposes restrictions on Russian users (2022-04-21, incl. update on Russian documents): https://forklog.com/en/binance-imposes-restrictions-on-russian-users/amp
- S7. The Block (2022): https://www.theblock.co/linked/142788/latest-eu-sanctions-force-binance-to-crack-down-on-russian-users ; Benzinga (2022): https://benzinga.com/markets/cryptocurrency/22/04/26730766/binance-limits-crypto-services-to-russians
- S8. CoinDesk, Binance UK derivatives (2021, Binance's licence-based derivatives policy): https://coindesk.com/policy/2021/12/14/binance-uk-is-threatening-to-block-derivatives-traders-in-a-move-to-keep-regulators-at-bay ; CoinPerps, Binance Futures restricted countries (2026-06-03, secondary; Russia and Argentina not listed): https://www.coinperps.com/ru/learn/binance-futures-restricted-countries
- S9. Binance FAQ, Leverage and Margin of USDⓈ-M Futures: https://www.binance.com/es/support/articles/360033162192
- S10. MFSA (Malta) crypto sanctions FAQ: https://smb.gov.mt/gn-final-crypto-faqs/ ; nalog.nl (2022-10-20): https://www.nalog.nl/en/news/2022/10/20/evrosoyuz-vvyol-zapret-na-obsluzhivanie-kriptokoshelkov-rossiyan/
- S11. Baker McKenzie, EU sanctions compliance for crypto assets (2026-09): https://www.bakermckenzie.com/en/insight/publications/2026/09/european-union-sanctions-compliance-for-crypto-assets
- S12. CriptoNoticias on RG CNV 1058/2025 (2025-03-18): https://www.criptonoticias.com/regulacion/nueva-norma-argentina-exchanges-bitcoin
- S13. Estudio O'Farrell via abogados.com.ar, RG CNV 1172/2026: https://abogados.com.ar/la-cnv-actualiza-el-regimen-aplicable-a-los-proveedores-de-servicios-de-activos-virtuales/40294
- S14. iProUP on RG 1172/2026: https://www.iproup.com/finanzas/72368-la-cnv-actualiza-registro-de-exchanges-cripto-con-nuevas-reglas-para-operar-en-argentina ; text (PDF): https://www.colegio-escribanos.org.ar/noticias/2026_10_15_CNV-Res-Gral-1172-26.pdf
- S15. Contxto, mandatory registry, unregistered firms cannot operate: https://www.contxto.com/en/argentina/argentina-implements-mandatory-crypto-exchange-registry/
- S16. iProUP, CNV competence over crypto: https://www.iproup.com/economia-digital/54645-la-cnv-y-una-aclaracion-clave-que-criptomonedas-puede-regular-y-cuales-no
- S17. Cointelegraph, CNV approves Bitcoin futures index (Matba Rofex): https://cointelegraph.com/news/argentina-securities-regulator-approves-bitcoin-futures-index ; Consejo Salta summary: https://consejosalta.org.ar/wp-content/uploads/BREVE-RESENA-NORMATIVA-VINCULADA-A-CRIPTOACTIVOS-EN-ARGENTINA-1.pdf
- S18. Datawallet, best exchanges Argentina (secondary): https://www.datawallet.com/de/krypto/beste-krypto-b%C3%B6rsen-argentinien ; plus checklist L6 (Binance) and review src 6
- S19. abogados.com.ar, Ganancias en operaciones con criptomonedas: https://abogados.com.ar/el-impuesto-a-las-ganancias-en-las-operaciones-con-criptomonedas/22658 ; Rankia AR: https://www.rankia.com.ar/blog/cripto/7404760-impuesto-ganancias-criptomonedas-argentina
- S20. The Block, Binance bans > 600 accounts over unauthorized tools (2025-10-20): https://www.theblock.co/post/375278/binance-bans-more-than-600-accounts-over-unauthorized-third-party-tools

## Краткое резюме для пользователя (RU)

Это предварительная оценка, а не юридическая консультация.

- **OKX:** признаков запрета нет. Фьючерсы (perpetual, «бессрочные контракты») ограничены только для
  Австралии, Бразилии, Кореи и Великобритании. Для России ограничены только фиатные платежи.
  Условие: в профиле указана резиденция Аргентина, и счёт открыт на глобальной компании, а не на
  OKX EU.
- **KuCoin:** признаков запрета нет. Для фьючерсов нужен верифицированный аккаунт и, возможно, тест
  на знания. Проверьте в аккаунте, что раздел фьючерсов открыт.
- **Binance:** пока аккаунт числится российским, фьючерсы для стратегии не годятся. С 2022 года
  Binance ограничивает россиян (и тех, кто проходил проверку по российскому паспорту) с активами
  больше 10 000 евро: аккаунт переводится в режим «только вывод». Наши ~10k USDT как раз около этой
  границы. Сначала смените резиденцию на том же аккаунте (второй аккаунт не открывайте), потом
  проверим фьючерсы заново.
- **Bybit:** пока не использовать (заморожен перевод, устаревшая резиденция).
  **Gate.io:** заблокирован, Аргентина и Россия в списке запрещённых стран.
- **Аргентина:** запрета для частного лица торговать криптофьючерсами на зарубежной бирже не нашёл.
  Требования CNV (регулятор рынка ценных бумаг) касаются самих бирж.
- **Налоги (вопрос бухгалтеру):** главный риск в том, что прибыль по споту и убыток по шорту
  (продаже фьючерса) могут попасть в разные «корзины» и не зачесться друг против друга. Тогда налог
  платится с выигравшей ноги, и итог после налога может испортиться. Спросить также про фондинг
  (периодические платежи по фьючерсу) и про налог на имущество с маржи.
- **Что сделать:** пункты G5.1-G5.8 в разделе 5. Посмотреть раздел фьючерсов, ничего не включая;
  написать в поддержку OKX, KuCoin и Binance (текст вопроса там же); отнести бухгалтеру вопросы
  раздела 3.
