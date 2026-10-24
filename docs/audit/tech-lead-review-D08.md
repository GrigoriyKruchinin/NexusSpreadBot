# Tech-lead review — D-08 follow-up (watchdog "paper set stale"), commit fba9dd4

Round: 1 of 3. Spec: `docs/audit/delta-02-S0.md` row D-08; design: `docs/tasks/m3/S0-pre-soak-gates.md` § "D-08 follow-up".

## Verdict: RETURN (2 must-fix points, small)

## Checks
| Check | Result | Ratchet |
|---|---|---|
| `make check` (ruff format/check, mypy --strict, unit) | green | — |
| Unit tests | 1021 passed (+12) | >= 1009 OK |
| Branch coverage | 91.49 % | >= 91.4 % OK |
| ruff / mypy | 0 / 0 (163 files) | OK |

## What is correct
- **SQL vs schema.** `paper_portfolios(portfolio_id, started_at)` (migration b15a7c3e91d2) — `max(started_at) GROUP BY portfolio_id`
  is exactly "current run start per name" and is served by `ix_paper_portfolios_portfolio_started_at`.
  `paper_cap_stats` PK `(portfolio_id, hour)` serves `max(hour) GROUP BY portfolio_id`; the table is tiny
  (sets x hours), so a full index scan every watchdog tick is fine. Columns/types (tz-aware) match the models.
  Read-only, two aggregates in one session, no migration. Faked-session test only — acceptable, but add the
  query to the next integration pass on `nexus_test` (not now).
- **Freshness math.** Writer (`scanner/capstats.py`) buckets by hour start and flushes every 5 min, so a
  healthy set shows <= ~65 min; `stale_h=3` (ge=2) leaves margin. `max(started, newest_hour)` handles a new
  run / no rows. A restart after a long outage: stale -> 15 min grace -> first flush (5 min) clears it. OK.
- **Per-set state/dedup.** Key `paper_set:<name>`, reuses `_apply` (one alert, one recovery, severity
  escalation), `sorted()` deterministic, per-set exception isolation. OK.
- **Scanner suppression** does not hide incidents forever: paper checks are skipped only while the scanner
  check is not OK, which itself alerts; paper state is preserved and evaluated on scanner recovery.
- **(a) never-registered set invisible:** a set that resumes-fails still has its registry row from earlier
  runs, so the realistic D-08 case (resume failure, sweep/flush failures, all-paper-off) is covered. Only a
  brand-new set failing on its very first start is invisible; covered by the digest per-set line. Accept as
  documented limitation.
- **(c) text safety:** fixed template; set name passes `^[a-z0-9_]{1,32}$` at config time and `esc()` at
  render; minutes is an int. No secrets. Settings in `TOML_ALLOWED` with `WATCHDOG_` prefix (A7). OK.

## Must fix
1. **`paper_sets` check_error never recovers (bug).** `_run_paper_sets` calls `_probe_failed("paper_sets")`
   on a read failure, but a later successful read never applies `Finding("paper_sets")` (ok). Consequences:
   (i) after a >15 min failure the alert fires and no "resolved" is ever sent, the state stays `firing`
   forever, and every later failure is swallowed as `firing` (dedup) — a silent watchdog; (ii) a short
   failure leaves `since_ms` set, so a failure weeks later alerts with no grace. Fix: after a successful
   `source.read()`, `await self._apply(Finding("paper_sets"), now)` (inside try). Test: fail past grace ->
   alert; succeed -> exactly one `WatchdogRecovered("paper_sets", ...)`; fail again -> new alert after grace.
2. **Retire must not say "проблема устранена" (author risk b).** When a firing set crosses `retire_h`, the
   OK finding produces `WatchdogRecovered` -> "✅ Paper-набор X: проблема устранена, длилась ~7 д". For the GO
   data this is false: the set never came back, a week of data is missing. Recommended: return a distinct
   outcome from the domain (e.g. reason `paper_set_retired` / flag) and in the service, if the state was
   firing, send one distinct message ("Paper-набор X: больше не отслеживается — данных нет более 168 ч,
   считаю удалённым из конфигурации; проверьте, нужен ли он") and clear state; if not firing, clear silently.
   Staying fully silent is not acceptable — it closes a live incident without a trace. Test both branches.

## Should fix (may land in the same commit, not blocking)
3. Cross-validate `paper_set_retire_h > paper_set_stale_h` (model validator); today `stale_h=200` silently
   disables the check.
4. Removing/renaming a set in `PAPER_VENUE_SETS` produces a stale alert after 3 h that keeps firing until
   retire. Expected for the soak (config frozen), but write one line in the soak guide / design note.
5. Minor: a set in grace when the scanner goes stale keeps its old `since_ms`; on scanner recovery it can
   alert without grace. Rare (paper goes stale after the scanner check does); optional: reset non-firing
   paper grace states while suppressed, or accept and note.
6. Docstring/design note: the "paper_sets" check-error title and the retire message once item 2 lands.

## Notes
- Sets with `venues=None` (legacy/unrestricted) never get cap-stats rows (`service.py` filters them); the
  container always builds frozensets, so no production impact. Pre-B15 `legacy` run on an old DB is older
  than 168 h -> retired; the soak uses a fresh DB.
- Next round: re-review only items 1-2 (+ whichever of 3-6 are taken).

## Round 2 (2026-10-24)

Fix commit 4d1a990. Verdict: **ACCEPT**.

### Checks
`make check` green: ruff 0, mypy --strict 0 (163 files), 1028 unit tests passed (ratchet >= 1009 OK),
branch coverage 91.52 % (ratchet >= 91.4 % OK).

### Items
1. **FIXED** — `services/watchdog.py:107-111`: every successful `source.read()` applies `Finding("paper_sets")`,
   so a firing check error recovers once and a short failure's `since_ms` is cleared. Its own failure is isolated
   (`actions["paper_sets"]="error"`, set checks still run). Tests: `test_paper_source_error_recovers_once_and_can_alert_again`,
   `test_short_paper_source_failure_leaves_no_stale_grace`.
2. **FIXED** — domain returns `PAPER_SET_RETIRED` (`domain/watchdog.py:136-137`); `_retire` (`services/watchdog.py:131-147`)
   sends one `WatchdogRetired` only if firing, clears state after dispatch, else clears silently. Next tick: state empty
   -> "ok", no repeat. Text `formatting.py:285-291`: fixed template, `esc(watchdog_title)` + int hours, no "устранена".
   Event exempt from max-age drop (`alerts.py:115`) — correct, a late "no longer tracked" is not misleading; not in the
   silent set, so it notifies with sound — intended. Tests for both branches present.
3. **FIXED** — `config/groups.py:496-501` model validator `retire_h > stale_h`, test present.
4. **FIXED** — design note in `docs/tasks/m3/S0-pre-soak-gates.md` (rename/remove -> alert at 3 h, retire at 168 h).
5. **FIXED** — `_grace_gap` (`services/watchdog.py:172-179`, used at 190-193).
6. **FIXED** — docstrings + design note updated.

### Grace-restart analysis (new logic)
- Normal cadence (Celery beat, 300 s): grace starts t0, alert at t0+15 min; gap limit 25 min is never hit. OK.
- Postponement forever needs every consecutive evaluation of the check to be > 25 min apart. Causes: watchdog
  worker stalled > 25 min per tick (then nothing alerts anyway), or the scanner check flapping so paper checks run
  < once per 25 min — but then the scanner check itself is non-OK most of the time and alerts. Dispatch failing
  repeatedly delays by at most one extra grace per restart, only while the broker is down (documented). No new bug.
- Restart only for non-firing states, only paper checks; scanner/backup grace untouched. OK.

### Notes (non-blocking)
- `_retire` dispatch-then-save: a save failure after dispatch can repeat the retire message once (at-least-once,
  same as `_apply`). Accept.
- Integration test of the paper-set SQL on `nexus_test` still pending (round 1 note) — next integration pass.
