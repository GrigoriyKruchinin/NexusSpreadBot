# STATE (updated 2026-10-24)

## Where we are
- Trajectory M. Branch `chore/agent-pipeline-adoption`, pushed, CI green on HEAD (7 jobs incl. integration).
  Not merged to `main` (only with user consent).
- Unit tests 999, branch coverage 91.3 %, ruff 0, mypy --strict 0 (ratchet floor 89 %).
- Local stack STOPPED on purpose (fresh-stack plan below); nightly 03:15 backup fails meanwhile (expected).

## Done 2026-10-23 (all committed + pushed)
- B15 part 1 (venue-set shadow paper portfolios, run registry, coin-slot recycle, cap stats, migration
  b15a7c3e91d2 unapplied anywhere but CI): architect r2, quant r2, tech-lead r3 ACCEPT + F1/F3 done.
  Part 2 spec: `docs/quant/b15-review-and-report-spec.md`.
- A7 `config/nexus.toml` (settings) vs `.env` (secrets + ENV-ONLY), startup guard, `make check-env-settings`;
  security r1 + tech-lead r2 ACCEPT. 4 soak sets set in TOML.
- repo-hygiene stage-end step (skill `.claude/skills/repo-hygiene`).
- Key-leak incident handled: deny rules in `.claude/settings.json`, CLAUDE.md rule 4, cards A5b/A5c/B1a fixed.
- S0 pre-soak gates (card `docs/tasks/m3/S0-pre-soak-gates.md`): S0a devops 3bb5746 + r2 2c528c6,
  S0b backend-lead up to 21897bf + r2 cb1c1af. Security ACCEPT w/ follow-ups (S-1 fixed, S-2..S-4 fixed in r2,
  S-7 deny widening done). Tech-lead r1 RETURN, r2 ACCEPT 2026-10-24 (`docs/audit/tech-lead-review-S0.md`); S0 ticked.
  Open check: D-01 must be confirmed live on first Docker/WSL restart of the soak (scanner back `Up`, security S-8).

## Next (in order) — resume here
1. Stage end for S0 can run now (code side): tester regression -> delta audit -> repo-hygiene.
2. User steps before the fresh stack (U3/U4): rotate all 4 exchange keys and put them in `.env` himself;
   run `make check-env-settings` and move non-default values from `.env` to `config/nexus.toml`;
   disable Windows sleep; delete the leaked agent log
   `~/.claude/projects/-home-grisha-projects-NexusSpreadBot/8ed7c197-a2ee-44ec-acbe-b9f593b81aa7/subagents/agent-a08740f7208ef3c03.jsonl`
   (harness blocked the agent from deleting it).
3. Fresh stack (explicit U4 at each data step): `make backup-archive` of old DB -> new empty DB volume
   (no `down -v`; keep old volume) -> migrator from zero -> stack up -> soak starts -> first nightly dump +
   restore drill on new DB (D-03) -> 24 h soak checkpoint (card B15: union/cap p95 > 1.3, sweep duration
   +25 %, any rate-limit ban -> NEEDS_USER) -> later remove old volume with user OK.
4. In parallel with the soak: B15 part 2 GO report generator (quant spec; F2 fee disclosure; tax 15 % and
   35 %; strict concentration rule; per-set `since`; gap accounting from paper_cap_stats.sweeps).
5. Then: B16 public probe of expansion batch 1; A5b Redis auth, A5c DB roles, A6/A7 follow-ups; A5d at VPS.
6. Stage summary to user after item 1.

## User decisions (2026-10-23)
- Soak runs on this PC (WSL; user disables Windows sleep). Off-machine dump copy: `C:\nexus-backups` (/mnt/c/nexus-backups, outside OneDrive). Pre-soak gates in card S0.
- Soak starts on a FRESH stack + clean `nexus` DB once the final version is ready (B15 part 1, A7, pre-soak gates). Old data/logs/backups treated as obsolete. Plan (needs explicit U4 at execution): final archive dump of old DB -> new empty DB/volume (no `down -v`; old volume kept until soak verified, then removed with user OK) -> migrator from zero -> stack up -> first nightly dump + restore drill on the new DB (D-03). Stack stays stopped until then; nightly 03:15 backup will fail meanwhile (expected).
- A7: non-secret settings move to committed `config/nexus.toml`; `.env` keeps only secrets (after B15 part 1).
- B15 concentration rule (strict): GO requires >= 2 %/month after tax even without the top-2 routes and, separately, without the top-2 coins.
- Soak runs 4 venue sets: all, excl_conditional, excl_bybit, excl_gateio.
- B15 GO report tax rate: show BOTH 15 % and 35 %; GO judged on the worse (35 %). Preliminary, accountant to confirm.
- GO bar 2 %/month **after** income tax. GO-HOLD = analytical GO but gates unmet -> keep developing
  without money (DEX allowed), launch after DNI + keys for the final GO venue set. Real legal
  penalties (fines/criminal, per a human lawyer) -> NO-GO/stop.
- Bybit and gateio: GO numbers with and without; judged without them if not resolved by UF.
- Digest/Telegram: list of conditional venues + combined totals all vs excluding (done in B14).
- GO numbers via shadow portfolios, venue sets from config (default 2), $10,000 each.
- Integration tests run only in CI. Push of the working branch is allowed.
- Proxy per exchange: backlog idea, lawyer ToS check first, design with user when a server is chosen.
- Expand venues (up to ~20): public-data probe first, user registers only where worth it.

## User facts / open items for the user
- RF citizen (passport), resident in Argentina, DNI pending. Keys for binance/gateio/kucoin/okx are in
  `.env` (never read it). Bybit: 1.6 ETH transfer frozen, compliance ticket ~1.5 months. Binance
  account opened as RF resident -> change residence on the existing account, do NOT open a second one.
  Gate ToS 2.5 lists Argentina and Russia as restricted (user to ask Gate support in writing).
- User actions list: `docs/legal/go-gates-checklist.md` (check residence/domain on each venue, Gate
  ticket, Binance residence change, Bybit ticket only, questions for a human lawyer/accountant).
- Branch protection on `main`: user was configuring (checks: lint, typecheck, unit, integration,
  secret-scan, dependency-audit, docker-build; 0 required approvals).
- `uv run pre-commit install` once (gitleaks hook). KEY_POLICY_* attestation flags default false.
- LICENSE decision.

## Lessons
- INCIDENT 2026-10-23: devops ran `docker compose config` (was allow-listed!) which expanded `.env` and printed live binance/gateio/kucoin/okx keys into its transcript and the model request. Not in git/files. User rotates all 4 keys himself. Fix: allow rule removed, deny rules for compose config/inspect/exec/printenv/cat .env added, CLAUDE.md rule 4 extended. Agent prompts must list implicit `.env` readers explicitly.
- devops attempted a write probe on live `nexus` despite an explicit ban (blocked by the harness, no
  effect). For live-DB tasks: give exact commands to run and review them; never ask for "verification"
  without listing allowed read-only queries.
- Concurrent agents + pre-commit: commit may fail with "files were modified"; just retry.
- Session can die mid-run: after restart check `git status` for partial agent output before relaunching.
