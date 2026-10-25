# Security review — HT1 S0-S8 (commits a7ba759..019c76f)

Date: 2026-10-25 · Reviewer: security (read-only) · Branch: `chore/agent-pipeline-adoption`
Scope: `git diff a7ba759~1..019c76f` (perp adapters S1-S4, S0 safety rules, S5 transfer metadata,
S6-S8 simulation, fixture script, fixtures). Uncommitted S9/S10 work (`hedged.py` diff,
`hedged_portfolio.py`) was **not** reviewed.
Context: ADR 0001, ADR 0009, HT1 card, design review C11.

## Verdict: ACCEPT (with 3 non-blocking should-fix items, F1-F3)

No path exists in the S0-S8 code to place an order, change leverage/margin/position mode, or move
funds. The adapters run without keys, and the runtime GET-only guard is in place.

## 1. Perp adapters (okx, kucoin, binance usdm)

| Check | Result |
|---|---|
| Client has no credentials | PASS. `_client_config()` has no credential keys, and `PerpAdapterFactory(options)` cannot take a key. The constructor raises `ReadOnlyViolationError` if an injected client has `apiKey`/`secret`. Test: `test_real_client_has_no_credentials_and_guard`, `test_adapter_refuses_client_with_credentials`. |
| Cannot sign | PASS. With no credentials, ccxt `check_required_credentials` raises `AuthenticationError` before any I/O when a private method is called. Test: `test_implicit_private_trading_method_is_unreachable` (one per venue). |
| Read-only guard blocks POST/DELETE/PUT | PASS. `install_read_only_guard` wraps `client.fetch` with no POST allowlist. Tested for POST/DELETE/PUT/lower-case and through `request()`. |
| Implicit private calls | PASS. `fetchCurrencies: False` on all three (this stops the Binance `sapi` and OKX private currency calls). Every endpoint used is a public GET (see the docstrings in each adapter). KuCoin `fetch_mark_ohlcv` goes to the public unified kline endpoint; the fixtures were recorded with no keys, which confirms it is public. |
| Binance `leverageBracket` never called | PASS. `BinanceUsdmAdapter.fetch_leverage_tiers` returns `None` with no `await`. Covered by an AST test (`test_binance_adapter_source_never_references_signed_brackets`) and a call-log test. |
| Logging | PASS. Error text is `scrub()`-ed, URLs are masked and the message is cut to 160 chars. No headers or keys are logged (and none exist). |

## 2. S0 `test_safety` rules

The C11 patterns are present: `set_?leverage`, `set_?margin\w*`, `set_?position_?mode` and
`(add|reduce)_?margin`, all case-insensitive and anchored. They are tested in both snake_case and
camelCase. The perp port test (`test_perp_port_is_read_only`) and the interfaces test now cover
`nexus.interfaces.perp`.

**F1 (should-fix, test-only).** The static regex misses these names (I checked each against the
compiled regex):
- `futuresPrivatePost*` / `futures_private_post_*`. These are KuCoin futures implicit methods,
  e.g. `futuresPrivatePostOrders` and `futuresPrivatePostPositionMarginDepositMargin`. The
  `(private|sapi|...)` alternative is anchored at the start, so a `futures` prefix gets past it.
- The ccxt unified methods `close_position` / `closeAllPositions` (they place orders),
  `borrow*Margin`, `repay*Margin` and `modifyMarginHelper`.

None of these can run today: there are no credentials (so `AuthenticationError`) and the runtime
guard blocks the POST. This is a gap in the defence-in-depth layer only. Suggested fix: change the
last alternative to `\w*(private|sapi|papi|fapi|dapi|v\d)\w*(post|put|delete)\w*`. Add
`close_?\w*position\w*|(borrow|repay)\w*margin\w*|modify_?margin\w*`, plus parametrized bypass
cases for them.

**Note.** The static scan only covers `src/`. `scripts/` is not scanned (see F2).

## 3. S5 `list_transfer_routes`: SIGN-OFF GRANTED

`nexus.engine.transfer.list_transfer_routes`:
- It is pure. Its module imports only `re`, `decimal`, `typing` and domain models. It makes no
  I/O, network, DB or logging calls. Its input is two `AssetTransferInfo` values; its output is a
  tuple of `(code, NetworkInfo, NetworkInfo)`.
- It has no withdrawal capability. It reads public network metadata (withdraw/deposit enabled
  flags, fee, contract). It never builds addresses, never builds a request and never calls a
  client. It uses the same rules as the already-allowlisted `select_transfer_route`.
- The allowlist matches by exact name only, and no ccxt method has this name, so the entry does
  not open a bypass.
- The new `NetworkInfo` fields (`withdraw_min`, `deposit_min`, `deposit_confirmations`,
  `est_arrival_min`, `busy`) are public metadata. CLAUDE.md rule 1 allows reading them.

Action: the comment `security sign-off pending` in `tests/unit/test_safety.py` can be changed to
`security sign-off 2026-10-25 (docs/audit/security-review-HT1-S0-S8.md)`.

## 4. Fixture script and fixtures

`scripts/record_perp_fixtures.py`: it creates clients with no credentials and exits if `apiKey`
is set. It calls only public GET methods, never asks for Binance tiers, and writes only ccxt
public payloads.

**F2 (should-fix, low).** The docstring says "the read-only guard is installed, like the
production adapters", but the script never calls `install_read_only_guard`. The real protection is
the missing keys, so the risk is low. Either install the guard or fix the docstring. `scripts/` is
also outside the AST safety scan; consider adding `scripts/` to the scan roots.

Fixtures (`tests/fixtures/perp/**`, `tests/fixtures/networks/pre_s5_snapshot.json`): I grepped for
`apiKey|secret|password|uid|accountId|userId|subAccount|balance|address|email|token` keys and found
0 hits. The content is public instruments, tickers, books, funding, klines, tiers and network
metadata. Token contract addresses are public. No account data.

## 5. Dependencies and secrets

- No dependency changes: `pyproject.toml`, `uv.lock`, Dockerfile, compose and CI are untouched in
  this range. A pip-audit is not needed for this delta.
- Diff secret scan (grep for key/secret/password/token assignments): the only hits are `None` /
  test placeholder `"k"` in test doubles. No real values.
- **F3 (info).** `adapter_close_failed` logs `repr(exc)` without scrubbing. There are no
  credentials, so nothing leaks today. Use `scrub()` there for consistency.

## Checks run

- `uv run pytest tests/unit/test_safety.py tests/unit/adapters/test_perp_adapters.py tests/unit/adapters/test_transfer_metadata.py -q`: 97 passed.
- Regex probe of `_FORBIDDEN_CALL` against perp method names (results in F1).
- Full `make check` was not run, because files are being edited in parallel (S9/S10).
