# Tester regression - S1-tool (T14 stage gates)

Scope: branch chore/agent-pipeline-adoption at e0093eb (tech-lead ACCEPT round 3). Unit tests only; no docker, no DB, no integration.

## Numbers (ratchet 1085 / 92.08 % / floor 89 % / ruff 0 / mypy 0)
| Check | Result |
|---|---|
| `make check` (lint + typecheck + test) | green; 1085 passed, 19 deselected (integration) |
| `make test-cov` | 1085 passed; branch coverage 92.08 %; floor 89 % reached |
| ruff / mypy --strict | 0 / 0 (part of make check) |
| vs ratchet | equal, not worse |

## Carried items
- N-2 (real image build with/without config/local.toml): PENDING USER. Steps 1-2 of docs/guides/s1-tool-e2e-check.md. Static basis: Dockerfile uses glob `config/local.tom[l]`, so build must work in both cases; only a real build proves it.
- N-3: E2E on test bot + private channel: PENDING USER (steps 3-8 of the guide: nexus check, NEW/UPDATE/CLOSED edit-in-place, ru language, pin-text, system event).

## Not run (by instruction)
Integration tests, docker, stack start.

## Verdict
Unit regression PASS. Stage S1-tool closes after user reports on the guide.
