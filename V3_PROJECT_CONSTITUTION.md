# V3 Project Constitution

Authority version: `1.0.1`
Authority status: `P0_PROJECT_AUTHORITY`

This Constitution is normative project doctrine and a target invariant set. It is not a claim that every owner, integration, runtime handler, or product surface is already implemented or accepted. Current maturity must be stated with the vocabulary in `docs/status/V3_CAPABILITY_LEVELS.md` and supported by current evidence.

## 1. Product identity

V3 is:

> **A local-first, A-share-first, AI-native, reproducible and auditable professional Quant Research IDE / Workbench.**

V3 exists for professional China A-share quantitative research, deterministic computation, controlled experiments, reproducible backtests, provenance/evidence inspection, and AI-assisted research in which AI never owns financial truth.

V3 is not:

- a broker or live-trading terminal;
- a generic dashboard;
- a Qlib or vn.py GUI wrapper;
- an AI chat application with quant widgets;
- a demo-first research toy;
- a collection of disconnected backend modules.

## 2. Canonical research chain

```text
Data Truth
    ↓
Universe
    ↓
Factor / Dataset
    ↓
Model
    ↓
Signal
    ↓
Portfolio
    ↓
Risk
    ↓
Backtest
    ↓
Result
    ↓
Experiment / Artifact / Evidence
```

The cross-cutting owners are Control Plane / Task / Worker, Resource Governance, Artifact / Provenance, Reviewer, AI / Agent, and Desktop / Product UX.

## 3. Core authority principle

> **AI proposes and orchestrates; deterministic engines compute; V3 canonical owners validate, persist and own truth.**

```text
Agent Proposal
!= Execution
!= Canonical Truth
```

A caller DTO, UI state, LLM prose, local token, or private Python object cannot become authority by declaration. Authority belongs to the named canonical owner and is transferred only through an explicit, verified contract.

### 3.1 P0 Authority Amendment Protocol — HARD

The protected P0 Authority set is:

```text
/V3_PROJECT_CONSTITUTION.md
/AGENTS.md
/docs/architecture/V3_CANONICAL_ARCHITECTURE.md
/docs/status/V3_CAPABILITY_LEVELS.md
/docs/status/V3_PROJECT_AUTHORITY_MANIFEST.json
```

A normal feature, bug-fix, review, remediation, UI, runtime, migration, merge-closure, or refactor task MUST NOT modify any protected P0 Authority file or the Authority Manifest. If such a task discovers that P0 doctrine must change, the result is `STOP_FOR_REVIEW`; the task must not edit doctrine opportunistically.

Only an original task prompt explicitly authorized by the user as `P0_AUTHORITY_AMENDMENT` may modify this set. Authorization is never implied by documentation wording, implementation conflict, CI failure, Agent recommendation, or executor judgment.

Every amendment records its exact scope and rationale, previous and incremented `authority_version`, exact changed P0 files, and recomputed SHA-256 values for every locked file; updates the Manifest; passes the authority validator and normal repository validation; and proceeds through an ordinary commit, push, PR, and exact-SHA independent review. It is never auto-merged without separate authorization, and any accepted merge requires exact-main verification. History is preserved without overwrite.

P0 Authority is tamper-evident, governance-controlled, and Git-history traceable. It is not technically immutable and evolves only through this explicit amendment protocol.

## 4. Canonical payload provenance — HARD

Every formal numeric computation follows this exact doctrine:

```text
Canonical Reference
        ↓
Canonical Owner / Verified Artifact Store
        ↓
Canonical Payload Resolver
        ↓
Verified Actual Payload
        ↓
Deterministic Engine
        ↓
Content-addressed Result
        ↓
Exact Provenance / Resolution Receipt
```

The following shortcut is forbidden:

```text
valid-looking id/hash
+
independent caller-provided prices/scores/samples/values/market-state
→ formal computation
```

Actual bytes or values must be resolved from, or verified against, the canonical owner or verified Artifact Store before formal computation. This HARD rule covers market data, historical Universe membership, Factor inputs, `FeatureMaterialization`, Dataset samples and labels, Model training/prediction samples, Strategy score inputs, Portfolio inputs, Backtest market state, metrics, Reviewer evidence, and Experiment/Reward inputs.

Self-consistent references without verified content are insufficient evidence. A content hash is useful only when the actual payload is retrieved and verified under the declared hash and owner.

## 5. Single authority; no second engine

- `FactorDefinitionVersion` is the sole Factor mathematics authority.
- TDX source lowers into the canonical Factor IR; `no second TDX VM` is a hard rule.
- The frontend must not evaluate Factor mathematics.
- Alpha Mining must reuse the canonical IR and evaluator.
- Third-party code runs only behind explicit adapters, worker boundaries, and contracts.
- Third-party output cannot mint V3 canonical truth directly.
- Reuse of implementation does not transfer semantic ownership.

## 6. Financial semantics first

Where applicable, every formal path must explicitly bind and verify:

- PIT/as-of and knowledge time;
- historical Universe membership;
- trading calendar and session timing;
- suspension and ST state;
- listing and delisting;
- limit-up/down and board-specific rules;
- corporate actions, dividends, and splits;
- lot size, cash, and position constraints;
- transaction costs;
- execution and valuation timing;
- benchmark context;
- survivorship-bias controls.

Unavailable semantics remain explicitly unavailable. Defaults, convenience data, current membership, or inferred market state cannot silently substitute for missing historical truth.

## 7. Truth ceiling

```text
downstream truth/admission
<= meet(all upstream truth/admission)
```

Without new authority and evidence, the following promotions are forbidden:

```text
NOT_RUN -> PASS
NOT_AVAILABLE -> AVAILABLE
PENDING -> COMPLETE
BLOCKED -> COMPLETE
UNKNOWN -> VERIFIED
PRE_ALPHA -> FORMAL
```

## 8. Capability truth

```text
backend module exists
!= integrated
!= product connected
!= production available
```

A green test, an accepted module, or a merged PR proves only its stated evidence level. It does not automatically prove end-to-end product completion. Documentation, UI labels, Ledgers, PRs, and reports must name the exact maturity level they prove.

## 9. Runtime truth

Packaged production must use real canonical owners and production runtime services or state that the capability is unavailable.

- No hidden development fixture or demo fallback.
- No test runtime represented as production.
- No UI fake-connected state.
- Development fixtures must be explicitly enabled, visibly classified, and unable to mint production truth.

## 10. Agent authority

The default authority boundary is:

```text
L0 READ      allowed
L1 DRAFT     allowed
L2 EXECUTE   denied until shared canonical user-action authority exists
L3 PUBLISH   denied unless separately authorized
```

Until shared canonical user-action authority exists:

```text
Production Agent execution
= NOT_AVAILABLE / NOT_RUN
```

This applies across Factor, Model, Portfolio/Risk, Alpha Mining, and future Agents. A model response, local confirmation boolean, or Agent-owned approval object cannot bypass the shared authority boundary.

## 11. Evidence and Reviewer

Evidence must prove the actual payload and actual computation, not only a self-consistent ID graph. When bytes or data matter, the Reviewer must resolve them through the canonical owner, verify them through the Artifact Store, or deterministically recompute them. Missing evidence remains missing; a Reviewer cannot upgrade truth by confidence language.

## 12. Controlled experiments

A material context mismatch is:

`INCOMPARABLE_CONTEXT`

unless the difference is an explicitly declared controlled treatment. There is no context-free “best” factor, model, strategy, portfolio, or result.

## 13. Reuse-first and evidence-first

The default development order is:

```text
Requirement
→ OSS/paper/standard research
→ Adoption Gate
→ Dependency
→ Thin Adapter
→ Worker/API/CLI
→ Selective Module Reuse
→ Design Reference
→ Native implementation last
```

Licensing, provenance, runtime isolation, determinism, PIT semantics, and authority boundaries remain mandatory at every step. Reuse never transfers V3 authority.

## 14. Product UX identity

V3 is a modern Windows professional Quant IDE with an Agent-first top-level flow and five retained professional Labs. It is Chinese-first, dense but calm, low-chrome/no-box, custom-Electron-chrome, keyboard-friendly, accessible, and not a fake macOS clone.

### 14.1 Chinese-first — HARD

- Normal navigation, buttons, panel titles, status, help, tooltips, filters, and categories require Chinese.
- Professional state/type/version labels use Chinese plus the canonical token when the token matters.
- SHA values, IDs, formulas, operators, code, and trace-critical enum tokens retain exact text.
- A surface dominated by ordinary English labels is non-compliant.

### 14.2 Low-chrome / no-box — HARD

The default is `NO BOX`. Border/card nesting must not be the primary hierarchy. Prefer spacing, typography, alignment, subtle separators, and restrained material layers. Cards and borders are reserved for genuinely interactive or semantically bounded objects.

## 15. No downgrade, substitution, or silent deferral

Do not replace a promised capability with a placeholder, static card, fake demo, hidden fixture, fixed layout, fake success, or silent “later phase.” If the capability is unavailable, the product and documentation must say so explicitly.

## 16. GitHub-native development

```text
prompt
→ branch
→ implementation
→ tests
→ commit
→ push
→ PR
→ exact-SHA independent review
→ same-PR bounded correction
→ merge
→ exact-main verification
```

No reset, rebase, force push, or administrative bypass is allowed without explicit authorization. GitHub CURRENT is the execution truth for remote branch, PR, review, merge, and CI state.

## 17. No recursive correction chains

The same finding stays on the same branch and same PR for one bounded correction, or becomes `STOP_FOR_REVIEW`. Do not automatically create recursive C2/C3/R2 correction chains.

## 18. Context compaction and State Ledgers

Every long-running task Ledger begins, in this order, with:

```text
TASK_GOAL
TASK_PROGRESS
PROJECT_AUTHORITY
```

Before compaction, persist those fields, current authority identities and hashes, and current Git/GitHub state. After compaction, repeat the mandatory read order in root `AGENTS.md`, verify the authority manifest, refresh Git/GitHub CURRENT, and continue only from the exact next unfinished step.

## 19. Documentation truth

README, architecture, status documents, UI state, and PR language must match current evidence. They must not claim a capability absent when a module exists, and must not claim `PRODUCTION_AVAILABLE` when only a module exists.

## 20. Whole-system review questions

Every executor and Reviewer asks:

1. Who owns this truth?
2. Where did the actual payload come from?
3. Was it resolved from the canonical owner?
4. Was actual content verified, not only the ID?
5. Can a caller spoof values while presenting valid references?
6. Is PIT/as-of explicit?
7. Is the result content-addressed?
8. Does Reviewer evidence cover the actual payload and computation?
9. Is the production runtime actually connected?
10. Does the UI show the true state?
11. Does the change serve V3 product identity?
