# Round 5 W0 Agent Research Loop Contract

## Authority boundary

The W0 loop is an immutable coordination contract, not a new execution, financial Truth, Admission, review, reward, or publication authority.

- `AgentResearchProposal`, `ResearchActionDraft`, and `NextActionProposal` are always `NON_CANONICAL / DRAFT`; actions remain `NOT_RUN` until an existing V3 Control Plane authorization receipt exists.
- A directly constructed `ExecutionReceiptRef` is explicitly `UNRESOLVED_REF`; even the string `V3_CONTROL_PLANE` is not proof and cannot complete an iteration.
- The production `ResearchExecutionEvidenceResolver` is a W0-owned thin adapter over `TaskPersistencePort`. Callers provide only IDs; the adapter re-reads `Task`, `Run`, and `TaskAttempt` inside one persistence unit-of-work and rejects missing, mismatched, or non-successful owner state. Directly constructed domain objects are not an authority input.
- Current Control Plane persistence records `operation_id` and `RunIdentity.normalized_input_hash`, but it does not own an exact `ResearchActionDraft.action_draft_id` or a canonical accepted-input envelope that can be recomputed from the draft. Matching `requested_capability == operation_id` is necessary but insufficient. A successful persisted lifecycle therefore yields only `PERSISTED_TASK_OBSERVED_BUT_ACTION_BINDING_UNRESOLVED`, never `RESOLVED_OWNER_REF`.
- `ResearchLoopIterationRecord` stores exact proposal, action, receipt, canonical output, ReviewerReport, RewardVector, budget-consumption, and next-action refs. It does not recompute any of them.
- `ResearchSemanticEvidenceValidator` retains content-identity and exact cross-binding checks for actual `ExperimentRun`, successful `ExperimentAttempt`, `ReviewerEvidence`, `ResearchReviewReport`, and `RewardVector`. This is content-addressed semantic evidence, not persisted Control Plane execution evidence.
- Because the exact action-to-persisted-accepted-input binding is absent, production `COMPLETE` is `NOT_AVAILABLE / NOT_RUN` in W0 and fails closed with `RESEARCH_ACTION_EXECUTION_BINDING_NOT_AVAILABLE`. Raw review/reward strings, content-addressed evidence, terminal fields, valid IDs, matching capability, or a test fixture cannot upgrade it. `PROPOSED`, `PARTIALLY_EXECUTED`, `REVIEWED`, and `BLOCKED` remain truthful history states.
- Existing Agent Workspace permissions remain unchanged: L0 read and L1 draft are available; L2 execute and L3 publish remain denied to agents.

## Closed action vocabulary

`FACTOR_DRAFT_CREATE`, `FACTOR_IMPORT`, `FACTOR_EVALUATE`, `MODEL_TRAIN`, `MODEL_PREDICT`, `PORTFOLIO_CONSTRUCT`, `RISK_APPLY`, `BACKTEST_RUN`, `REVIEW_RUN`, `EVIDENCE_QUERY`, and `RESULT_COMPARE` are the only W0 action types. Unknown actions fail with `UNSUPPORTED_RESEARCH_ACTION`.

## Budget and identity

`ResearchLoopBudgetVersion` is content-addressed and contains explicit iteration, action, candidate, experiment, model-call, optional wall-clock, and resource-profile bounds. Unlimited is the explicit `UNLIMITED_EXPLICIT` token; `0` and `-1` are not magic values. Exceeding any bound raises `RESEARCH_BUDGET_EXCEEDED`.

IDs are derived only from canonical contract content. Wall-clock observation time, random UUIDs, storage paths, and database row IDs are not authority inputs.

## W0 status

The persistence lifecycle test fixture is explicitly `TEST_ONLY_PERSISTED_CONTROL_PLANE_FIXTURE` and uses `InMemoryTaskPersistence -> TaskSupervisor.accept -> persisted transitions -> finalize_run -> resolver re-read`. It proves the owner read path, not action admission. Autonomous loops, production execution completion, product permission changes, promotion, publication, and waiver are `NOT_RUN` and belong to later authorized L2 integration work.
