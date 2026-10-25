# T10 - README quickstart (EN) and docs/guides/quickstart.md (RU)

- id: T10
- stage: S1-tool
- owner: scribe
- complexity: medium (docs, but must be walked through literally)
- size: M
- depends_on: T8
- status: done (scribe draft 2026-10-25; user walk-through pending = NEEDS_USER; commit by orchestrator)

## Goal
A new user reaches working alerts in 10 minutes from the README alone.

## Context docs
`README.md`, `docs/guides/stage-1-local-setup.md`, outputs of T6-T8

## Scope
1. README (English): what it is (screenshots/sample alert text), requirements (Docker), 5-step quickstart, config table, public vs keyed mode, safety (read-only keys, no trading, not financial advice), troubleshooting table from T7 messages, license note
2. Russian `docs/guides/quickstart.md`: same plus BotFather steps, channel creation, adding the bot as admin, finding `-100...` id, creating read-only keys per venue with permission checklist, how to stop/reset
3. Disclaimer + exchange ToS note from the lawyer card T13

## Acceptance criteria
- A person who did not write the code follows the guide verbatim (user walk-through) - NEEDS the user's confirmation
- Every command in the guides exists in Makefile (script check) and no command expands `.env`
- Links valid (link check)

## Out of scope
Marketing, website.

## Files likely touched
README.md, docs/guides/quickstart.md

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).

## Progress (2026-10-25, scribe)
- `README.md` rewritten (EN, short): quickstart via `make up`, config table, key policy, disclaimer and exchange
  terms (lawyer s. 3.1, 3.4), troubleshooting, update/stop/reset, Apache-2.0 note.
- `docs/guides/quickstart.md` written (RU, plain language): BotFather, private chat / private channel id (-100...),
  bot as admin with "Post messages" + "Edit messages of others", read-only key checklist, legal notes, troubleshooting.
- API-keys statement: lawyer s. 3.3 ("Your keys stay with you") NOT used verbatim. T9 security ACCEPT is not recorded
  yet, so the text is reworded as a design goal until security records the review.
- Checked by hand: every `make` target used exists in Makefile (up, ps, logs, doctor, down, reset-data, migrate, check,
  test-integration); no command reads `.env`; relative links point to existing files.
- Open: user walk-through of the guide (acceptance criterion 1), security ACCEPT for the key statement (T9).
