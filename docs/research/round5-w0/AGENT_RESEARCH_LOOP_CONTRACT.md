# Round 5 W0 Agent Research Loop Contract

## Authority boundary

The W0 loop is an immutable coordination contract, not a new execution, financial Truth, Admission, review, reward, or publication authority.

- `AgentResearchProposal`, `ResearchActionDraft`, and `NextActionProposal` are always `NON_CANONICAL / DRAFT`; actions remain `NOT_RUN` until an existing V3 Control Plane authorization receipt exists.
- A directly constructed `ExecutionReceiptRef` is explicitly `UNRESOLVED_REF`; even the string `V3_CONTROL_PLANE` is not proof and cannot complete an iteration.
- `ResearchExecutionEvidenceResolver` is a W0-owned thin resolver. It accepts actual current-main `Task`, `Run`, and `TaskAttempt` objects, requires their exact bindings and terminal-success states, and derives an action-bound `RESOLVED_OWNER_REF`. It does not replace or modify the Control Plane owner.
- `ResearchLoopIterationRecord` stores exact proposal, action, receipt, canonical output, ReviewerReport, RewardVector, budget-consumption, and next-action refs. It does not recompute any of them.
- `COMPLETE` requires a `ResolvedResearchCompletionEvidence` bundle built from exact action-bound executions plus actual `ExperimentRun`, successful `ExperimentAttempt`, `ReviewerEvidence`, `ResearchReviewReport`, and `RewardVector`. The report must resolve all four owner objects, and the reward must bind the same run/attempt/reviewer evidence. Raw review/reward strings are ignored as completion authority.
- Existing Agent Workspace permissions remain unchanged: L0 read and L1 draft are available; L2 execute and L3 publish remain denied to agents.

## Closed action vocabulary

`FACTOR_DRAFT_CREATE`, `FACTOR_IMPORT`, `FACTOR_EVALUATE`, `MODEL_TRAIN`, `MODEL_PREDICT`, `PORTFOLIO_CONSTRUCT`, `RISK_APPLY`, `BACKTEST_RUN`, `REVIEW_RUN`, `EVIDENCE_QUERY`, and `RESULT_COMPARE` are the only W0 action types. Unknown actions fail with `UNSUPPORTED_RESEARCH_ACTION`.

## Budget and identity

`ResearchLoopBudgetVersion` is content-addressed and contains explicit iteration, action, candidate, experiment, model-call, optional wall-clock, and resource-profile bounds. Unlimited is the explicit `UNLIMITED_EXPLICIT` token; `0` and `-1` are not magic values. Exceeding any bound raises `RESEARCH_BUDGET_EXCEEDED`.

IDs are derived only from canonical contract content. Wall-clock observation time, random UUIDs, storage paths, and database row IDs are not authority inputs.

## W0 status

The contract and deterministic test fixtures are implemented. Autonomous loops, product permission changes, live execution orchestration, promotion, publication, and waiver are `NOT_RUN` and belong to later Round 5 tracks.
