# Round 5 W0 Agent Research Loop Contract

## Authority boundary

The W0 loop is an immutable coordination contract, not a new execution, financial Truth, Admission, review, reward, or publication authority.

- `AgentResearchProposal`, `ResearchActionDraft`, and `NextActionProposal` are always `NON_CANONICAL / DRAFT`; actions remain `NOT_RUN` until an existing V3 Control Plane authorization receipt exists.
- `ExecutionReceiptRef` can only reference receipts issued by `V3_CONTROL_PLANE` and binds existing Task / Run / Attempt identifiers. It does not mint them.
- `ResearchLoopIterationRecord` stores exact proposal, action, receipt, canonical output, ReviewerReport, RewardVector, budget-consumption, and next-action refs. It does not recompute any of them.
- `COMPLETE` requires one unique execution receipt per requested action plus exact ReviewerReport and RewardVector refs. `NOT_RUN`, `BLOCKED`, and incomplete history cannot be inferred as complete.
- Existing Agent Workspace permissions remain unchanged: L0 read and L1 draft are available; L2 execute and L3 publish remain denied to agents.

## Closed action vocabulary

`FACTOR_DRAFT_CREATE`, `FACTOR_IMPORT`, `FACTOR_EVALUATE`, `MODEL_TRAIN`, `MODEL_PREDICT`, `PORTFOLIO_CONSTRUCT`, `RISK_APPLY`, `BACKTEST_RUN`, `REVIEW_RUN`, `EVIDENCE_QUERY`, and `RESULT_COMPARE` are the only W0 action types. Unknown actions fail with `UNSUPPORTED_RESEARCH_ACTION`.

## Budget and identity

`ResearchLoopBudgetVersion` is content-addressed and contains explicit iteration, action, candidate, experiment, model-call, optional wall-clock, and resource-profile bounds. Unlimited is the explicit `UNLIMITED_EXPLICIT` token; `0` and `-1` are not magic values. Exceeding any bound raises `RESEARCH_BUDGET_EXCEEDED`.

IDs are derived only from canonical contract content. Wall-clock observation time, random UUIDs, storage paths, and database row IDs are not authority inputs.

## W0 status

The contract and deterministic test fixtures are implemented. Autonomous loops, product permission changes, live execution orchestration, promotion, publication, and waiver are `NOT_RUN` and belong to later Round 5 tracks.
