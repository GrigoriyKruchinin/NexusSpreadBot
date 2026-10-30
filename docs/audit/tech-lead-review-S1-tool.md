# Tech-lead review — stage S1-tool (round 1)

- Card: `docs/tasks/tool/T14-stage-gates.md` (scope item 1). Branch `chore/agent-pipeline-adoption`.
- Range: `f603178~1..69c6a7e` (T1a/T1b 0cd7f6a+767510a, T2 f0d9b71, T3 aa2cf98, T4 43c21a8, T5 3be4978/2364740/c9c253b/c445540,
  network times 562da8b, T6 4e92c79, T7 3b02eea, T8 869d252/8e06f6e, T9 b5f6ac3, T10 08de8f9, T11 69c6a7e).
- Inputs: ADR 0010, `todo.md` S1-tool, cards `docs/tasks/tool/`, `docs/audit/baseline-S1-tool.md`.
- Date: 2026-10-25. Reviewer: tech-lead (no code edited).

## Verdict: **RETURN** (1 blocking, 5 should-fix, 10 nits)

Overall the stage is in good shape: the paper/GO/HT removal is clean (`grep -i paper|go-report|hedge|perp|portfolio|soak`
over `src/ config/ .env.example` is empty except the Binance flag name `enablePortfolioMarginTrading`), the squash is
covered by a one-head + `alembic check` no-drift integration test, the alert state machine is mostly well designed
(claim-before-send, atomic hourly budget with `ON CONFLICT ... WHERE sent < limit`, refund on failure, stale-SENDING
reaper, alerts-only columns that the scanner's `save()` cannot clobber), the rate limiter is correct for a single
prefork child (`--concurrency 1` is set in compose), and `nexus check` / key-policy share one decision function.

## Checks (run by reviewer)
| Check | Result |
|---|---|
| `make check` | ruff format 160 files OK, ruff 0, mypy --strict 0 (162 files), **1059 passed**, 19 deselected |
| `make test-cov` | total **92 %** (5464 stmts / 1168 branches), matches baseline 91.90 %; floor 89 % |
| CI (`gh run list`) | green on 69c6a7e; only failure 869d252 (fixed by 8e06f6e) |
| Leftovers grep (ADR 0010 confirmation) | clean |
| vulture (60 %) | only `pinned_text`, `fmt_time` really unused (N2) |

Ratchet vs baseline: not worse (baseline file is current; CLAUDE.md line still says 1028 / 91.5 %, update is user-owned, see T12).

## Blocking

1. **CLOSED fallback bypasses the anti-spam cap** — `src/nexus/services/alerts.py:227`. When an episode has no stored
   message, `send_event(EpisodeClosed)` falls through to a standalone (Russian) system message, outside the hourly budget.
   The scanner marks an episode "alerted" as soon as the task is *queued* (`scanner/service.py` `_alert_episode`), so every
   episode whose NEW was **suppressed by `max_per_hour`** produces an uncapped "episode closed" message for an alert the
   user never saw. In a burst (exactly when the cap matters) this doubles the spam the cap is meant to stop and defeats
   T5 AC "cap overflow produces one summary". Test `test_close_without_a_message_falls_back_to_the_event_message` locks
   in this behaviour. Fix: with a `messages` repository, a close without a stored message is dropped (log
   `alert_close_no_message`, outcome `SUPPRESSED`/`MISSING`); keep the standalone fallback only for `MessageGoneError`
   (message deleted) or drop it too and log. Update the test; add one: NEW suppressed -> close -> 0 extra sends.

## Should-fix

2. **UPDATE before NEW is stored -> duplicate/orphan messages** — `alerts.py:127-137`. If NEW is retried (local limiter
   wait > 20 s, 429 `retry_after`, transient error) or suppressed by the cap, a later UPDATE finds no stored message and
   sends a fresh message (UPDATE template, consumes budget); a late NEW retry then sends another one and
   `_remember` overwrites the id, so the first message is never edited/closed. Fix: (a) UPDATE with no stored message
   whose episode NEW was suppressed -> suppress too (count in the summary); (b) NEW (`realert == 0`) when a message is
   already stored -> edit instead of send. Tests for both orders.
3. **System events are Russian-only while the product default is `en`** — `formatting.py:377` `SystemEventFormatter`
   (scanner started/stopped, exchange down/recovered, quarantine, watchdog, episode-closed fallback, `fmt_duration`) and
   the digest. A third party's first message ("scanner started") is Russian. T4 scope 1 says all user-facing strings go
   through one catalog. Either route them through `alert_catalog` with `[alert] language`, or record a decision that
   S1-tool ships ru-only system messages and say so in README/quickstart.
4. **Docs claim schema changes cannot be upgraded in place** — `README.md:133`, `docs/guides/quickstart.md:225-226`.
   The migrator runs `alembic upgrade head` on every `make up` (b7d2c4e6a1f3 itself is an in-place upgrade). Only DBs
   created before the T2 squash are incompatible. Reword: "updates migrate automatically; a database from before
   2026-10-25 (S1-tool) must be reset once". Otherwise users will run `make reset-data` needlessly and lose data.
5. **Fixed host port 5432** — `docker-compose.yml:68`. A local PostgreSQL or the old `nexus-local` stack on the same
   machine makes `make up` fail with "port is already allocated", not covered in README troubleshooting. Use
   `"127.0.0.1:${POSTGRES_HOST_PORT:-5432}:5432"` (+ `.env.example` advanced section + env-example test) or at least a
   troubleshooting row. (Note: project name changed `nexus-local` -> `nexus`; the owner's old containers/volumes are
   untouched and must be stopped/removed by the user — put it in the S1-tool summary.)
6. **Agent guard rails are stale after the compose rename** (user-owned files; for the orchestrator to raise, coordinate
   with security): `.claude/settings.json` deny/ask rules target `docker-compose.local.yml` and `make up-local/down-local`;
   the new `make up`, `make down`, `make doctor`, `make reset-data` (runs `docker compose down --volumes` via make, so the
   Bash-prefix deny rule does not fire; the typed-DELETE prompt can be piped) and `scripts/start.sh` are not in `ask`;
   `docker compose --profile tools config` is not denied. CLAUDE.md "Commands" still lists `make up-local / down-local`
   (T12 proposal should cover it).

## Nits

7. `checks.py:31` placeholder regex matches substrings (`your`, `fake`, `xxxx`, ...) anywhere in a real random token
   (~1e-4 chance) -> fatal exit 3 with a misleading text. Test placeholders only when the format check fails, or match
   whole known placeholders.
8. Dead code: `alert_catalog.pinned_text` (T4 scope 6 pin text is neither wired nor documented in README),
   `formatting.fmt_time` unused.
9. `telegram.py:83` `str(None)` -> message id `"None"` if Telegram omits `message_id`; a later `edit` does
   `int("None")` (ValueError, not a NotificationError). Return/keep `None` and treat as "no message".
10. `formatting.truncate` can cut inside an HTML tag/entity -> Telegram 400 (rejected, not retried). Pre-existing;
    alerts are far below 4096, low risk.
11. `domain/episodes.py:60-63`: the `survived_latency` docstring sits after `unverified_since_ms` (misattached).
12. Key check has no retry: a transient network error at startup -> `request_failed` -> default mode runs that venue
    public for the whole run (until restart); strict mode exits 3 and the scanner parks until a manual restart.
    Document in troubleshooting or retry once with backoff.
13. `startup_check/runner.py` 82 % (DB probe `_current_revision` only covered by integration/manual).
14. README example alert (`README.md:14`) does not match the golden template (no Buy/Sell lines, `0.85% net` vs
    `+0.85 % net`); regenerate from a golden test string.
15. `README.md:75` says KuCoin cannot report permissions; in code KuCoin scopes ARE checked (anything but `General` is
    rejected), only the IP whitelist is unverifiable; Gate.io scopes are unverifiable (accepted with a warning in default
    mode — security to confirm this is acceptable under CLAUDE.md rule 2).
16. Owner setup: `config/nexus.toml` ships `language = "en"`; the owner wants `ru` (STATE). Since the config is baked
    into the image, the owner's deploy needs a toml edit + `make up` — add to the deploy notes.

## Next
Backend-lead fixes 1-2 (+ tests), 3 (code or decision), 4/5/14/15 docs+compose (scribe/devops), 7-11 optional.
Orchestrator raises 6 with the user. Round 2 review on the fix commits only.

---

# Round 2 (2026-10-30)

- Range: `13dc219..0c6a255` (a98e936, 57e34a3, 5804947, 2b132d2, b76f3f4, e5f1e9b, 8609cce, 029d2fd, e8b691f, bc3b8ae, 0c6a255).
- Reviewer: tech-lead (no code edited).

## Verdict: **RETURN** (1 blocking, 0 should-fix, 3 nits). All 16 round-1 points are closed.

## Checks (run by reviewer)
| Check | Result |
|---|---|
| `make check` | ruff format + ruff 0, mypy --strict 0 (162 files), **1084 passed**, 19 deselected |
| `make test-cov` | **92.08 %** (5506 stmts / 1182 branches); floor 89 % |
| Ratchet | not worse than round 1 (1059 / 92 %) or CLAUDE.md (1028 / 91.5 %) |
| Hermeticity probe | with an untracked `config/local.toml` (`[alert] language = "ru"`): **1 failed**, 1083 passed (see R2-1); file removed afterwards |

## Round-1 points
| # | Status | Evidence |
|---|---|---|
| 1 | closed | `alerts.py` `send_event`: with a messages repo a close goes only through `_close_message`; no stored message -> `SUPPRESSED`, gone/no evaluation -> `MISSING`, never a standalone message. Tests `test_close_without_a_message_is_silent`, `test_suppressed_new_then_close_adds_no_extra_send`, `test_close_of_a_deleted_message_sends_no_standalone_message` |
| 2 | closed | `_deliver`: UPDATE without stored message dropped (`alert_update_no_message`); NEW with stored message edits (no budget used). Tests for both orders |
| 3 | closed | `SystemEventFormatter(language)` / `DigestFormatter(language)` from `alert_catalog`, wired in `container.py`; en/ru key parity test |
| 4 | closed | README "Update" and quickstart reworded (migrations in place; only pre-2026-10-25 DBs reset) |
| 5 | closed | Postgres port not published by default; opt-in `docker-compose.postgres-port.yml` (`127.0.0.1:${POSTGRES_HOST_PORT:-5432}`); troubleshooting row incl. old `nexus-local` stack |
| 6 | closed | `.claude/settings.json` updated (b76f3f4, user OK): `make up/down/doctor`, `scripts/start.sh` in ask; `make reset-data`, `docker compose -f/--profile/...` denied. CLAUDE.md "Commands" `up-local` line remains for T12 (user-owned) |
| 7 | closed | `_PLACEHOLDER_RE.fullmatch`; probed: real-format token not matched, `your_bot_token` / `1234:AAFakeFake` matched |
| 8 | closed | `nexus pin-text` + `make pin-text`, documented; `fmt_time` removed |
| 9 | closed | `DeliveryReceipt.message_id: str | None`; `_remember` / summary skip `None` |
| 10 | closed | `truncate` drops a cut tag/entity and closes open tags (64-char reserve) |
| 11 | closed | docstring moved |
| 12 | closed | `_read_with_retry`: 3 tries, 1 s / 2 s backoff, only `ExchangeUnavailableError`/`ExchangeRateLimitError`/`TimeoutError`; auth not retried (tests) |
| 13 | closed | `startup_check/test_runner.py` covers the DB probe with a fake engine |
| 14 | closed | README example now matches the template (Buy/Sell lines, `+0.80 % net`) |
| 15 | closed | README residual-risk text matches the code (KuCoin: IP only; Gate.io: permissions) |
| 16 | closed, but see R2-1 | `config/local.toml` overlay (same guard, per-key merge, gitignored, `COPY config/nexus.toml config/local.tom[l] ./config/`) |

## Blocking

R2-1. **The recommended owner overlay breaks `make check` on the owner's machine** —
`tests/unit/config/test_config_file.py::test_repo_toml_equals_code_defaults` points `NEXUS_CONFIG_FILE`
at the real `config/nexus.toml`, and the loader now also merges `config/local.toml` next to it. Once the owner follows
README/quickstart (`[alert] language = "ru"`), the test fails (reproduced: 1 failed). Agents run `make check` in the same
working copy, so every later commit gate goes red; same exposure for `test_merged_db_name_is_what_the_integration_guard_checks`
if the overlay ever sets `[postgres]`. Fix: in tests that use `REPO_TOML` through the loader, copy it into `tmp_path` and
point `NEXUS_CONFIG_FILE` there (or add a loader switch that tests use to disable the overlay). Add a regression test:
a `local.toml` beside the repo file does not change these tests' result.

## Nits (no action required for ACCEPT)

N-1. Dropped UPDATE while its NEW is still being retried: the scanner has already advanced the re-alert baseline, so that
growth step is not re-announced until the next threshold. Acceptable trade-off; worth one line in the `_deliver` docstring.
N-2. The Dockerfile optional glob is verified only by a text test. Tester (T14 scope 2) must run a real `docker build`
with and without `config/local.toml`.
N-3. `make pin-text` starts a container but is not in the `ask` list; harmless (prints text), noted for completeness.

## Next
Backend-lead fixes R2-1 (test-only change). Round 3 (last) checks only R2-1 plus `make check`.
