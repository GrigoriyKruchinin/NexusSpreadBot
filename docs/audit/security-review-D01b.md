# Security review D-01b: auto-recovery + host-side dead-man watchdog

Reviewer: security (static review + unit tests only; `.env` not read, watchdog not executed against the live stack,
no state-changing docker commands). Commits: 7c06a23, 3ed5b61, 1f78bd2 (branch `chore/agent-pipeline-adoption`).

## Verdict: ACCEPT (no blocking findings; F-1..F-3 recommended as a follow-up, not required before deploy)

## Scope checked
| Area | Result |
|---|---|
| Token in argv / `ps` | OK. Token is read into a shell variable (`grep`/parameter expansion, no `source`), validated by `^[0-9]+:[A-Za-z0-9_-]+$`, and written by the bash builtin `printf` into a pipe to `curl --config -`. No external process gets it in argv. Test `test_token_goes_through_stdin_config_not_argv` + the global argv assertion cover it. |
| curl config injection | OK. Token regex and heartbeat URL regex exclude `"`, `\`, whitespace and newlines, so the value cannot break out of `url = "..."`. |
| stdout/stderr, cron mail, log file | OK. Only fixed messages, service names/states and the HTTP code are logged; curl stderr goes to `/dev/null`; `-q` ignores `~/.curlrc` (no `verbose`/`trace` from user config). Crontab line redirects all output to the log file, so no cron mail. |
| `set -x` / verbose | OK. No `set -x`, no `-v` on curl; the guide does not suggest `bash -x`. |
| Error paths | OK. Missing/malformed credentials -> generic warning "values not shown"; curl failure -> `http 000`; heartbeat failure details suppressed. |
| Temp files | OK. None created; state = three integers, lock file empty. |
| Docker commands | OK. Only `docker info` (output discarded), `docker compose ps -a --format '{{.Service}} {{.State}} {{.Health}}'` and `docker compose start <svc>` (output discarded). No `up`/`down`/`build`/`exec`/`inspect`/`config`; the `ps` format cannot print env. |
| Telegram payload | OK. Contains only service names/states from `compose ps`. `chat_id` is in curl argv: not a credential (Info, see F-5). |
| Baked config | OK. `config/nexus.toml` is committed, non-secret, and the fail-closed loader (`src/nexus/config/file.py`, A7) refuses secret/unknown keys, so a secret cannot be baked in silently. `.dockerignore` excludes `.env`, `.env.*` (except `.env.example`), `.git`, `.claude`, backups/dumps; the Dockerfile copies only `config/nexus.toml`. Test `test_config_file_is_baked_into_the_image_not_bind_mounted` pins it. Image is local-only (not pushed). |
| External heartbeat URL | OK. File must be a regular file owned by the user with mode 600 (a symlink fails the `stat` check), https only, passed via stdin config, never logged. Pinged only when healthy (correct dead-man semantics). |
| Guide (Task Scheduler / crontab) | OK. Task runs `wsl.exe ... sleep infinity` as the user, no elevation, no stored password. Autologon is correctly flagged as a security trade-off. No step reads/prints `.env` or runs forbidden commands. |
| Secrets scan of the 3 commits | Clean (token/heartbeat/AWS/private-key patterns: no hits). |
| Tests | `tests/unit/scripts/test_host_watchdog.py` + `tests/unit/test_compose.py`: 35 passed. |

## Findings
1. **F-1 (Low) Forgotten pause file silently disables the dead-man.** `~/.nexus-watchdog-pause` stops everything
   indefinitely with only a log line. Without the optional external heartbeat nobody is told. Recommend: if the pause
   file is older than N hours (e.g. 12 h), send one Telegram reminder (and keep pausing). Abuse needs same-user write
   access to `$HOME`, which already implies full compromise; no privilege issue.
2. **F-2 (Low) State dir permissions depend on who creates it first.** The guide runs `mkdir -p ~/.local/state/nexus-host-watchdog`
   (umask 022 -> 0755) before the script's `mkdir -p -m 700`, which does not change an existing dir; the log file is
   created 0644 by the cron redirect. Contents are non-secret (service states), so impact is minimal. Recommend:
   guide uses `mkdir -p -m 700 ...` and the script runs `chmod 700 "$STATE_DIR"` (and optionally `umask 077`).
3. **F-3 (Low) Unbounded log file.** `watchdog.log` grows forever (~15 KB/day) and relies on manual truncation.
   Not a security risk by itself; recommend size-capped rotation (e.g. truncate in the script above 1 MB) for long soaks.
4. **F-4 (Info) `read_env` matches only `KEY=value` lines.** An `export KEY=...` line is ignored (fails closed: no
   send, warning logged). Functional, not a leak.
5. **F-5 (Info) `chat_id` and message text are visible in curl argv** to same-host users for ~1 s. Chat id is not a
   credential (the token is required to post); acceptable. Could be moved into the stdin config if desired.
6. **F-6 (Info) Ad-hoc debugging.** Running the script with `bash -x` would expose the token in xtrace. Recommend one
   comment line in the script header: "never run with bash -x".

## Rule compliance
ADR 0001 (no withdrawal/order code): untouched. CLAUDE.md rule 4: the script reads `.env` itself at runtime on the
user's host (agent never did); no `config`/`inspect`/`exec`. Rule 5: no DB access.

## NEEDS_USER
None for this review. (Deploy itself still needs the user's OK per the handoff: soak data gap ~1-2 min.)
