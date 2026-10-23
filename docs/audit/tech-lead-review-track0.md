# Tech-lead review — Track 0 (B1, A4, B1a/A2a, CI, A6)

- Date: 2026-10-23. Reviewer: tech-lead. Round: 1 of max 3.
- Branch: `chore/agent-pipeline-adoption`. Commits: 2862593 (B1), f6b5abb (CI, R-05), 37de0fa (A4),
  c90e37b (B1a/A2a), 6766bfd (A6, committed during this review).
- Working tree at review time: `.env.example` + `docker-compose.local.yml` (`KEY_POLICY_*`
  passthrough) modified but **not committed**; unrelated doc edits (ADR 0006/0008, vision, legal).

## Checks

| Check | Result | Baseline |
|---|---|---|
| `make check` (ruff format/check, mypy --strict, unit) | green; ruff 0, mypy 0 (131 files) | ruff 0, mypy 0 |
| Unit tests | **610 passed**, 12 deselected (integration) | 481 |
| Branch coverage (total) | **90 %** | 89 % |
| `nexus/adapters/key_policy.py` coverage | 97 % (lines 120, 133, 177, 183 uncovered) | n/a |
| ccxt implicit methods exist (binance/bybit/okx/kucoin/gate) | all 5 present in installed ccxt | n/a |
| Empty env `KEY_POLICY_*=` (compose `${VAR:-}`) | parses to `False`, no startup crash | n/a |

## Verdict

- B1, A4, B1a/A2a, CI (R-05): **ACCEPT** (notes below, none blocking).
- A6: **RETURN** (small, round 1). Design is sound and fails closed in every path I traced: pure
  parsers -> rule names, all venues evaluated before raising, booleans/rule names only in logs,
  check runs right after adapter construction and before DB/engine, adapters closed on refusal,
  CLI exit code 3. The points below are small but A6 is the gate for U3 (real keys), so the
  must-fix items should land before U3.

## A6 findings

### Must fix (before U3)

1. **[Medium] Non-`ExchangeError` exceptions escape the runner.** `verify_key_policies`
   (`src/nexus/adapters/key_policy.py:251-257`) catches only `ExchangeError`. `_call`
   (`ccxt_base.py:232-257`) passes through anything that is not `TimeoutError`, `ccxt.BaseError`,
   `IndexError/KeyError/TypeError`, e.g. `ReadOnlyViolationError` (a `NexusError`, not an
   `ExchangeError`), `ConfigurationError`, `ValueError`. Result: still fail-closed (process dies),
   but with a traceback instead of "venue + rule name" (AC2), with exit code 1 instead of 3, and
   the other venues are not reported. Fix: `except Exception as exc` -> `REQUEST_FAILED` (or a
   dedicated `request_blocked` for `ReadOnlyViolationError`), log `type(exc).__name__` only.
   Add a test with a non-`ExchangeError` raised from `fetch_key_info`.
2. **[Medium] Binance and OKX use deny-lists; KuCoin uses an allow-list.** `BINANCE_FORBIDDEN`
   (`key_policy.py:40-50`) and `OKX_FORBIDDEN_PERMS` (`:53`) pass any *new* trade/transfer flag
   or scope the venue adds later. For a fail-closed gate prefer allow-lists: binance — any
   `enable*`/`permits*` boolean that is `true` and not in `{"enableReading", "enableFixReadOnly"}`
   refuses (keep the explicit list as required fields); okx — `scopes - {"read_only"}` non-empty
   refuses. Bybit is acceptable because `readOnly` is authoritative.
3. **[Medium] README contradicts A6.** `README.md:124-129` ("Extension runs") tells the user to
   add MEXC/Bitget keys; with A6 a configured key on a venue without a policy refuses startup
   (`NO_POLICY`). State that extension runs are public-data only (no keys) until a policy exists.
4. **[Low, must] Dead attribute.** `key_info_method` ClassVar in `src/nexus/adapters/cex/bybit.py:16`
   is unused (left over from an earlier design). Remove.
5. **[Low, must] Commit the `KEY_POLICY_*` passthrough** (`.env.example`, `docker-compose.local.yml`,
   currently uncommitted). Without it kucoin/gateio with keys can never pass in Docker. Also the
   card status line ("implemented (uncommitted)") is stale.

### Should fix (can be a follow-up card)

6. **[Low] "One call per venue" vs retries.** `fetch_key_info` goes through `_call`, which retries
   retryable errors up to `max_attempts=3` (`ccxt_base.py:145,251`). Still GET-only, but AC1 says
   one call. Either call with a single attempt or amend AC1 ("one call, retried on transient errors").
7. **[Low] Sequential venues, long worst case.** Per venue up to 3 x 2 x `timeout_ms` (20 s) +
   backoff -> ~1 min; 5 venues ~5 min before refusal. Use `asyncio.gather` per venue (conventions:
   isolated gather) or a single-attempt call.
8. **[Low] Restart loop.** Scanner has `restart: unless-stopped` (`docker-compose.local.yml:119`);
   exit 3 is restarted forever, re-hitting signed endpoints with a refused key. Devops: document,
   or `restart: on-failure:N`, or have healthcheck/alert surface `key_policy_violation`.
9. **[Low] Swallowed parser exception without log.** `KeyPolicyCheck.evaluate`
   (`key_policy.py:205-208`) turns any exception into `UNPARSEABLE` silently. Fail-closed is right;
   add `log.warning(..., error=type(exc).__name__)` per conventions ("never swallow silently").
10. **[Low] Response-derived text in rule names.** KuCoin `permission:{name}` (`:184`) copies
    arbitrary scope strings from the payload into logs/exception. Not secret today; cap length and
    restrict to `[A-Za-z]+`, or map unknown to `permission:unknown_scope`.
11. **[Low] Typing.** `adapters: Mapping[str, object]` + `getattr(..., "fetch_key_info")` bypasses
    mypy. A small `IKeyIntrospection` Protocol in `nexus/interfaces/` matches the ports style of
    `target.md`.
12. **[Low, U3] IP wildcard set** (`:37`) misses broad CIDRs (`/0`-`/8` style ranges). Decide at
    U3 whether any CIDR wider than /32 (/128) counts as unbound.
13. **[Low] AC5 test scope.** Guard test checks `_rest` only. Correct today (WS and transfer
    fallback are unauthenticated), but add an assertion that `_ws`/fallback carry no `apiKey`,
    so a future authenticated WS client fails the test.

## Notes on other commits (accept)

- B1: clean; `CORE_EXCHANGES` single source of truth, tests added.
- A4: URL-credential regex `://[^:/@\s]*:[^@\s]+@` is fine for DSNs; it can over-redact
  `http://host:port/path?x=a@b` (cosmetic only).
- B1a/A2a: hook pinned and in sync with CI version. `docs/guides/stage-1-local-setup.md` section 7
  checklist still lists MEXC and Bitget keys — drop them (same fix as point 3).
- CI: SHA-pinned actions, `contents: read`, no secrets, `persist-credentials: false`, gitleaks
  checksum-verified, test DB name asserted (R-01). First run still pending (STATE.md).
- Process: todo.md A6 was ticked in the same commit before reviews; acceptable per workflow, but
  untick if this RETURN is not closed before U3.
