# 11 - Legal and Compliance (PRELIMINARY - NOT LEGAL ADVICE)

Date: 2026-10-23. Prepared by an automated code audit. Web sources were NOT consulted (no verification performed); statements come from general knowledge and must be confirmed with current official texts and a qualified lawyer/accountant.

## 1. What the project does (legally relevant facts)

- Reads public market data (REST/WebSocket) from Bybit, Binance, OKX, Gate.io, KuCoin (and MEXC, Bitget per README) and optionally uses read-only authenticated endpoints for fee/deposit-withdrawal status.
- Never places orders and never withdraws or transfers (code audit: see 06-security-baseline.md, section 7). V1 sends Telegram alerts only; paper trading is simulated.
- Personal, self-hosted tool. Future V2 (trading) and V3 (dashboard) would change the legal profile significantly.

## 2. Project license

- No `LICENSE` file in the repository root and no `license` field in `pyproject.toml` (checked). Without a license, default copyright applies: nobody else may legally use, modify or redistribute the code. If the repo is public, add an explicit license (MIT/Apache-2.0 for open source, or "All rights reserved" notice if proprietary).
- Choice interacts with dependencies (see 3); permissive licenses are compatible with all runtime dependencies listed below.

## 3. Dependency licenses (from general knowledge; not machine-verified)

| Dependency | Expected license |
|---|---|
| ccxt | MIT |
| celery | BSD-3-Clause |
| httpx | BSD-3-Clause |
| pydantic / pydantic-settings | MIT |
| SQLAlchemy | MIT |
| alembic | MIT |
| asyncpg | Apache-2.0 |
| redis-py | MIT |
| structlog | MIT or Apache-2.0 |
| protobuf | BSD-3-Clause |
| Docker images: python (PSF-like), postgres (PostgreSQL License), redis 7.x (BSD-3; Redis 7.4+ moved to RSALv2/SSPLv1, and Redis 8 added AGPLv3 option) | see note |

Action: run `uv run pip-licenses` (or `liccheck`) to verify transitive licenses. Note on `redis:7-alpine`: tag 7 stays on the BSD-licensed line up to 7.2; later 7.x tags may carry the source-available license. Using the server image internally is generally fine, but redistribution/SaaS offerings need review; Valkey is a BSD alternative.

## 4. Personal data

- Telegram chat id (identifier of the operator/users), Telegram bot token (credential), possibly username if added later.
- Logs and PostgreSQL store market evaluations (not personal data), and may store chat ids / delivery receipts; `json-file` logs are retained locally (10 MB x 5 per service).
- Exchange API keys are credentials, not personal data, but identify an account holder.
- If only the owner uses the bot, GDPR/Argentine Ley 25.326 (Personal Data Protection) impact is minimal (household exemption). If alerts are sent to third parties or a public channel/subscribers are added, you become a data controller: privacy notice, retention policy, and security measures needed.
- Retention settings exist for snapshots/evaluations/episodes (`MAINTENANCE_*_RETENTION_DAYS`); define a retention for logs.

## 5. Exchange terms of service / automated access

Not verified against current ToS (no web access used). General position:
- All five exchanges publish public REST/WebSocket APIs intended for programmatic access, with rate limits and IP bans for abuse. Market-data reading and read-only API keys are normally allowed.
- Risks: exceeding rate limits (temporary bans), using API keys from restricted jurisdictions or via VPNs/VPS in other countries (account freezes), sharing keys, and commercial redistribution of market data (many exchanges restrict re-publication of their data; alerts to third parties may fall under that).
- Account/jurisdiction restrictions: Binance (global entity vs Binance.US), Bybit, OKX, KuCoin and Gate.io each limit access by country and require KYC for withdrawals; check that an Argentina-resident user and a hosting-VPS IP are acceptable. Some exchanges (e.g. Bybit, OKX) have publicly changed local access rules over time.
- Arbitrage trading (V2) is generally permitted but market-manipulation clauses (wash trading, spoofing) and API-trading rules apply; some venues prohibit cross-account self-matching.
- Action: before V2, read each exchange's current API Terms, Risk Disclosure, and prohibited-jurisdictions pages and archive dated copies.

Sources to check (official, unverified): developers/API docs and "Terms of Use"/"API Terms" pages of bybit.com, binance.com, okx.com, gate.io, kucoin.com.

## 6. Argentina - regulation and tax overview (verify with current law)

Regulation (general knowledge as of training; may be outdated):
- Law 27.739 (2024) amended AML rules to include virtual asset service providers (PSAV). CNV Resolution 994/2024 created the PSAV registry and Resolution 1058/2025 set operating requirements. Providers offering exchange, custody, transfer or brokerage services to third parties in/from Argentina must register with CNV.
- A personal scanner that only reads data and alerts the owner is not a PSAV. Offering signals, paid alerts, or managing/executing trades for others, or custody, could trigger CNV/UIF obligations (and, for investment advice, further rules). V2 trading with own funds on foreign exchanges is not itself PSAV activity.
- Exchange-control (BCRA/cepo) rules mainly govern fiat/FX; crypto flows via foreign exchanges have had specific reporting (e.g., ARCA/AFIP information regimes for foreign accounts and PSAV reporting).

Tax (indicative):
- Profits from crypto trading are generally taxable income for Argentine residents (Ganancias, cedular regime for digital assets sale; rates and treatment have changed in 2023-2025). Arbitrage profits repeated frequently may be classified as habitual activity (Monotributo/Responsable Inscripto, IVA/Ingresos Brutos implications).
- Holdings abroad may require reporting (Bienes Personales, foreign assets, ARCA regimes such as the foreign-account information duty).
- Keep complete records: paper results are not taxable; real trades and fees must be logged with timestamps, prices in ARS equivalent, and exchange statements. V2 should export trade ledgers.

## 7. DEX (V3+) notes

- Sanctions: US OFAC designated Tornado Cash (2022, delisted March 2025 after court rulings) and other addresses; interacting with sanctioned addresses/pools can create liability even via smart contracts. Screen routes/tokens; avoid mixers and sanctioned token contracts; use an address blocklist.
- Smart-contract risk: exploits, rug pulls, honeypot tokens (sell-blocked), fee-on-transfer/rebasing tokens, malicious proxies/upgradable contracts, oracle/bridge failures. Cross-chain bridges are a major loss vector.
- Operational DEX risk: MEV/front-running, failed-transaction gas costs, approvals (unlimited allowances), private-key custody (a hot wallet would conflict with the CLAUDE.md rule against fund transfer; a DEX layer needs a separate safety design).
- Regulation: DeFi interaction by an individual is generally unregulated in Argentina but taxable; operating a front-end for others is a different matter.

## 8. Questions for a human lawyer / accountant

1. Does sending paid or shared alerts (signals) to third parties require CNV registration (PSAV or investment advice) in Argentina?
2. Is an Argentine resident allowed under each exchange's ToS to use their API from a foreign VPS, and what are the consequences of IP/jurisdiction mismatches?
3. How are arbitrage gains taxed for an individual (Ganancias cedular vs. habitual business activity, Monotributo limits, IVA, Ingresos Brutos)? What records are required?
4. What foreign-asset and foreign-account reporting duties apply (Bienes Personales, ARCA/CNV information regimes)?
5. Does republishing exchange market data (prices, order books) in alerts, dashboards or to subscribers breach data-licensing terms?
6. If V2 trades automatically, any additional obligations (UIF/AML, tax withholding, liability for erroneous orders)?
7. Which license should the repository carry, and is publishing the code allowed given exchange-API trademark/branding rules?
8. Data protection: obligations if Telegram users other than the owner receive messages (registration of databases with AAIP, consent, retention)?
9. DEX use: sanctions-screening duties and liability for interacting with sanctioned or hacked-fund addresses.
