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
