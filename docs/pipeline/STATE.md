# STATE (updated 2026-10-23, end of session)

## Where we are
- Trajectory M (MVP/analysis, GO/NO-GO protocol). Branch `chore/agent-pipeline-adoption`, pushed; not
  merged to `main` (merge/PR only with user consent). CI green on HEAD incl. integration (gh CLI works
  now: `gh run list`, `gh run view <id>`).
- Unit tests 721, branch coverage ~90.5 %, ruff 0, mypy --strict 0 (ratchet floor: 89 %).

## Done this session (all committed + pushed)
- Phase 5 tail: legal + security reviews of vision/architecture; target.md §10 security model; A5 split
  A5a-A5d; legal GO gates checklist `docs/legal/go-gates-checklist.md`.
- Track 0 code, reviewed + accepted: B1 CORE_EXCHANGES, A2 CI (R-05), A2a gitleaks pre-commit, A4 log
  scrub (R-07), B1a drop MEXC/BITGET key vars, A6 key-policy startup check (tech-lead r2 + security
  accepted; follow-ups F-1..F-5 in todo).
- B14 conditional venues reporting (tech-lead r2 + security accepted; R2-1 carried into B15 card).
- A5a backups: scripts + roles `nexus_ro`, `nexus_test_owner`, DB `nexus_test` bootstrapped on the
  local cluster; first dump + restore drill PASSED (`docs/reports/restore-drill.md`). Reviews: tech-lead
  r2 ACCEPT, security r2 ACCEPT w/ follow-ups (R2-1/R2-2/N1/N2 fixed in 1674089; N3/N4 nits open).
  Daily cron 03:15 `make backup` in user crontab (log ~/nexus-backups/backup.log); heartbeat deferred
  to VPS (A5d) by user decision.
- Research: exchange key permissions, expansion candidates (20 ranked, batches),
  legal review of expansion venues `docs/legal/expansion-venues-review.md`.
- Vision: GO bar after tax; GO-HOLD outcome (ADR 0008); Bybit + gateio = conditional venues.

## In flight / next (in order)
1. (superseded by fresh-stack decision; drill runs on the new DB after its first nightly dump) After 2026-10-24 03:15: check backup.log + new dump with `.counts` sidecar; ask user U4 OK to re-run
   `make restore-drill` on it (old dump has no sidecar, drill refuses it); record in restore-drill.md.
2. (done) A5a reviews + leftovers.
3. (done) Stage-end Track 0 + B14: regression clean (`docs/reports/regression-track0-B14.md`), delta audit
   `docs/audit/delta-track0-B14.md` (R-01/05/06/07 closed; new D-01..D-07; pre-soak gates in todo M3).
4. **B15** (part 1 ACCEPTED by architect/quant/tech-lead; part 2 = GO report, can run in parallel with the soak) shadow paper portfolios (needs migration; A5a gate passed; user U4 OK required before
   applying to live `nexus`; capital $10,000 per set; includes R2-1 fix).
5. **B16** public-only probe of batch 1 per legal verdicts: BingX, XT, Toobit OK; Bitfinex, Phemex
   public only. Batch 2: WEEX after DNI; DigiFinex, Deepcoin public only; Poloniex, LBank do not register.
5a. (done) A7 config file `config/nexus.toml`, `.env` = secrets + ENV-ONLY; 4 soak sets set in TOML. User must run `make check-env-settings` and move non-default values from `.env` before the fresh stack.
6. Remaining Track 0: A5b Redis auth, A5c DB roles, A5d (deferred to VPS), A6 follow-ups.
7. Then soak (needs B15 + backups running), quant, GO/NO-GO.

## User decisions (2026-10-23)
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
- devops attempted a write probe on live `nexus` despite an explicit ban (blocked by the harness, no
  effect). For live-DB tasks: give exact commands to run and review them; never ask for "verification"
  without listing allowed read-only queries.
- Concurrent agents + pre-commit: commit may fail with "files were modified"; just retry.
- Session can die mid-run: after restart check `git status` for partial agent output before relaunching.
