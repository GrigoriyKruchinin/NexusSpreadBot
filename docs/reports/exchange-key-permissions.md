# Exchange API key permission introspection (core venues)

- Author: crypto-specialist
- Date / access date of all sources: 2026-10-23
- Input: security review finding S-08 (`docs/audit/security-review-architecture.md`),
  `CORE_EXCHANGES = ("binance", "bybit", "gateio", "kucoin", "okx")` (`src/nexus/config/groups.py`).
- Scope: documentation research only. No API was called, no key was used, no code was changed.
- Legend: **[V]** verified on the official doc page cited; **[I]** inferred from official docs
  (not stated literally); **[U]** unverified (not found in official docs on the access date;
  must be confirmed on a real read-only key during U3 before relying on it).

## Summary

| Venue | Self-introspection endpoint | Permissions exposed | IP whitelist exposed | Startup check feasible |
|---|---|---|---|---|
| binance | `GET /sapi/v1/account/apiRestrictions` [V] | yes, per-scope booleans [V] | `ipRestrict` bool [V] | **yes, full** |
| bybit | `GET /v5/user/query-api` [V] | `readOnly` 0/1 + `permissions` groups [V] | `ips` array [V] | **yes, full** |
| okx | `GET /api/v5/account/config` [V] | `perm` = read_only/trade/withdraw [V] | `ip` string [V] | **yes, full** |
| kucoin | `GET /api/v1/user/api-key` [V] | `permission` CSV string [V] | not in current docs [U] | **permissions yes, IP no** |
| gateio | none for the current key's scopes [U] | no (see fallback) | `GET /account/detail` `ip_whitelist` [V] | **IP yes, permissions no** |

All introspection endpoints are signed `GET` requests, so they pass the existing GET-only guard.
None of them changes state. Never probe permissions by calling a trade, transfer or withdraw
endpoint (even with invalid params): that is forbidden by ADR 0001 / hard rule 1.

## Per-venue detail

### binance

| Item | Value |
|---|---|
| Endpoint | `GET /sapi/v1/account/apiRestrictions` (base `https://api.binance.com`) [V] |
| Auth | `USER_DATA`, HMAC-signed, header `X-MBX-APIKEY`, params `timestamp` (+ `recvWindow` <= 60000) [V] |
| Weight | 1 (IP) [V] |
| Response fields | `ipRestrict`, `createTime`, `enableReading`, `enableWithdrawals` (needs IP restriction), `enableInternalTransfer`, `enableMargin`, `enableFutures`, `permitsUniversalTransfer`, `enableVanillaOptions`, `enableFixApiTrade`, `enableFixReadOnly`, `enableSpotAndMarginTrading`, `enablePortfolioMarginTrading` (all bool except `createTime`) [V] |
| Refuse-to-start rule | any of `enableWithdrawals`, `enableInternalTransfer`, `permitsUniversalTransfer`, `enableSpotAndMarginTrading`, `enableMargin`, `enableFutures`, `enableVanillaOptions`, `enablePortfolioMarginTrading`, `enableFixApiTrade` is `true`; or `enableReading` is `false` |
| IP rule | `ipRestrict == false` -> refuse (or loud warning if policy allows; recommend refuse) |
| Fee / network metadata | `GET /sapi/v1/capital/config/getall`, `USER_DATA` signed, IP weight 10 [V]. Per `networkList[]`: `network`, `depositEnable`, `withdrawEnable`, `withdrawFee`, `withdrawMin`, `withdrawMax`, `withdrawIntegerMultiple`, `minConfirm`, `busy`, `depositDesc`/`withdrawDesc` [V]. No explicit permission named; reading-only key is sufficient [I] (endpoint is a read `USER_DATA` call). |

### bybit

| Item | Value |
|---|---|
| Endpoint | `GET /v5/user/query-api` [V] |
| Auth | signed headers `X-BAPI-API-KEY`, `X-BAPI-TIMESTAMP`, `X-BAPI-RECV-WINDOW`, `X-BAPI-SIGN` [V]; "Any permission can access this endpoint" [V] |
| Rate limit | not stated on the page; see Bybit rate-limit page [U] |
| Response fields | `readOnly` (0 = read+write, 1 = read only), `permissions` object (`ContractTrade`, `Spot`, `Wallet` [`AccountTransfer`, `SubMemberTransfer`, `SubMemberTransferList`, `Withdraw`], `Options`, `Derivatives`, `Exchange`, `Earn`, `FiatP2P`, ...), `ips` (bound IPs), `type` (1 personal / 2 third-party app), `deadlineDay`, `expiredAt`, `isMaster`, `parentUid`, `uta`, `isFixApi` [V] |
| Refuse-to-start rule | `readOnly != 1`; or `permissions.Wallet` contains `Withdraw`, `AccountTransfer` or `SubMemberTransfer*` |
| IP rule | `ips` empty or wildcard -> refuse. Exact representation of "no IP bound" (empty array vs `["*"]`) [U]; treat both as unbound. Note `deadlineDay`/`expiredAt` are set only for keys without IP binding [V] - a useful secondary signal. |
| Caveat | The official example shows `readOnly: 1` together with trade groups listed in `permissions`; the doc does not explain the interaction [V]. Therefore `readOnly` is the authoritative flag; group lists are scopes, not write rights [I]. Confirm on a real key at U3 [U]. |
| Fee / network metadata | `GET /v5/asset/coin/query-info` (signed). `chains[]`: `withdrawFee` (empty = withdrawal unsupported), `withdrawPercentageFee`, `withdrawMin`, `chainDeposit`/`chainWithdraw` (0 suspended / 1 normal), `confirmation` [V]. Permission not stated on the page [U]; read-only key expected to work [I]. |

### okx

| Item | Value |
|---|---|
| Endpoint | `GET /api/v5/account/config` [V] |
| Auth | headers `OK-ACCESS-KEY`, `OK-ACCESS-SIGN`, `OK-ACCESS-TIMESTAMP`, `OK-ACCESS-PASSPHRASE` [V] (passphrase is a secret) |
| Rate limit | 5 requests / 2 s per User ID [V] |
| Response fields | `perm` - "The permission of the current requesting API key", values `read_only`, `trade`, `withdraw` (comma-separated) [V]; `ip` - "IP addresses that linked with current API key", empty string if none [V]; `label`, `uid`, `mainUid` [V] |
| Refuse-to-start rule | `perm` (split on `,`) contains `trade` or `withdraw`, or does not contain `read_only` |
| IP rule | `ip == ""` -> refuse. Note: OKX expires keys without IP binding after a period of inactivity [U] |
| Fee / network metadata | `GET /api/v5/asset/currencies` (Funding account, signed). Official section could not be loaded on the access date (doc page truncated in fetch); fields from prior knowledge, all [U]: `canDep`, `canWd`, `canInternal`, `minWd`, `maxWd`, `fee` (fixed on-chain withdraw fee) with `minFee`/`maxFee` possibly deprecated, `chain`, `mainNet`, `wdQuota`; permission "Read" [U]; rate limit ~6 req/s [U]. A third-party SDK doc says funding methods require auth [I]. Verify on a read-only key at U3. |

### kucoin

| Item | Value |
|---|---|
| Endpoint | `GET /api/v1/user/api-key` ("Get API Key Info", returns info on the calling key; works for master and sub-account keys) [V] |
| Auth | private, API permission `General` (= read-only scope) [V]; KuCoin signed headers incl. passphrase (secret) |
| Rate limit | pool `Management`, weight 20 [V] |
| Response fields | `remark`, `apiKey`, `apiVersion`, `permission` (CSV, e.g. `General,Futures,Unified,Spot,Earn,InnerTransfer,Margin`), `createdAt`, `uid`, `isMaster`, `region`, `kycStatus`, `siteType` [V]. No per-field descriptions [V]. |
| Refuse-to-start rule | `permission` contains anything other than `General` (in particular `Spot`, `Margin`, `Futures`, `Unified`, `Earn`, `Withdrawal`, `InnerTransfer`, `FlexTransfers`, `LeadtradeFutures`). Permission names per KuCoin API-permission list [V]. |
| IP rule | IP whitelist is **not** in the documented response [V]; legacy docs may have had an `ipWhitelist` field [U]. Fallback: user-attested in the U3 guide (screenshot not needed; checkbox "IP restriction enabled, host IP only"). Note: KuCoin requires IP restriction for `Withdrawal`/`FlexTransfers` scopes [V], irrelevant for a General-only key. |
| Fee / network metadata | `GET /api/v3/currencies` - **public**, no key, weight 3 [V]. `chains[]`: `withdrawalMinFee`, `withdrawFeeRate`, `withdrawalMinSize`, `isWithdrawEnabled`, `isDepositEnabled`, `confirms`, `needTag`, `maxWithdraw` [V] (fields shown by example only, semantics of fee-rate vs min-fee not defined [U]). |

### gateio

| Item | Value |
|---|---|
| Self-introspection | No documented endpoint returning the **current key's** permission scopes [U]. `GET /account/main_keys` (added v4.105.11, "query all main account API key information") exists [V], but its response schema/auth scope could not be found [U]; it likely needs main-account rights and may need more than read-only [U]. Sub-account key model has `perms[] {name, read_only}` [V] - main_keys may reuse it [U]. |
| IP whitelist | `GET /account/detail` (apiv4 signed, no params) returns `ip_whitelist` (list), `currency_pairs`, `user_id`, `tier`, `key.mode`, `copy_trading_role` [V]; changelog v4.43.0: "Get API key's ip whitelist in GET /account/detail" [V]. |
| IP rule | `ip_whitelist` empty -> refuse. |
| Permission fallback (safe) | 1) U3 guide instructs: every permission group (`spot`, `futures`, `delivery`, `wallet`, `withdrawal`, `account`, `earn`, `margin`, `unified`, `loan`, `options`, `copy`, `custody`) set to **Read-only** or **Disabled**, never Read-write [V for group names / levels]. 2) Optional, after U3 verification: call `GET /account/main_keys` and refuse if any `perms[].read_only == false` for the matching key [U]. 3) Never probe with POST/DELETE. Startup check for gateio is therefore "IP-only + user attestation" until (2) is verified. Gate docs: "All GET operations are read requests, while others are write requests" [V]. |
| Fee / network metadata | `GET /wallet/withdraw_status` (apiv4 signed) [V]: `withdraw_fix`, `withdraw_percent`, `withdraw_fix_on_chains` (dict chain->fee), `withdraw_percent_on_chains`, `withdraw_amount_mini`, `withdraw_day_limit`, `withdraw_eachtime_limit`, `deposit` [V]. Requires wallet **read-only** permission [I] (GET = read; wallet read-only scope documented). Chain status: `GET /wallet/currency_chains?currency=X` - **public** [V]: `chain`, `is_disabled`, `is_deposit_disabled`, `is_withdraw_disabled`, `decimal`, `contract_address` [V]. Note: low-liquidity currencies not returned by API (changelog v4.105.24) [V]. |

## Read-only access to transfer metadata (question 3)

| Venue | Withdraw fee | Network deposit/withdraw status | Key needed | Read-only enough |
|---|---|---|---|---|
| binance | `capital/config/getall` | same | yes | yes [I] |
| bybit | `asset/coin/query-info` | same | yes | yes [I], confirm [U] |
| okx | `asset/currencies` | same | yes [I] | yes [U] |
| kucoin | `api/v3/currencies` | same | **no (public)** | n/a |
| gateio | `wallet/withdraw_status` | `wallet/currency_chains` (public) | fee: yes; status: no | yes [I] |

## Recommendations for S-08 / target.md "Key policy"

1. Implement a per-venue `KeyPolicyCheck` at scanner startup (GET-only, one call per venue):
   binance/bybit/okx = full check (refuse on any trade/withdraw/transfer scope or missing IP binding);
   kucoin = permission check + IP by attestation; gateio = IP check + permission by attestation.
2. Policy for unknown/new fields: if the response cannot be parsed or a required field is missing,
   **refuse to start** (fail closed), log venue + reason only (never the key or response body).
3. Do not log the full introspection response: bybit returns `apiKey`, okx returns `uid`/`label`;
   treat as sensitive and log booleans only.
4. Items marked [U] must be confirmed on the user's real read-only keys during U3 (a guided
   one-time run), then this report updated.

## Sources (accessed 2026-10-23)

- Binance, Get API Key Permission and account endpoints: https://developers.binance.com/docs/wallet/account/api-key-permission
- Binance, All Coins' Information: https://developers.binance.com/docs/wallet/capital
- Bybit, Get API Key Information: https://bybit-exchange.github.io/docs/v5/user/apikey-info
- Bybit, Get Coin Info: https://bybit-exchange.github.io/docs/v5/asset/coin-info
- OKX, API v5 docs (Get account configuration): https://www.okx.com/docs-v5/en/#trading-account-rest-api-get-account-configuration
- OKX, Get currencies (section not retrievable on access date): https://www.okx.com/docs-v5/en/#funding-account-rest-api-get-currencies
- KuCoin, Get API Key Info: https://www.kucoin.com/docs-new/rest/account-info/account-funding/get-apikey-info
- KuCoin, API permissions overview: https://www.kucoin.com/docs/rest/account/basic-info/get-api-key-info
- KuCoin, Get All Currencies: https://www.kucoin.com/docs-new/rest/spot-trading/market-data/get-all-currencies
- Gate, API v4 docs (permissions, changelog): https://www.gate.com/docs/developers/apiv4/en/
- Gate official SDK model docs: https://github.com/gateio/gateapi-python/blob/master/docs/AccountApi.md ,
  https://github.com/gateio/gateapi-python/blob/master/docs/AccountDetail.md ,
  https://github.com/gateio/gateapi-python/blob/master/docs/WalletApi.md ,
  https://github.com/gateio/gateapi-python/blob/master/docs/WithdrawStatus.md ,
  https://github.com/gateio/gateapi-python/blob/master/docs/CurrencyChain.md ,
  https://github.com/gateio/gateapi-python/blob/master/docs/SubAccountKeyPerms.md
