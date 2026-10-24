# Tech-lead review D-01b, round 1 (2026-10-24)

Scope: commits `7c06a23` (bake `config/nexus.toml`, drop bind mount), `3ed5b61` (`scripts/host_watchdog.sh` + tests),
`1f78bd2` (guide, handoff, STATE, todo). Handoff `docs/handoffs/D01b-auto-recovery.md`.

## Verdict: RETURN (2 must-fix, small; rest should-fix)

Checks run: `make check` green (1122 unit passed, lint/mypy clean, ratchet not worse); watchdog + compose tests 35 passed;
`bash -n` ok. No docker state changes, no integration tests, watchdog not run against the live stack.

## What is right
- Root cause addressed: the file bind mount `./config/nexus.toml` is gone from `x-image` and `worker-maintenance`; the file is
  `COPY`ed in the runtime stage; `.dockerignore` does not exclude `config/`; file mode 644 (readable by uid 10001).
  The loader path is relative (`config/nexus.toml`, WORKDIR `/app`), so nothing else changes. Test asserts no app-service
  bind mount except worker-maintenance and the COPY after `AS runtime`.
- Scanner exit-3 park: a parked scanner is `running` + `unhealthy`; the watchdog only alerts on unhealthy and never
  restarts a running container, so no key-introspection loop. OK.
- Watchdog logic: 2-strike alert, hourly repeat, recovery message, failed send retried next run (alerted stays 0),
  pause file before lock, `flock -n` against overlapping cron runs, only `start` (no up/recreate/build/down/exec/config/
  inspect), `.env` parsed with grep (not sourced), token/heartbeat URL via curl stdin config, strict regexes block config
  injection. Missing container reported, not created. Correct.
- Tests are hermetic (fake docker/curl, tmp HOME), assert argv never carries the token and no forbidden docker verbs.

## Must fix
1. **Remaining bind mount may come up silently EMPTY instead of failing.** `${HOME}/nexus-backup-status:/backups:ro` uses
   short syntax; for a missing *directory* source Docker creates an empty host dir and starts the container. After a WSL
   restart worker-maintenance can then be `running healthy` with an empty `/backups` (in-stack backup liveness watchdog
   blind or false-alarming) and the host watchdog will never fix it (it does not restart running containers). The handoff/
   guide assume "fails -> watchdog starts it". Fix: long syntax `type: bind, source: ${HOME}/nexus-backup-status,
   target: /backups, read_only: true, bind: {create_host_path: false}` so a missing source fails the start (then the
   watchdog `start` path applies); update the compose test (bind detection currently only parses short strings) and the
   guide D-01 step 3 (add a check that the backup status is visible, e.g. the in-stack backup check is green).
2. **`docker compose start` under `timeout 60` is too short.** `start` honours `depends_on` conditions: migrator must
   complete, worker-alerts / worker-maintenance must be healthy (interval 30 s, start_period 30 s) before scanner / beat.
   A full-stack recovery (the D-01 case: 4 services) can take 60-90 s; `timeout` then kills the CLI mid-way, later services
   stay down for another 5 min, and the post-check counts a bad run (spurious ALERT likely at threshold 2). Use a separate,
   longer timeout for `start` (e.g. 240 s; flock already protects overlap) and add a test that the start call is made with
   it (or at least that a non-zero `start` exit still re-evaluates and does not send "restarted").

## Should fix (this round, cheap)
3. Deploy steps: the build bakes the *working tree* `config/nexus.toml`. Add `git status --short config/ src/` (must be empty)
   before `make up-local`, and verify after deploy that `paper_resumed` shows the same `run_id`s as before (not only that the
   event exists).
4. Recovery after an earlier alert sends two messages ("restarted ... now healthy" and "healthy again"); send one.
5. Tests missing: recovery that does not succeed (start, still exited -> no "restarted" message, fails=1); concurrent run
   skipped by the lock (hold the lock file with `flock` in the test and assert exit 0, no docker calls).
6. Guide: if the scanner is parked (exit 3) and the user stops it to fix keys, the watchdog restarts it every 5 min (one key
   introspection per start). Say explicitly: pause the watchdog while fixing keys.

## Deploy safety (handoff commands)
Safe for the running soak once points 1-3 are in, with user OK (data gap ~1-2 min, already disclosed):
- `make up-local` = `up -d --build`: removing the volume entries changes the config of every app service, so all 5 app
  services are recreated; postgres/redis definitions are unchanged and are not recreated (volumes untouched).
- Migrator rerun: `alembic upgrade head` at head = no-op. Harmless.
- Paper runs resume with the same run: `settings_hash()` is computed over effective setting values (not path/mtime), file
  content unchanged. Code delta for the scanner since its running image (~`699bb75`): only reports and maintenance
  retention (`db.py` adds an opt-in `read_only` flag, default off) -> scanner behaviour unchanged.
- Key policy is re-evaluated once on scanner recreate (same as the 15:11Z start); acceptable.

## Rebuild-on-config-change
Documented (Dockerfile, compose header, README). Acceptable for the soak: config changes during a soak change the run hash
anyway and require a deliberate restart. Also note it in `docs/guides/` where settings edits are described, if any.

## Residual risks (no action now)
- Exit 127 mechanism itself not confirmed; the design removes the dependency and adds a generic recovery path.
- After `wsl --shutdown` the Task Scheduler keep-alive is gone until next logon; Ubuntu stays up via Docker Desktop's
  integration. "PC off / not logged in" is only covered by the optional external heartbeat (user decision).
