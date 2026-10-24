# Handoff: S0a (devops) -> tech-lead / security review

Done (files: docker-compose.local.yml, scripts/backup.sh, scripts/_backup_common.sh, Makefile, docs/guides/backups.md,
tests/unit/scripts/test_backup_scripts.py, tests/unit/test_compose.py):
- D-01: scanner `restart: on-failure` (unlimited, Docker backoff) + `sh` wrapper mapping exit 3 -> exit 0 (not restarted),
  other codes propagate, SIGTERM/INT forwarded. Clean stop is not restarted either. Wrapper verified with fake binaries.
- D-02: `copy_offsite` (dump + .counts to BACKUP_COPY_DIR, default /mnt/c/nexus-backups, created on first run only if the
  parent exists and /mnt/<x> is a mountpoint; sha256 verified; temp+rename; same prune; WARN and continue otherwise).
- Status: `last_backup.json` {finished_at, ok, dump, copied}, atomic, on success and failure.
- DEVIATION from card item 3: BACKUP_DIR is 0700 and the container user is uid 10001, so mounting it would be unreadable
  (and would expose dumps). backup.sh writes the status to BACKUP_DIR (contract) AND mirrors it (0644) to
  BACKUP_STATUS_DIR (default ~/nexus-backup-status), which is mounted ro at /backups in worker-maintenance.
  `make up-local` creates that dir (else Docker would create it root-owned).
- Guide updated (Russian). Tests use sandbox copy/status dirs; real /mnt/c was never touched.

For S0b: read `/backups/last_backup.json`; fields as above; `ok=false`/`copied=false`/older than 26 h -> alert.
Not run (by instruction): make backup, restore-drill, docker compose up. First real run of the copy is untested on /mnt/c.
Pitfall: the full `make check` was red only on backend-lead's in-progress src/ files at the time of writing.

## Round 2 (devops, tech-lead D-01/6/7/8, security S-2/S-3/S-4)
- D-01: scanner `restart: unless-stopped`; inline wrapper in `docker-compose.local.yml` traps TERM/INT before
  the fork, forwards to the scanner, and on exit 3 PARKS (sleep, exits 0 on TERM/INT). Executable tests run the
  real wrapper (extracted from the YAML) against a fake `nexus` for exit 0/1/3 and SIGTERM during run and park
  (`tests/unit/test_compose.py`).
- TL6: `make backup-archive` (`BACKUP_ARCHIVE=1 scripts/backup.sh`, optional `SOURCE_DB=`) writes
  `~/nexus-backups/archive/nexus-archive-<stamp>.dump`; never pruned (name + subdir), copied off-machine, no
  status/heartbeat. Documented in the guide; use it for the fresh-stack step.
- TL8: copy order is `.counts` first then dump; any failure removes the copied sidecar.
- S-3: copy temp files are `mktemp` names in the copy dir (no fixed/symlinkable name).
- S-4: status publish refused if the status dir == BACKUP_DIR, inside it, or holds `nexus-*.dump`. Compose and
  Makefile now use the fixed `$HOME/nexus-backup-status` (no BACKUP_STATUS_DIR, no .env dependency); the script
  override remains for tests only.
- S-2: guide has the optional `icacls` step. TL7: card S0 item 3 records the mount deviation.
- TL "optional 6/8" (gather_isolated nit) belongs to backend-lead.
