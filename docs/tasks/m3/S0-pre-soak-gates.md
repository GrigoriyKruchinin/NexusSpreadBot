# S0 — Pre-soak gates (D-01, D-02, R-02, liveness)

- id: S0
- stage: M3 (must be done before the fresh-stack soak)
- owner: devops (S0a), backend-lead (S0b)
- reviewers: tech-lead (diff), security (backup copy path, Telegram content)
- complexity: medium
- depends_on: A7 (done), B15 part 1 (done)
- status: todo

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
   user data beyond file names). Mount `$BACKUP_DIR` read-only into the maintenance worker at `/backups`.
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
4. Settings for thresholds go to `config/nexus.toml` + `TOML_ALLOWED` (A7 rules).

## Acceptance
`make check` not worse (>= 900 tests, branch >= 89 %), CI green (7 jobs), no secrets, ADR 0001 unchanged,
never reads `.env`, no live DB access. Card + todo updated.
