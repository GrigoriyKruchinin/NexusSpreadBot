# A2a — gitleaks pre-commit hook (S-06, G1)

- id: A2a (follow-up to A2; security review gap G1)
- stage: Track 0 (base)
- owner: devops
- complexity: low
- depends_on: A2 (CI gitleaks version pin and `.gitleaks.toml`)
- status: done

## Goal
Secrets are caught locally before commit, with the same rules as CI.

## Context docs
`docs/audit/security-review-architecture.md` (S-06, G1), `.gitleaks.toml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`.

## Acceptance criteria
1. `.pre-commit-config.yaml` has a gitleaks hook pinned to a fixed tag/rev (same version as CI), using `.gitleaks.toml`, staged-changes mode, redacted output.
2. A throwaway fake secret (non-real pattern) in a staged scratch file is blocked; removed afterwards, nothing committed.
3. Hook does not break existing hooks; setup line added to `docs/conventions.md` or README.
4. `make check` not worse than baseline.

## Out of scope
CI changes, history scanning (CI does it), allowlist changes.

## Files likely touched
`.pre-commit-config.yaml`, docs note, `todo.md`.
