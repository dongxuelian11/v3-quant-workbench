# Round 5 S Bounded Alpha Mining Contract

Task: `V3-ROUND5-S-ALPHA-MINING-01`

Base: `eda009b601b681c8a26d2a98a1093b3e6f33245e`

## Authority path

```text
explicit Control Plane-resolved USER authorization
  -> existing ResourceGovernor admission
  -> AlphaMiningJobSpec
  -> deterministic closed grammar
  -> MiningFactorCandidate (NON_CANONICAL / DRAFT)
  -> existing Canonical Factor IR validation
  -> existing FactorDefinitionVersion
  -> ExistingFactorEvaluationPort
  -> exact FactorEvaluation + Experiment Run/Attempt + ReviewerEvidence + RewardVector
  -> AlphaMiningRewardPolicyVersion projection
  -> AlphaMiningRunRecord
```

S never evaluates factor values. The injected port must return existing canonical
objects, and S rejects evidence unless FactorDefinitionVersion, FactorEvaluation
context, Dataset, Experiment Run/Attempt, ReviewerEvidence, RewardVector,
complexity, period, label, horizon, evaluation policy and cost context all match
the exact job.

## V1 search space

The CI fixture uses existing `default_operator_registry()` and this numeric
allowlist:

- `ADD@1.0.0`
- `SUBTRACT@1.0.0`
- `MULTIPLY@1.0.0`
- `DIVIDE@1.0.0`
- `LAG@1.0.0`

Every operator is resolved from the exact registry and must be deterministic,
PIT-safe, and closed over `FLOAT_SERIES`. `LEAD`, boolean-only operators,
unregistered operators, arbitrary Python, external programs and fields without
an exact `data-truth-field:` reference fail before evaluation.

The generator uses SHA-256 selection over the job seed, generation, candidate
ordinal and policy version. It does not depend on an LLM or process-global PRNG
state. Candidate source is canonical `V3_FACTOR_IR_JSON/1.0.0`; it is lineage,
not executable code.

## Bounds and stop truth

Every job content-addresses positive finite limits for expression depth, node
count, candidates, generations and evaluations, plus an exact existing
`ResearchLoopBudgetVersion` and `OperationProfile`. The two wall-clock limits
must match. No `0` or `-1` means unlimited.

Reaching the requested target is `SUCCEEDED`. Candidate, generation, evaluation
or reviewer-blocking stops are `PARTIAL` with an exact reason and retained
candidate lineage. A canonical definition is attempted at most once per exact
job context; another attempt requires a new explicit job/reason.

## Reward policy

`AlphaMiningRewardPolicyVersion` contains exact decimal weights, per-component
missing behavior and the blocking-reviewer rule. The V1 fixture consumes only
actually available fields from the existing `RewardVector`:

| Component | Fixture weight | Meaning |
|---|---:|---|
| Rank IC | `1` | positive reward |
| IC | `0.5` | positive reward |
| coverage | `0.25` | positive reward |
| turnover | `-0.2` | deterministic penalty |
| complexity | `-0.01` | deterministic bloat penalty |

Missing evidence is `NOT_AVAILABLE`; an explicit zero is possible only when the
policy says `EXPLICIT_ZERO`, which changes policy identity. A blocking Reviewer
finding yields `BLOCKED_BY_REVIEWER` and no total reward. LLM output never assigns
reward.

## User / Agent / promotion boundaries

- `AlphaMiningJobDraft` is always `NON_CANONICAL`, `DRAFT`, and `started=False`.
- `AlphaMiningUserJobService` accepts only a resolved explicit USER authorization
  issued by the existing V3 Control Plane and bound to the exact JobSpec. An
  injected Control Plane persistence port must independently resolve it before
  resource admission; the typed token alone grants no authority.
- Resource admission/release uses the existing `ResourceGovernor`.
- Production W0 ResearchLoop actions remain `NOT_RUN`; S adds no Agent L2 action.
- `AlphaMiningRunRecord.factor_asset_lifecycle_transition` is always `NOT_RUN`.
  S never calls REVIEWED, PROMOTED, publication, Truth or Admission elevation.

## Acceptance coverage

The `round5_s_alpha_mining` suite covers all required behaviors:

1. stable JobSpec identity;
2. stable candidate order for the same seed/search space;
3. candidate count bound;
4. expression depth and node bounds;
5. evaluation count bound;
6. LEAD/future operator rejection;
7. unresolved/unsupported data rejection;
8. arbitrary Python source rejection;
9. NON_CANONICAL/DRAFT candidates;
10. canonical `FactorDefinitionVersion` creation;
11. invalid IR rejection before evaluation;
12. canonical identity dedup;
13. existing evaluator-only math;
14. exact evaluation context rejection tests;
15. exact evidence reward input;
16. explicit missing reward component;
17. deterministic complexity penalty;
18. blocking Reviewer handling;
19. no promotion;
20. Agent draft cannot start;
21. explicit user job stops truthfully at budget;
22. production ResearchLoop remains `NOT_RUN`;
23. deterministic non-LLM mode;
24. truthful rejected/deduplicated/evaluated lineage.

`scripts/backend-foundation-test.mjs` adds only this S test directory to the
existing public validation harness. That one-line suite registration is the sole
`SHARED_INTEGRATION_PATH`; no router, dependency manifest or lockfile changes.
