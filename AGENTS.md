# V3 Codex Startup Authority

This file applies to every Codex, executor, and reviewer task in this repository.

## Mandatory read order before any work

1. `/V3_PROJECT_CONSTITUTION.md`
2. `/docs/architecture/V3_CANONICAL_ARCHITECTURE.md`
3. `/docs/status/V3_CAPABILITY_LEVELS.md`
4. the complete task prompt
5. the task State Ledger
6. Git and GitHub CURRENT

Then read `/docs/status/V3_PROJECT_AUTHORITY_MANIFEST.json`, recompute every listed SHA-256, and store the exact authority file hashes in the Ledger.

## Non-negotiable rules

- P0 project authority outranks a later task prompt. Any conflict is `STOP_FOR_REVIEW`.
- The first Ledger fields are `TASK_GOAL`, `TASK_PROGRESS`, and `PROJECT_AUTHORITY`, in that order.
- If an authority file or expected hash changes after task admission, stop with `STOP_FOR_REVIEW`; do not silently accept authority drift.
- Before context compaction, persist the three priority Ledger fields, authority hashes, and Git/GitHub state. After compaction, repeat the complete read order and hash verification before continuing the exact next unfinished step.
- Never promote `NOT_RUN`, `PENDING`, or `BLOCKED` without the missing action and evidence. Capability language must follow `V3_CAPABILITY_LEVELS.md`.
- GitHub CURRENT is execution truth. Do not infer remote branch, PR, review, merge, or CI state from a local commit or an older report.
- Keep one branch and one PR for a bounded correction. Do not create recursive correction chains. Same finding: same PR, one bounded correction, or `STOP_FOR_REVIEW`.
- No rebase, reset, force push, amend, administrative bypass, or destructive cleanup without explicit authorization.
- Backend and quantitative work must obey canonical payload provenance: canonical ref → owner/resolver → verified actual payload → deterministic engine → content-addressed result → provenance receipt. Valid-looking IDs plus caller-supplied values are not authority.
- UI and product work must obey Chinese-first and low-chrome/no-box doctrine, preserve exact trace-critical tokens, and show unavailable/degraded states truthfully.
- AI is L0 READ / L1 DRAFT by default. L2 EXECUTE and L3 PUBLISH require the shared canonical authority defined by the Constitution; local tokens or model prose cannot grant it.
- Never substitute a demo, fixture, placeholder, static card, or fake-connected state for an unavailable capability.
