# Round 5 S Bounded Alpha Mining and Research-Loop Contract

Task: `V3-ROUND5-S-ALPHA-MINING-01`

Original base: `eda009b601b681c8a26d2a98a1093b3e6f33245e`

CURRENT main merged for the runnability correction:
`d975c06382b15323176891dbe29347d516edb62f`

## Authority path

Production user-start is deliberately unavailable on current main:

```text
untrusted caller / USER claim / Agent draft / fake persistence object
  -> USER_EXECUTION_AUTHORITY_NOT_AVAILABLE
  -> NOT_AVAILABLE / NOT_RUN
  -> STOP before ResourceGovernor, engine.run, candidates, evaluation or reward
```

Current main has no accepted shared canonical user-action/approval authority that
can authorize production Alpha Mining. S does not create that authority. A
future production start requires a separately designed and accepted shared
Control Plane user-action authority.

The deterministic domain path remains available to unit tests, bounded domain
tests, benchmarks and explicitly non-production test harnesses:

```text
AlphaMiningJobSpec
  -> deterministic closed grammar
  -> MiningFactorCandidate (NON_CANONICAL / DRAFT)
  -> existing Canonical Factor IR validation
  -> existing FactorDefinitionVersion
  -> ExistingFactorEvaluationPort
  -> exact FactorEvaluation + Experiment Run/Attempt + ReviewerEvidence + RewardVector
  -> AlphaMiningRewardPolicyVersion projection
  -> AlphaMiningRunRecord
```

The backend research entry added by the runnability correction is:

```text
AlphaResearchLoopService.run(AlphaMiningJobSpec)
  -> canonical FormalDatasetVersion owner
  -> P1 resolve and verify Dataset actual bytes
  -> strict canonical Dataset sample decoder
  -> deterministic candidate generation
  -> existing FactorDefinitionVersion and sole FormalFactorEvaluationService
  -> P1 resolve and verify FeatureMaterialization actual bytes
  -> V3 compute_reward_metrics(IC, RankIC, quantile returns, turnover, coverage)
  -> registered Reviewer review_research_scope
  -> ExperimentRun / ExperimentAttempt / ExperimentResult + RewardVector
  -> scored reward feedback into the next deterministic generation
  -> existing Artifact Store result publication
```

`run` accepts only the canonical job. It has no caller metric, caller Reviewer
PASS, caller RewardVector or caller evaluation-evidence argument. Dataset and
Feature bytes are resolved through the one P1 `CanonicalPayloadResolver`; the
path creates neither another resolver nor another Artifact Store.

The original injectable engine port remains for bounded contract tests. The
runnable backend adapter never accepts caller evidence: it binds generated IR to
the existing Formal Factor service, and rejects evidence unless
FactorDefinitionVersion, FactorEvaluation context, Dataset actual bytes,
FeatureMaterialization actual bytes, Experiment Run/Attempt, Reviewer evidence,
RewardVector, complexity, period, label, horizon, evaluation policy and cost
context all match the exact job.

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

For the runnable adapter these components are computed from the exact joined
FeatureMaterialization and Dataset sample coordinates by V3
`compute_reward_metrics`; caller summaries are not an authority seam. The
current deterministic fixture exercises IC, RankIC, quantile return/spread,
turnover, coverage and complexity. The highest scored earlier-generation reward
ID is incorporated into the next generation's canonical source lineage and
generation token.

## User / Agent / promotion boundaries

- `AlphaMiningJobDraft` is always `NON_CANONICAL`, `DRAFT`, and `started=False`.
- Production user-started Alpha Mining is `NOT_AVAILABLE / NOT_RUN` because
  current main has no shared canonical user-action/approval authority.
- `AlphaMiningUserJobService` rejects every caller DTO, actor string, claimed
  Control Plane issuer, fake persistence object and Agent draft with
  `USER_EXECUTION_AUTHORITY_NOT_AVAILABLE` before resource admission or engine
  execution. S defines no authorization DTO, authorization Protocol, local
  receipt, approval repository or persistence authority.
- The existing `ResourceGovernor` remains the resource mechanism for a future
  authorized runtime, but denied production starts never reach it.
- Agent L1 may create and validate a bounded draft. It cannot start the job,
  admit resources, run the engine, mint authority, publish or promote output.
- Direct deterministic domain-engine calls in tests do not represent production
  user execution authority.
- `AlphaResearchLoopService` is a backend research composition candidate. It is
  not wired to a production user-start endpoint, Task runtime or Agent L2 action.
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
20. Agent draft and caller-created USER claims cannot start;
21. production user-start fails closed before ResourceGovernor and engine;
22. production ResearchLoop remains `NOT_RUN`;
23. deterministic non-LLM mode;
24. truthful rejected/deduplicated/evaluated lineage.
25. strict Dataset actual-byte decoding and altered-byte rejection through P1;
26. actual FeatureMaterialization byte resolution through P1;
27. V3-computed IC, RankIC, returns, turnover and coverage;
28. no caller metrics or caller PASS evidence in the runnable entry;
29. scored reward feedback changes the next generation lineage;
30. content-deterministic replay and Artifact reproduction.

`scripts/backend-foundation-test.mjs` retains this S test directory in the
existing public validation harness. `scripts/alpha-research-smoke.mjs` is a
bounded backend smoke wrapper. There is no router, Desktop, dependency manifest,
lockfile, Model, Data Quality or Core Research Pipeline change.
