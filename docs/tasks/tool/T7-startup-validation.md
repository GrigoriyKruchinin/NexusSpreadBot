# T7 - Startup validation with Russian/English messages

- id: T7
- stage: S1-tool
- owner: backend-lead
- complexity: high (external API calls at boot, error taxonomy, secret hygiene)
- size: L
- depends_on: T6
- status: todo

## Goal
Fail early and clearly on misconfiguration; degrade gracefully (public mode) for bad exchange keys; never print secrets.

## Context docs
`adapters/key_policy.py`, `container.py`, `notifications/telegram.py`, `log.py` scrubber, A6 card

## Scope
1. Telegram checks via Bot API: `getMe` (token valid), `getChat` (chat/channel exists), `getChatMember(bot)` (for channels: administrator with `can_post_messages`; groups: bot is member), optional test message behind `--send-test` / CLI `nexus check`
2. Messages bilingual per `[alert] language` or `LANG` (en default, ru): missing token; placeholder token; invalid token (401); chat not found; bot not admin / cannot post; id looks like a channel username (`@name`) -> explain to use numeric id or `@name` support (decide)
3. Exchange keys: validate once at boot (read-only permission present, withdraw permission ABSENT where the venue API exposes it). Invalid/rejected key -> warning `venue X: key rejected, running in PUBLIC mode` and continue; withdraw-enabled key -> refuse that venue's keyed mode (fall back to public) and say why
4. Messages include the fix step and a docs link (`docs/guides/quickstart.md`); secrets/tokens never in messages or logs (test with sentinel secret, extends A4 scrub tests)
5. Exit codes: 0 ok, 3 fatal config (no restart loop, as in D-01)

## Acceptance criteria
- Unit tests with fake HTTP for each error case in both languages
- Sentinel-secret test: no log/exception text contains token or key
- Bad key for one venue does not stop other venues; scanner starts in public mode for it
- `nexus check` CLI command prints a summary table (venue, mode public/keyed, telegram ok) and is used by T8

## Out of scope
Trading-permission handling (not applicable, ADR 0001).

## Files likely touched
src/nexus/{adapters/key_policy.py,container.py,cli.py,notifications}, tests/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
