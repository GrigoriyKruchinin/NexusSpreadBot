# Legal GO gates G1-G4 — checklist

Date: 2026-10-23 (updated same day with user facts F5-F10). Author: lawyer agent.
Status: **all gates open; none cleared. G1 has a likely blocker for gateio (G1.2).**
**Not legal advice.** Preliminary checklist. Items marked *unverified* need a human
lawyer/accountant or an official source before they are relied on.

Source of the gates: [`review-vision-architecture.md`](review-vision-architecture.md) section 1
(addendum A in the same file covers the 2026-10-23 update).
GO rule: [`docs/product/vision.md`](../product/vision.md) section 3 item 3 — every gate below must
be **cleared** (all items `done` or `n/a` with a reason) and no blocking verdict may exist.
"No blocker found" alone is not enough.

## How to use

- Status per item: `open` (not checked yet) · `at risk` (known fact threatens the gate) ·
  `done` (evidence filed) · `blocked` (cannot be cleared as things stand) · `n/a` (with reason).
- Gate status = worst item status.
- Who checks: **user** (only the user can see account/KYC data), **accountant** (human Argentine
  accountant/lawyer), **lawyer** (this agent: desk check of public sources, records the result).
- Evidence: store a short note in `docs/legal/evidence/` (create when first needed). **Never
  store** KYC documents, passport/DNI numbers, account IDs, API keys, balances, ticket numbers or
  screenshots showing them — only "checked on <date>, result: <yes/no>, source: <page name/URL>".
- Re-check every gate at UF (GO/NO-GO) and whenever a venue changes its ToS or the user's
  residence/document status changes (e.g. DNI issued).

## Known facts (from the user, 2026-10-23)

No personal identifiers or document numbers are recorded here by design.

| # | Fact | Effect |
|---|---|---|
| F1 | ~~Bybit account blocked, reason unknown.~~ **Revised by F7:** not a full ban; one outgoing ETH transfer is held by compliance. No Bybit keys. | See F7. |
| F2 | No MEXC/Bitget accounts: they do not accept RF citizenship; user waits for Argentine DNI (~2027-04). | Already excluded from GO analytics (ADR 0002, `CORE_EXCHANGES`). G4: must not be worked around. |
| F3 | ~~Residence and contracting entity on core accounts not yet confirmed.~~ **Refined by F6-F9.** Entity still unconfirmed everywhere. | G1 open/at risk per venue. |
| F4 | GO bar is measured **after income tax** (user decision). | G3 is a hard input to the money criterion. |
| F5 | Citizenship on all accounts: Russia (Russian international passport used as ID). KYC passed on all core accounts. | Nationality is a KYC risk factor everywhere; residence field is what decides service scope. |
| F6 | User lives in Argentina; Argentine DNI not yet issued (awaited). | Residence proof for KYC must be a non-DNI document (G1.6). Re-check all venues when DNI is issued. |
| F7 | **bybit:** KYC was done while the user lived in Montenegro, Georgia or Armenia (user unsure which). Declared residence on the account unknown. An ETH transfer (~1.6 ETH) has been frozen pending a compliance ticket for ~1.5 months. User reports such holds are common at Bybit now. | G1.5 at risk: declared residence probably not Argentina -> stale data (duty to update). Hold = freeze-risk evidence for risk-manager. |
| F8 | **binance:** old account opened while the user lived in Russia; declared residence likely Russia. User offers to open a new account for Argentine residence. | G1.1 at risk (stale residence; Russia-resident regime). **Opening a second account would breach G4.2** — see G1.1a. |
| F9 | **gateio, kucoin, okx:** opened with the Russian passport while living in Argentina (no DNI required). Declared residence presumably Argentina, **not confirmed**. | G1.2-G1.4: user must confirm field. **gateio lists Argentina and Russia as Restricted Locations** (source L5) -> G1.2 likely blocked. |
| F10 | Argentine DNI is awaited. | Trigger for re-check of G1 (all venues) and G4.3 (MEXC/Bitget). |

## Summary

| Gate | Subject | Status | Main reason |
|---|---|---|---|
| G1 | KYC/residence truthful and current, global (non-EU) entity, venue serves the residence | **at risk** (gateio item **blocked**, pending verification) | gateio ToS lists Argentina + Russia as restricted (G1.2); binance residence likely Russia (G1.1); bybit residence likely a third country + compliance hold (G1.5) |
| G2 | VPS/server location not restricted for any core venue | open (note: Argentina itself is on gateio's list) | VPS not chosen/checked yet |
| G3 | Argentine and Russian tax position known | **at risk** | GO is after-tax (F4) but residency start, rate and category are unverified |
| G4 | No foreign-name accounts, no multi-accounting, no third-party KYC | **at risk** | F8 (offer of a second Binance account), F7 (temptation of a new Bybit account), F2 |

## G1 — KYC / residence on every core account

Core venues: binance, bybit, gateio, kucoin, okx (final GO set may shrink, see G1.7).

| ID | Item (checkable) | Evidence required | Who | Status |
|---|---|---|---|---|
| G1.1 | binance: profile residence = Argentina; KYC verified; contracting entity is non-EU (global or Argentina-registered entity) | Note: date, residence field value, entity name | user (lawyer reads entity) | **at risk** (F8) |
| G1.1a | binance: residence is updated **on the existing account** via Account -> Identification -> Edit Address, with an Argentine proof of address (Binance FAQ, source L1; KYC reset may be required). **No second account.** If Binance refuses or forces a reset that fails: ask support in writing how to proceed (e.g. close old account first, then re-register with their consent). | Note: date of request, outcome (approved / reset / refused), products lost/gained | user | open |
| G1.1b | binance: until G1.1a is done, the account is **not used for Nexus**. Reason: as a Russia-resident account it is under Binance's 2022 sanctions regime (balances > EUR 10,000 limited to withdrawal-only; Binance said in 2023 the limits still apply in full — sources L2, L3; *2026 status unverified*); also the declared residence is stale. | Note "not used until updated" | user | open |
| G1.2 | gateio: Gate User Agreement (last updated 2026-07-22) cl. 2.5 lists **Argentina and Russia** among "Restricted Locations" (source L5; read via automated extraction — *a human must re-read the clause*). If confirmed, an Argentina-resident user is outside Gate's service scope -> ToS breach risk and freeze risk regardless of KYC. Actions: (a) user checks the residence field and any in-account notices; (b) user asks Gate support in writing whether Argentina-resident users are served and by which entity; (c) until a written "yes", **gateio excluded from the GO set** (G1.7). | Note: clause re-read date, support answer (category only), decision | lawyer re-read + user ticket | **blocked** (pending verification) |
| G1.3 | kucoin: residence = Argentina; KYC verified; entity non-EU. Russia and Argentina not on KuCoin's restricted list per secondary source (Terms art. 17(5) as cited by L7); official page not readable by the agent — *unverified* | Note: residence field, entity, date | user + lawyer | open |
| G1.4 | okx: residence = Argentina; KYC verified; entity non-EU. OKX Risk & Compliance Disclosure (2026-07-08) s. 3: neither Russia nor Argentina is a restricted location; Russia only "fiat payment services" restricted (source L8). ToS cl. 7.1: duty to update changed info; cl. 9.1: no multiple accounts (source L9). Also list products restricted for Russia-verified users (source 1 of review) | Note + list of restricted products seen in the account | user + lawyer | open (desk check: no blocker) |
| G1.5 | bybit: (a) user reads the declared residence country in the account; (b) the hold is pursued **only inside the existing ticket**: reply to every request, provide truthful source-of-funds material (exchange history, TxIDs, proof the destination is the user's own wallet/account), ask in the ticket for a written reason category and expected timeline, ask how to update residence to Argentina; (c) do **not** submit new KYC with a different country, do not open another account, do not use another person's identity (Bybit keeps only the first-verified account per ID, source L11). Bybit's excluded list (s. 11.3, updated 2026-05-07) names neither Russia, Argentina, Montenegro, Georgia nor Armenia (source L10) | Note: residence value seen, ticket open date, reason category, outcome; no ticket numbers | user | **at risk** (F7) |
| G1.6 | Residence proof used for KYC (without DNI) is truthful: document type and address match the user's actual situation; no Russian or third-country address declared as current residence while the user lives in Argentina | Note: document type per venue (e.g. "precaria / residence certificate / utility bill / bank statement"), not the document | user; acceptability -> accountant (Q4) | **at risk** (binance F8, bybit F7) |
| G1.7 | Decision on venues that cannot pass G1 by UF: excluded from the GO set or GO deferred. Already decided for bybit: GO numbers with and without Bybit; without Bybit if not resolved. **Proposed: same rule for gateio and binance** | Entry in `docs/pipeline/STATE.md` / ADR by orchestrator | user (via orchestrator) | open |
| G1.8 | No account is with an EU/EEA entity (EU Reg. 833/2014 art. 5b; *current wording unverified*). Montenegro, Georgia, Armenia are not EU/EEA, so a Bybit KYC done there does not by itself mean Bybit EU — user confirms the account is on bybit.com, not bybit.eu | Covered by entity field in G1.1-G1.5 | lawyer + user | open |
| G1.9 | Re-check of every venue after the DNI is issued (F10); update residence proof where the venue asks; no other KYC changes | Note per venue | user + lawyer | open |

Gate G1 is cleared when G1.1-G1.6, G1.8 are `done` for every venue in the GO set and G1.7 records
which venues are excluded.

## G2 — Server / VPS location

| ID | Item (checkable) | Evidence required | Who | Status |
|---|---|---|---|---|
| G2.1 | VPS provider and region chosen and recorded | Note: provider, country/region (no IP addresses) | user + devops | open |
| G2.2 | Region is not on the restricted list of any GO-set venue (at least US, UK, Singapore, Canada, Hong Kong, sanctioned regions; EU/EEA for binance.com since 2026-07-01; EEA limits on Bybit Global; **gateio also lists Argentina, Russia, several EU states, UAE and others** — source L5) | Note: per venue, link + date checked | lawyer | open |
| G2.3 | Public endpoints called from that region return normal data (no HTTP 403/451 geo-block) | Short log excerpt or test output, no keys | devops | open |
| G2.4 | API-key IP whitelist matches the VPS IP only; no VPN/proxy used to hide location from a venue | Note: "whitelist = VPS only, checked <date>" | user | open |
| G2.5 | Where the user logs in from (web/app) is consistent with declared residence (Argentina) | Note by user | user | open |

## G3 — Tax position (Argentina and Russia)

GO is after income tax (F4), so G3.1-G3.3 feed directly into the quant model.

| ID | Item (checkable) | Evidence required | Who | Status |
|---|---|---|---|---|
| G3.1 | Date from which the user is an Argentine tax resident (permanent vs temporary residence, 12-month rule, LIG art. 116 — *unverified for this case*) | Written answer from accountant (date + basis) | accountant (Q1) | **at risk** |
| G3.2 | Income category and rate: 15 % schedular foreign-source vs Argentine-source 5/15 % vs business (third category) income for frequent arbitrage | Written answer from accountant | accountant (Q1) | **at risk** |
| G3.3 | Tax rate used by quant-analyst matches G3.2; pre-tax figure also shown | Link to quant report section | quant-analyst; lawyer verifies match | open |
| G3.4 | Bienes Personales (wealth tax) on crypto held on foreign exchanges: applies or not, rate | Written answer from accountant | accountant (Q2) | open |
| G3.5 | Record-keeping plan: Stage 2 orders/fills/transfers kept >= 5 years (Ley 11.683 art. 56 — *unverified*), export format agreed with accountant | Accountant confirmation + architecture note (review A5) | accountant + architect | open |
| G3.6 | Russian side: tax residency status (183-day rule), foreign-account notifications and reports under 173-FZ, NDFL exposure; Russia-Argentina tax treaty in force or not | Written answer from accountant/lawyer with Russian competence | accountant (Q3) | open |

## G4 — Own name only, no multi-accounting, no third-party KYC

| ID | Item (checkable) | Evidence required | Who | Status |
|---|---|---|---|---|
| G4.1 | Every account used for Nexus is in the user's own name and KYC | User statement, dated | user | open (F5: own passport on all core accounts — statement still to be filed) |
| G4.2 | No second account on any venue; only official sub-accounts. **binance: no new account while the old one exists** — update residence on the old one (G1.1a); a new account would be a duplicate KYC under the same passport (one verified account per person, sources L4 secondary; Binance ToS text *not read*). **bybit: no new account** while the hold is open (Bybit keeps only the first-verified account per ID, L11). A new account is acceptable only after the old one is closed with the venue's written consent | User statement, dated | user | **at risk** (F7, F8) |
| G4.3 | No MEXC/Bitget access via relatives', friends' or purchased KYC, and no misstatement of citizenship; wait for DNI and re-check those venues' rules then | User statement, dated; re-check note after DNI | user; lawyer re-checks ToS after DNI | **at risk** (F2) |
| G4.4 | No account is shared with or operated for another person (no custody of others' money; vision scope "Out") | User statement, dated | user | open |

## User actions (from 2026-10-23 facts)

Ordered by impact. Record results as evidence notes (no identifiers, no screenshots).

1. **All venues:** open profile/verification page, write down only the *country of residence*
   value and KYC level (binance, bybit, gateio, kucoin, okx). Also note the site (e.g. bybit.com
   vs bybit.eu).
2. **gateio:** ask Gate support in writing: "Are users residing in Argentina eligible under the
   User Agreement cl. 2.5, and which entity serves them?" Until a written yes, do not move capital
   there; keep public data only.
3. **binance:** do **not** open a new account. Update residence on the existing account to
   Argentina (Identification -> Edit Address, Argentine proof of address). If a KYC reset is
   offered, follow it on the same account. If refused, ask support in writing what they allow.
   Do not use this account for Nexus until residence = Argentina.
4. **bybit:** keep working inside the one compliance ticket: answer every request, provide
   source-of-funds material truthfully, ask for reason category, timeline and how to update
   residence to Argentina. No new KYC submissions, no new account. Keep a dated log of messages.
5. **kucoin, okx:** confirm residence = Argentina; okx: list products marked unavailable.
6. **When the DNI arrives:** tell the orchestrator; lawyer re-checks all venues and MEXC/Bitget.
7. Bring Q4 + the extra question below to the human accountant/lawyer.

## Questions for a human accountant / lawyer

The five questions are in [`review-vision-architecture.md`](review-vision-architecture.md)
section 7 (Q1-Q5). Mapping: Q1 -> G3.1, G3.2 · Q2 -> G3.4 · Q3 -> G3.6 · Q4 -> G1.1-G1.6 ·
Q5 -> pivot 2 only. Extra questions:
- Q4a: If an exchange holds funds of a Russian national resident in Argentina for compliance
  review for months, what lawful escalation exists (venue complaints channel, regulator of the
  contracting entity, CNV if the venue is a registered PSAV), and must the hold be declared?
- Q4b: Does gateio's listing of Argentina as a Restricted Location make an existing account
  unusable for an Argentine resident, and what is the safe exit (withdraw and close)?
- Q4c: For binance, is a residence change Russia -> Argentina on the existing account (possibly
  moving it to the Argentina-registered entity) the correct path, and does it change tax
  reporting to ARCA?

## Sources for the 2026-10-23 update (accessed 2026-10-23)

Sources 1-17 are in the review. Additional:

- L1. Binance FAQ "How to Update My Residential Address on Binance?" (updated 2024-11-27): https://www.binance.com/en/support/faq/how-to-update-my-residential-address-on-binance-fce08b48060b42e1bb5245cfcd9868a1 ; "How to Set up a Binance Account (Migrant Residents)" (updated 2025-12-19): https://www.binance.com/en/support/faq/how-to-set-up-a-binance-account-migrant-residents-5b3d7d9117d541fca63d532d5126c8a9
- L2. kod.ru, Binance restrictions for Russian accounts (2022-04-21): https://kod.ru/binance-oghranichila-uslugi-russia/ ; The Block (2022): https://www.theblock.co/linked/142788/latest-eu-sanctions-force-binance-to-crack-down-on-russian-users
- L3. kod.ru, Binance denies lifting EUR 10,000 limit (2023-04-18): https://kod.ru/binance-otmena-limita ; CommEX closure 2024 and Binance statement on existing Russian users: https://www.theblock.co/post/284430/binance-russia-commex-closure ; DTF (secondary, 2026 claim that Russia residents cannot newly verify): https://dtf.ru/crypto-top/3703916-binance-v-rossii-v-2025-godu
- L4. Secondary only — one verified account per person on Binance: https://multilogin.com/blog/can-i-have-multiple-binance-accounts/ (vendor blog; Binance ToS page https://www.binance.com/en/terms not readable by the agent — *unverified*)
- L5. Gate User Agreement (last updated 2026-07-22), cl. 2.4-2.5 Restricted Locations incl. Argentina and Russia; cl. 8.7(f), 10.1(a) multiple accounts: https://www.gate.com/user-agreement (*read via automated extraction; human re-read required*)
- L6. Binance CNV PSAV registration (2024-10): https://www.crowdfundinsider.com/2024/10/230780-binance-incorporated-into-argentinas-virtual-asset-service-providers-registry-by-national-securities-commission/ ; https://criptonoticias.com/negocios/binance-registro-proveedores-servicios-bitcoin-argentina
- L7. Datawallet, KuCoin restricted countries (updated 2026-08-04, secondary): https://www.datawallet.com/es/cripto/kucoin-países-restringidos
- L8. OKX Risk and Compliance Disclosure (updated 2026-07-08), s. 3: https://www.okx.com/help/risk-compliance-disclosure
- L9. OKX Terms of Service (updated 2026-10-22), cl. 7.1, 7.6-7.7, 9.1, 13.3: https://www.okx.com/help/terms-of-service
- L10. Bybit "Service Restricted Countries" (updated 2026-05-07; via search snippet, page timed out): https://bybit.com/en/help-center/article/Service-Restricted-Countries
- L11. Bybit Individual KYC FAQ (one account per user for KYC; first-verified account kept): https://www.bybit.com/en/help-center/article/Individual-KYC-FAQ ; Bybit P2P Terms (effective 2026-01-19, multi-account ban): https://www.bybit.com/common-static/compliance/legal/BYBIT/3fbe62695299e8dbb207575b9898047d.pdf
- L12. Secondary, anecdotal — Bybit compliance holds and source-of-funds requests: https://forklog.com/en/?p=22431 ; https://vc.ru/crypto/2968792-aml-blokirovki-na-bybit-prichiny-i-mehanika-proverok (commercial authors; not relied on for rules)

## Change log

- 2026-10-23: created; all gates open, G1/G3/G4 at risk (facts F1-F4).
- 2026-10-23: user facts F5-F10 added; F1 revised (hold, not ban). G1.2 gateio -> blocked pending
  verification (Argentina + Russia in Gate Restricted Locations). G1.1/G1.6 -> at risk (binance
  residence likely Russia). Added G1.1a/b, G1.9, user actions, Q4a-c, sources L1-L12.
