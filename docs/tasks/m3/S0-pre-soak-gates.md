# S0 — Pre-soak gates (D-01, D-02, R-02, liveness)

- id: S0
- stage: M3 (must be done before the fresh-stack soak)
- owner: devops (S0a), backend-lead (S0b)
- reviewers: tech-lead (diff), security (backup copy path, Telegram content)
- complexity: medium
- depends_on: A7 (done), B15 part 1 (done)
- status: done (S0a 3bb5746 + r2 2c528c6, 8b1e81d; S0b up to 21897bf + r2 cb1c1af; D-08 fba9dd4; TL r2 ACCEPT 343df63, security r2 ACCEPT 1fb8d60). Open: D-01 live restart check on the first Docker/WSL restart of the soak (security S-8); D-08 tech-lead review in progress (`docs/audit/tech-lead-review-D08.md`)

## Context
Delta audit `docs/audit/delta-track0-B14.md` D-01, D-02, R-02; STATE.md. User decisions 2026-10-23:
soak runs on this PC (WSL, Windows sleep disabled by the user); off-machine dump copy to `C:\nexus-backups`
(`/mnt/c/nexus-backups`, outside OneDrive, no encryption needed); soak on a fresh stack + clean DB.

## S0a — devops (files: docker-compose.local.yml, scripts/, Makefile, docs/guides/backups.md)
1. D-01: scanner restart policy: key-policy refusal (exit 3) must NOT restart-loop; any other failure
   restarts indefinitely (`unless-stopped` or equivalent, with backoff). Document the choice.
2. D-02 copy: after a successful dump + `.counts` sidecar, copy both to `BACKUP_COPY_DIR`
   (default `/mnt/c/nexus-backups`; skip with a WARN if the dir is not mounted, never fail the dump);
   prune copies with the same retention as local. Verify copy size/checksum.
3. Status contract for liveness: `backup.sh` writes `$BACKUP_DIR/last_backup.json` atomically:
   `{"finished_at": ISO-UTC, "ok": bool, "dump": "<file name>", "copied": bool}` (no secrets, no paths with
   user data beyond file names). Mount a world-readable status dir `~/nexus-backup-status` (fixed path; `backup.sh` mirrors `last_backup.json` there) read-only into the maintenance worker at `/backups`. Accepted deviation: `$BACKUP_DIR` itself is 0700 and is NOT mounted (the container uid cannot enter it and must not see dumps).
4. Guide (Russian) `docs/guides/backups.md`: copy location, how to disable Windows sleep for the soak,
   how to check the status file.

## S0b — backend-lead (files: src/, tests/)
1. R-02: one failing evaluation/venue task must not abort the whole sweep (no bare `asyncio.gather`
   propagation; `CancelledError` still propagates). Tests.
2. Liveness watchdog (Celery beat task in maintenance worker, period from config TOML):
   - scanner alive: last sweep timestamp (existing heartbeat/metric/DB row; pick the cheapest reliable one)
     older than N minutes -> Telegram alert; recovery message once.
   - backup: `/backups/last_backup.json` missing, `ok=false`, `copied=false`, or older than 26 h -> alert.
   - de-duplicated (one alert per incident), no secrets in text, Russian alert text.
3. Gap accounting for the GO report: persist per-hour "scanner was sweeping" coverage (cheapest: reuse
   `paper_cap_stats.sweeps` per set, quant N12) and expose total downtime per set in the digest.
   The digest downtime is informational only; the B15 part 2 GO report recomputes gaps from raw
   `paper_cap_stats.sweeps` (tech-lead S0 round 2, R2-3).
4. Settings for thresholds go to `config/nexus.toml` + `TOML_ALLOWED` (A7 rules).

## Acceptance
`make check` not worse (>= 900 tests, branch >= 89 %), CI green (7 jobs), no secrets, ADR 0001 unchanged,
never reads `.env`, no live DB access. Card + todo updated.

## D-08 follow-up (watchdog: paper set stale)
New check `paper_set:<name>` per venue set (state key per set, one alert / one recovery, same severity and
`check_error` handling). Sets come from the run registry (`paper_portfolios`, latest run per name): the
maintenance worker has no `PAPER_VENUE_SETS`, and a set that never registered cannot be seen (limitation).
Freshness = newest `paper_cap_stats` hour, age from the hour start (a healthy set shows up to ~65 min), a
set with no row is judged from its run start. Settings `watchdog.paper_set_stale_h = 3` and
`paper_set_retire_h = 168` (silent longer = treated as removed from config, no alert), both in
`TOML_ALLOWED`. A 15 min grace absorbs the flush lag after a scanner restart. Paper checks are skipped
while the scanner check is stale / no-data / failing (no double alerts; they resume after recovery).
Alert text: fixed Russian template + set name only. Read-only queries, no migration.

D-08 tech-lead round 1 fixes: (1) the `paper_sets` source-read `check_error` is now closed by an OK finding
after every successful read (one recovery, no stale grace). (2) A set that crosses `paper_set_retire_h`
while firing gets one distinct message (event `WatchdogRetired`, "Paper-набор X больше не отслеживается:
данных нет более N ч, считаю удалённым из конфигурации"), never "проблема устранена"; the state is then
cleared. A non-firing set is forgotten silently. (3) Validator: `paper_set_retire_h > paper_set_stale_h`.
(4) Grace edge: a paper-set / `paper_sets` grace window older than grace + 2 watchdog runs (the check was
paused, e.g. scanner stale) restarts instead of alerting instantly on resume; side effect: if dispatch keeps
failing for > 2 runs after grace, the alert is delayed by up to one more grace (15 min). Removing or renaming
a set in `PAPER_VENUE_SETS` alerts after 3 h and keeps firing until retire (168 h), then sends the retire message.
