---
name: next-task
description: Run the full autonomous delivery loop for the next unchecked todo.md item - implement, verify (quality, tests, risk audit), tick todo.md, commit and push. Respects the "Start Implementation" gate and stage guide requirements.
---

# next-task

1. Read `todo.md`. Find the first unchecked `- [ ]` item in the earliest incomplete stage.
   If Phase 0 is complete but the user has not yet said "Start Implementation", stop and remind
   them (in Russian).
2. If the item is a Stage's user-guide item (`x.0`), write the guide as a Russian Markdown file in
   `docs/guides/` (see CLAUDE.md "Workflow Gates"); in chat give only the link and a 1–3 line
   summary. Do not paste the guide into chat. If the next items need secrets the user has not
   provided yet, continue with items that don't need them.
3. Implement the item (directly or via the `implementation` agent), including tests.
4. Verify: `/check-code-quality` and `/run-tests` until green; `/audit-risks` if the item is `(R)`
   or touches money math, execution, or secrets.
5. Tick the item `[x]` in `todo.md`.
6. Run `/ship` (commit + push).
7. Proceed to the next item automatically. Pause only for the conditions listed in CLAUDE.md
   "Autonomous Delivery Loop" → Rules.
