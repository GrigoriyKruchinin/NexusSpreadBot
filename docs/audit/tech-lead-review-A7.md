# Tech-lead review A7 — round 1 (commits f28db06, 8670a2f)

- Reviewer: tech-lead, 2026-10-23. Card `docs/tasks/track0/A7-config-file.md`, spec
  `docs/audit/security-config-split-A7.md`, handoff `docs/handoffs/A7-to-review.md`.
- Scope: source priority, no default change, missing-file behaviour, run hash vs B15 `config_hash`,
  maintainability, compose/CI/docs, tests. Guard internals are reviewed by security separately.
- Checks: `make check` green — 867 unit tests passed (baseline 721), ruff 0, mypy --strict 0; branch
  coverage 91 % (floor 89 %). No integration run, no DB, `.env` not read.

## Verdict: RETURN (2 medium points; low points may be fixed in the same round or ticketed)

## What was verified and is fine
- Priority env > `.env` > TOML > default holds for scalars and lists: probed with the repo TOML in
  container mode — `EXCHANGES_ENABLED=binance,okx` and `CONDITIONAL_VENUES=okx` replace the TOML lists,
  `CONDITIONAL_VENUES=[]` gives `()`, empty env falls through to TOML (same as the pre-A7 default
  fallback), `PAPER_VENUE_SETS` (string) replaces. Init kwargs beat TOML (tested).
- No default change: `test_repo_toml_equals_code_defaults` compares typed dumps with/without file;
  TOML floats reach Decimal as `Decimal('0.3')` (pydantic converts via str), so no float drift.
- **Security-relevant values unchanged:** `[postgres] host = "localhost"` (= code default; compose
  overrides to `postgres`, only remaining wired setting); retention 7/30/90 days, cleanup 3600 s equal
  code defaults; compose postgres `POSTGRES_DB/USER` hardcoded `nexus` and tied to TOML by a test.
- B15 paper `config_hash`: unchanged code; it normalizes Decimals (`_dec`), and typed values are equal
  from TOML/env/default, so A7 cannot by itself start a new paper run (no double restart). Fresh stack
  is planned anyway.
- Missing file: explicit path missing -> refuse; default missing -> refuse in containers, WARNING locally.
  Image has `WORKDIR /app`, `config/` not baked into the image, compose mounts it `:ro` into all five app
  services (tested) -> a container without the mount fails closed. Good.
- CI integration job sets `POSTGRES_DB=nexus_test` in env; merged-value guard in the integration
  conftest refuses the repo `nexus` value (unit test proves it). Unit tests hermetic via autouse
  `NEXUS_CONFIG_FILE` -> empty file.
- `TOML_ALLOWED` as an explicit list: keep it. Deriving it from the models would make every NEW field
  TOML-allowed by default (fail-open), against spec item 1; the completeness/classification test already
  forces the list, the file and the models to stay in sync.

## Points

1. **MEDIUM — dict settings are deep-merged across sources, not overridden.**
   pydantic-settings deep-merges dict values from all sources. Probe: TOML `transfer_tax_pct =
   {LUNC=1.5, USTC=1.5}` + env `SPREAD_TRANSFER_TAX_PCT='{"FOO":"2"}'` -> effective
   `{LUNC: 1.5, USTC: 1.5, FOO: 2}`. Before A7 the env value replaced the default entirely; now an env
   override can never remove an asset, which contradicts the documented "env replaces the file".
   Fix: make env win per key name, e.g. `NexusTomlSource` drops a table key when its full name is set
   non-empty in env (or, locally, in `.env`) — the same set `env_overridden_names()` computes — so every
   type has replace semantics. Add a unit test (env dict replaces TOML dict; `.env` dict likewise).

2. **MEDIUM — stale setting lines in `.env` behave opposite to what the guide says for the docker stack.**
   Containers disable `.env` loading and compose no longer forwards setting variables, so in the docker
   stack old `.env` setting lines are now **silently ignored** (not shown in `env_overrides` either);
   they only override when running on the host. The guide says "Иначе они молча перекроют файл", which is
   true only for host runs. Any non-default value the user keeps in `.env` (we cannot read it) is silently
   lost on the next `make up-local` — a behaviour change vs the card's "behaviour unchanged with current
   local stack". Related: the 2026-10-23 decision "soak runs 4 venue sets" is not in `config/nexus.toml`
   (it has the code default `all;excl_conditional`) and is not wired anywhere else now.
   Fix: (a) correct the Russian guide: host runs — `.env` lines override; docker — they are ignored, move
   values into `config/nexus.toml` before restart; (b) add a pre-soak gate in `todo.md`: set
   `[paper] venue_sets = "all;excl_conditional;excl_bybit=-bybit;excl_gateio=-gateio"` in the TOML as a
   separate reviewed commit (a config-value change, out of A7's no-default-change scope); (c) optional:
   a host-side helper that prints only the NAMES of SETTING keys present in `.env` (never values), for
   the user to run.

3. **LOW — run-settings hash is environment- and spelling-dependent.** It includes `POSTGRES_HOST` (and
   port/pool), so a host CLI run and the container stack log different hashes for the same strategy;
   Decimals are dumped un-normalized (`"20"` vs `"20.0"` from env), contradicting "source independent".
   Fix: normalize Decimals like paper `_dec`; either exclude deployment plumbing (`POSTGRES_HOST/PORT`,
   pool sizes, `LOG_*`) or document that the hash identifies the deployment, not just the strategy.

4. **LOW — test gaps.** `test_repo_toml_equals_code_defaults` skips `TelegramSettings` (4 SETTING keys
   unverified; construct it with init secrets). `test_allowed_names_never_hit_the_denylist` checks full
   names only, while the guard also checks bare keys — add the bare-key check. The `not_settings` set in
   the classification test duplicates `_DENY_EXACT`; derive it (`_DENY_EXACT` minus `NEXUS_*`).

5. **NIT — provenance coverage.** `settings_loaded` is logged by the scanner and per worker child process
   (`worker_process_init`, so twice per worker at concurrency 2); beat and migrator never log it (the guard
   still runs there). Acceptable; mention in the handoff that the GO report should cite the scanner event.

## Next
backend-lead fixes 1-2 (and 3-4 if cheap), then round 2 here. Max 3 rounds.

---

# Round 2 (HEAD f58ba53; fixes 3e3f34d, 7ce6af8)

- Reviewer: tech-lead, 2026-10-23. Mapping: `docs/handoffs/A7-to-review.md` "Round 2".
- Checks: `make check` green — 900 unit tests passed (round 1: 867), ruff 0, mypy --strict 0. CI green
  on all 7 jobs (per orchestrator). No integration, no DB, `.env` never read.

## Verdict: ACCEPT

## Round 1 points
| # | Status | Evidence |
|---|---|---|
| TL1 dict deep-merge | closed | `NexusTomlSource` drops a table key whose full name is in `present_env_names()` (env, or `.env` outside containers; empty values ignored = `env_ignore_empty`). Tests: env dict / `.env` dict / env list replace TOML; container ignores `.env`; empty env keeps TOML (`test_config_round2.py`). |
| TL2 stale `.env` | closed | Guide rewritten (docker ignores, host overrides, move values into TOML, no merge for lists/dicts); host helper `make check-env-settings`, run by `make up-local`. Soak venue sets moved into the TOML as a separate commit (replaces the todo gate I asked for). |
| TL3 hash | closed | Decimals normalized (`20` = `20.0` = `2E+1`), `POSTGRES_/REDIS_/LOG_` excluded; tests for location independence, spelling, and still tracking strategy values. |
| TL4 tests | closed | Telegram in defaults-equality, bare keys vs denylist, `not_settings` derived from `_DENY_EXACT`. |
| TL5 provenance | closed | beat (`beat_init`) and migrator (`migrations/env.py`) log `settings_loaded`; tested. |

## Security L1 / L2 / L5 re-check
- **L1 closed.** `_refuse` passes table and key through `_printable` (`[A-Za-z0-9_-]{1,64}` and not
  credential-shaped, else `<unprintable key>`); line number kept; tests cover both branches.
- **L2 closed.** Probed the new rule with Python `re` (gitleaks uses RE2; the pattern has no
  constructs that differ): `config/nexus.toml` -> 0 matches on both rules (no false positive, incl. the
  new `venue_sets = "...=-bybit;...=-gateio"` and `transfer_tax_pct = {LUNC=1.5, ...}`). Matches inline
  tables `telegram = {bot_token = ...}`, `x = { a = 1, password = "p" }`, `{ chat_id = ... }`, quoted and
  dotted keys; commented lines skipped (`[^#\n]` cannot cross `#`); `HTTPS://u:p@h` caught. Side effect:
  any value containing a keyword followed by `=` matches — fail-safe direction, acceptable.
- **L5 closed.** `isolated_env` clears `KEY_POLICY_*` and `NEXUS_WORKER_ROLE`.

## `make check-env-settings` (static review + fake-file probes in the scratchpad)
- Code: `dotenv_values(".env")` -> keep keys with non-empty values -> intersect with `TOML_ALLOWED` ->
  print sorted names. Values are never stored beyond the parse dict, never printed, never written to
  disk or logs; a junk key cannot be printed unless it equals an allowed SETTING name. Secret names
  (e.g. `TELEGRAM_BOT_TOKEN`) are not in `TOML_ALLOWED`, so they are never listed.
- Probes (fake `.env` in a scratch dir, every value tagged `LEAK`): `export X=...`, lower-case names,
  line without `=`, `NAME` alone, `=value`, quoted multi-line value, `'a\nVALUE=b'`, JSON dict value,
  whitespace-only value, `KEY  =  v`, malformed `bad = = "...` -> output contained **0** value
  fragments; python-dotenv parse warnings print only "could not parse statement starting at line N".
  Exit 0 in all these cases.
- Non-UTF-8 `.env`: `UnicodeDecodeError` traceback, exit 1 (aborts `make up-local`). Message holds
  one byte value and position only, no line content — no leak. See point R2-1.

## Soak venue sets (7ce6af8)
Correct: `venue_sets = "all;excl_conditional;excl_bybit=-bybit;excl_gateio=-gateio"` matches the
STATE.md decision (4 sets). `test_soak_venue_sets_resolve_with_default_venues` resolves them strictly
with default `EXCHANGES_ENABLED` / `CONDITIONAL_VENUES`. A TOML value counts as "explicitly set"
(`model_fields_set`), so `strict=True` applies: narrowing `EXCHANGES_ENABLED` to drop bybit/gateio fails
closed with a named error — intended. The defaults-equality test allows exactly this one deviation.
B15 paper `config_hash` changes for the new portfolios — fine, the soak starts on a fresh stack.

## Remaining points (non-blocking, may be ticketed)
1. **R2-1 LOW** — helper: catch `UnicodeDecodeError`/`OSError` and print a one-line message
   (".env is not readable UTF-8; check skipped/failed") instead of a traceback.
2. **R2-2 NIT** — helper always exits 0 when names are found; the warning can scroll away in the
   `docker compose build` output. Consider printing it again after `up -d`, or a non-zero exit with an
   override flag. Design choice, user-facing only.
3. **R2-3 NIT** — gitleaks key rule does not match hyphenated `api-key`/`private-key`; the runtime guard
   covers it (defence in depth only).
