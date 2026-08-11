# Reviewer Integration V0 — Reuse Adoption Matrix

Task: `V3-ROUND4-TRACK-O-REVIEWER-INTEGRATION-V0-01`

Repository baseline: `dongxuelian11/v3-quant-workbench@0d9799f0d47285d10246c23f9f1494105f20848a`

External CURRENT observed: 2026-08-12 (Asia/Shanghai)

## Decision vocabulary

- `DIRECT_REUSE`: use the current-main owner without duplicating its truth or identity.
- `THIN_ADAPTER`: translate an existing authoritative object into a Track O read model without becoming its owner.
- `DESIGN_REFERENCE`: borrow a design lesson only; no runtime dependency or authority transfer.
- `REJECT`: incompatible with V3 authority, determinism, provenance, or licensing boundaries.
- `V3_NATIVE_REQUIRED`: the current repo lacks the bounded structure and Track O must own it.

## Current-main audit

| Candidate | Exact revision / owner | License | Relevant capability | Decision | Boundary |
|---|---|---|---|---|---|
| `ReviewerEvidence`, `ReviewerFinding`, `RewardVector` | `0d9799f0d47285d10246c23f9f1494105f20848a`; `domain/experiments` | Apache-2.0 | Frozen, content-addressed reviewer/reward evidence with explicit `PASS/FAIL/NOT_RUN` and Truth ceiling | `DIRECT_REUSE` | Track O does not create a second reward or reviewer truth owner. Existing evidence is read-only source evidence. |
| Research/Data/Reviewer Agent contracts | same revision; `agents/research_evidence_integration` | Apache-2.0 | Trusted-tool receipts, exact system citations, Reviewer draft contract, non-canonical proposal boundary | `DIRECT_REUSE` | Layer B remains `NON_CANONICAL` and `L1_DRAFT`; its narrative cannot change Layer A. |
| Pydantic reviewer worker | same revision; `agents/pydantic_worker.py` and Track G worker | Apache-2.0 | Typed structured output and explicit Reviewer role | `THIN_ADAPTER` | The worker may interpret an immutable report only. It receives no admission, publish, waive, execute, or evidence-mutation method. |
| Canonical Truth / Admission lattice | same revision; `contracts/common/truth_admission.py` | Apache-2.0 | Closed Truth, Admission, Validation, publication, and downstream ceiling semantics | `DIRECT_REUSE` | `ResearchReviewReport.truth_ceiling` is the meet of source states and cannot promote them. |
| Dataset / Split / FactorEvaluation | same revision; `domain/datasets`, `domain/factors` | Apache-2.0 | Knowledge cutoff, exact evaluation membership, split/purge/embargo semantics | `THIN_ADAPTER` | Track O reviews exact IDs, hashes, and exposed facts; it does not rematerialize data or recompute factors. |
| Experiment / Run / Attempt | same revision; `domain/experiments` | Apache-2.0 | Immutable run/attempt identity and artifact lineage | `THIN_ADAPTER` | Review bindings are read-only and exact. |
| Training / Model / Prediction | same revision; `domain/models` | Apache-2.0 | Request echo, artifact binding, training evidence, ModelVersion, PredictionArtifact, row-materialization ceiling | `THIN_ADAPTER` | Track O checks exact contract linkage; unresolved row materialization stays surfaced, never promoted. |
| Strategy / Portfolio / Risk / Backtest | same revision; current canonical F/H/I/J owners | Apache-2.0 | Period/cutoff, semantic intent, target timing, risk target receipt, RiskAdjusted schedule, execution/cost evidence | `THIN_ADAPTER` | Protected financial owners remain unchanged; Track O does not recompute engines or create financial artifacts. |
| Round 3 evidence projection | same revision; `adapters/round3_evidence` | Apache-2.0 | Exact H/I/J IDs/hashes, lineage edges, read-only Agent Workspace evidence | `DIRECT_REUSE` | Protected schema and adapter are not modified. UI reports missing backend ReviewReport as `NOT_RUN`, never as PASS. |
| `ReviewerRuleSet`, `ResearchReviewReport`, immutable Track O `ReviewerFinding`, lifecycle link | absent from current main | Apache-2.0 project license | Versioned/content-addressed rules, deterministic closed outcomes, coverage, exact report binding, `RESOLVES/SUPERSEDES` | `V3_NATIVE_REQUIRED` | Owned only by `domain/reviewer_integration`; it is review evidence, not Formal Admission. |
| Reviewer panel / summary / findings / coverage UI | absent from current main | Apache-2.0 project license | Layer A/B visual separation, exact evidence navigation, NOT_RUN visibility, lifecycle display | `V3_NATIVE_REQUIRED` | Additive Agent Workspace section only; five Labs and Evidence Inspector remain canonical. |

## External CURRENT research

| Candidate | CURRENT revision / release | License | Adopted lesson | Decision | Rejection / authority boundary |
|---|---|---|---|---|---|
| [GX Core](https://github.com/fivetran/great_expectations) (the former `great-expectations/great_expectations` URL redirects here) | `74341e3ee48fd231f4c57ba512ce66a156e80f81`; release `1.20.0` (2026-08-07) | Apache-2.0 | A versioned validation definition binds a data batch to an expectation suite; validation results remain inspectable artifacts. See [Run Validations](https://docs.greatexpectations.io/docs/core/run_validations/). | `DESIGN_REFERENCE` | No GX runtime dependency. GX `success` is not V3 Truth, Admission, publication, or a substitute for missing evidence. |
| [MLflow](https://github.com/mlflow/mlflow) | `3128eb46928fab08500124e9e0cde6791cf845aa`; release `v3.15.1` (2026-08-03) | Apache-2.0 | Separate evaluation artifacts/metrics from explicit threshold validation; missing metrics are explicit failures. See [Model Evaluation](https://mlflow.org/docs/latest/ml/evaluation). | `DESIGN_REFERENCE` | No MLflow evaluator or LLM judge can create V3 Admission. Track O does not import metric validation as canonical truth. |
| [Qlib](https://github.com/microsoft/qlib) | `79633dd9506ea689e5400dea0197717b5b3d74b7`; release `v0.9.7` | MIT | Explicit Experiment → Recorder(run) hierarchy and retained result artifacts. See [Qlib Recorder](https://qlib.readthedocs.io/en/stable/component/recorder.html). | `DESIGN_REFERENCE` | Qlib identities and experiment state do not replace V3 Experiment/Run/Attempt or PIT provenance. |
| [RD-Agent](https://github.com/microsoft/RD-Agent) | `6762f84f9bc0f5c6486c50a00e128a57ac6c3683`; release `v0.8.0` | MIT | Hypothesis → experiment → execution feedback → next iteration is useful research-loop vocabulary. | `DESIGN_REFERENCE` | Autonomous feedback must not become deterministic evidence, finding waiver, formal approval, execution authority, or publication authority. Track O does not depend on its runtime. |
| [Pydantic AI / Pydantic Evals](https://github.com/pydantic/pydantic-ai) | `655c829f6386e3184dbd7a87e5e93bc1e1984900`; release `v2.27.1` (2026-08-11) | MIT | Typed evaluators, version tags, structured result/value/reason separation. See [Evaluator API](https://pydantic.dev/docs/ai/api/pydantic_evals/evaluators/). | `DESIGN_REFERENCE` | Structured shape does not prove factual correctness. LLM judge scores/reasons remain Layer B concerns unless exact canonical evidence independently supports a Layer A rule. |
| [Nature Portfolio reporting standards](https://www.nature.com/nm/editorial-policies/reporting-standards) and [Reporting Summary](https://www.nature.com/documents/nr-reporting-summary-flat.pdf) | web policy observed 2026-08-12; reference form published 2026 | Proprietary web/form content; no code license relied upon | Require explicit study design, statistics, exclusions, replication, data/code availability, and negative disclosures rather than silent blanks. | `DESIGN_REFERENCE` | Concepts only. No text/template copying and no implication that a software review equals scientific peer review or journal acceptance. |

## Closed adoption gate

1. The repository's existing canonical evidence, Truth/Admission lattice, agent permission model, and H/I/J read-only projection remain the only authorities reused directly.
2. External systems are design references only. None is installed, imported, or allowed to emit V3 `PASS`, Formal Admission, publication, or waiver.
3. Track O owns only the missing immutable review-rule/report/finding/lifecycle structures and Reviewer UI.
4. Lack of exact evidence is `NOT_RUN` or `INSUFFICIENT_EVIDENCE`; it is never inferred from `PRE_ALPHA`, an agent concern, a tool score, or a green UI state.

Gate result: `V3_NATIVE_REQUIRED` for the bounded Track O structures, with current-main direct reuse and thin read adapters around existing canonical owners.
