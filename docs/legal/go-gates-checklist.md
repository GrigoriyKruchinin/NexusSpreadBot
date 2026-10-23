# Legal GO gates G1-G4 — checklist

Date: 2026-10-23. Author: lawyer agent. Status: **all gates open; none cleared.**
**Not legal advice.** Preliminary checklist. Items marked *unverified* in the source review need a
human lawyer/accountant or an official source before they are relied on.

Source of the gates: [`review-vision-architecture.md`](review-vision-architecture.md) section 1.
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
  store** KYC documents, passport/DNI numbers, account IDs, API keys, balances or screenshots
  showing them — only "checked on <date>, result: <yes/no>, source: <page name/URL>".
- Re-check every gate at UF (GO/NO-GO) and whenever a venue changes its ToS or the user's
  residence/document status changes (e.g. DNI issued).

## Known facts (from the user, 2026-10-23)

| # | Fact | Effect |
|---|---|---|
| F1 | **Bybit account is blocked by the exchange; reason unknown.** No Bybit keys. | G1 at risk (bybit KYC cannot be confirmed); G4 at risk (temptation to open a second account). Bybit cannot be a GO leg until resolved. |
| F2 | No MEXC/Bitget accounts: they do not accept RF citizenship; user waits for Argentine DNI (~2027-04). | Already excluded from GO analytics (ADR 0002, `CORE_EXCHANGES`). G4: must not be worked around. |
| F3 | Residence and contracting entity on the core accounts are **not yet confirmed**. | G1 open for binance, gateio, kucoin, okx. |
| F4 | GO bar is measured **after income tax** (user decision). | G3 is a hard input to the money criterion, not only a compliance item. |

## Summary

| Gate | Subject | Status | Main reason |
|---|---|---|---|
| G1 | KYC/residence truthful and consistent, global (non-EU) entity | **at risk** | Bybit blocked (F1); others unconfirmed (F3) |
| G2 | VPS/server location not restricted for any core venue | open | VPS not chosen/checked yet |
| G3 | Argentine and Russian tax position known | **at risk** | GO is after-tax (F4) but residency start, rate and category are unverified |
| G4 | No foreign-name accounts, no multi-accounting, no third-party KYC | **at risk** | F1 + F2 create pressure to work around blocks |

## G1 — KYC / residence on every core account

Core venues: binance, bybit, gateio, kucoin, okx (per review; final GO set may shrink, see G1.7).

| ID | Item (checkable) | Evidence required | Who | Status |
|---|---|---|---|---|
| G1.1 | binance: profile shows country of residence = Argentina; KYC level verified; contracting entity is the global/non-EU entity (ToS "you are contracting with" section) | Note: date, residence field value, entity name from ToS/account page | user (lawyer reads ToS entity list) | open |
| G1.2 | gateio: same three checks | same | user + lawyer | open |
| G1.3 | kucoin: same three checks | same | user + lawyer | open |
| G1.4 | okx: same three checks; also confirm which products are restricted for Russia-nationality users (2023 restrictions, source 1 of review) | same + list of restricted products seen in the account | user + lawyer | open |
| G1.5 | bybit: **account blocked, reason unknown.** User asks Bybit support for the reason in writing (ticket), without new KYC submissions that misstate anything | Note: ticket date, stated reason (category only, e.g. "nationality", "document", "unknown"), outcome | user | **at risk** |
| G1.6 | Residence proof used for KYC (without DNI) is truthful: the document type and address match the user's actual situation; no Russian address declared as current residence if user lives in Argentina, and vice versa | Note: document type used per venue (e.g. "precaria / residence certificate / utility bill"), not the document itself | user; acceptability -> accountant (Q4) | open |
| G1.7 | Decision on venues that cannot pass G1 (bybit now): excluded from the GO set or GO deferred | Entry in `docs/pipeline/STATE.md` / ADR by orchestrator | user (via orchestrator) | open |
| G1.8 | No account is with an EU/EEA entity (EU Reg. 833/2014 art. 5b custody bar for Russian nationals without EU/EEA/CH residence; *current wording unverified*) | Covered by entity field in G1.1-G1.5 | lawyer | open |

Gate G1 is cleared when G1.1-G1.4, G1.6, G1.8 are `done` for every venue in the GO set and G1.5/G1.7
are resolved (bybit either `done` or excluded by decision).

## G2 — Server / VPS location

| ID | Item (checkable) | Evidence required | Who | Status |
|---|---|---|---|---|
| G2.1 | VPS provider and region chosen and recorded | Note: provider, country/region (no IP addresses) | user + devops | open |
| G2.2 | Region is not on the restricted list of any GO-set venue (at least US, UK, Singapore, Canada, Hong Kong, sanctioned regions; EU/EEA for binance.com since 2026-07-01; EEA limits on Bybit Global) | Note: per venue, link to its current restricted-jurisdictions page and date checked | lawyer | open |
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
| G4.1 | Every account used for Nexus is in the user's own name and KYC | User statement, dated | user | open |
| G4.2 | No second account on any venue; only official sub-accounts. In particular **no new Bybit account** while the old one is blocked (would breach anti-multi-account clauses and can freeze both) | User statement, dated | user | **at risk** (F1) |
| G4.3 | No MEXC/Bitget access via relatives', friends' or purchased KYC, and no misstatement of citizenship; wait for DNI and re-check those venues' rules then | User statement, dated; re-check note after DNI | user; lawyer re-checks ToS after DNI | **at risk** (F2) |
| G4.4 | No account is shared with or operated for another person (no custody of others' money; vision scope "Out") | User statement, dated | user | open |

## Questions for a human accountant / lawyer

The five questions are in [`review-vision-architecture.md`](review-vision-architecture.md)
section 7 (Q1-Q5). Mapping: Q1 -> G3.1, G3.2 · Q2 -> G3.4 · Q3 -> G3.6 · Q4 -> G1.1-G1.6 ·
Q5 -> pivot 2 only (not a GO gate). Suggested extra item for Q4 given F1: "If an exchange blocks
the account of a Russian national resident in Argentina, what can the user lawfully do to recover
funds or the account, and does the block need to be declared anywhere?"

## Change log

- 2026-10-23: created; all gates open, G1/G3/G4 at risk (facts F1-F4).
