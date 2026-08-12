# Round 5 R Portfolio/Risk Agent — Reuse Adoption Matrix

Date: 2026-08-13. Base: `f2cd80ee377d213a1bc1e78fb9812d2192b10cf9` (frozen Round 5 W0 merge).

R does not add a second portfolio-construction, risk, backtest, analytics, reviewer,
identity, provenance, admission, or permission authority. R composes existing canonical
H/I/J/Result/Reviewer owners through exact public objects and adds L0/L1 Agent seams only.
Context7 was requested by repository instructions but no Context7 MCP tool was available in
this session (`NOT_AVAILABLE`); the bounded refresh below uses repository pins plus
PyPI/upstream metadata evidence fetched 2026-08-13.

## Inventory of current V3 runtime (inspection first)

| Canonical owner | Module | Reused by R as |
|---|---|---|
| H — Portfolio construction | `domain/portfolio_construction` `DeterministicPortfolioConstruction.construct` | `PORTFOLIO_CONSTRUCT` scenario draft + user-confirm application seam |
| W0 weight seam | `domain/weights` `TargetWeightVector` / `RiskAdjustedWeightVector` / `RuntimeIdentity` / `UnresolvedExactReference` | exact evidence projections; R never mints rows |
| I — Risk runtime | `domain/risk_runtime` `apply_risk`, `RiskPolicyDefinition`, `RiskPolicySetVersion`, `RiskStateInput` | `RISK_APPLY` scenario draft + user-confirm application seam |
| J — A-share backtest | `domain/backtest_runtime` `DeterministicAshareBacktestEngine.run`, `BacktestRunSpec`, `CostPolicyVersion`, A-share rule/timing profiles | `BACKTEST_RUN` scenario draft + user-confirm application seam |
| Result analytics | `domain/result_analytics` `DeterministicResultAnalyticsEngine.analyze` | exact analytics projection for `RESULT_COMPARE` |
| Reviewer | `domain/reviewer_integration` `review_research_scope`, `ResearchReviewScope`, `V0_REVIEWER_RULE_SET_ID` | `REVIEW_RUN` draft and evidence-bound explanation |
| Agent framework | `agents/contracts` `ProposalBoundary`/`StrictAgentModel`, `agents/permissions` L0/L1, `agents/pydantic_worker` | thin PydanticAI adapter (same pattern as P/Q) |

## Naming note (frozen-base mapping)

The R task text references `RiskModelVersion`. The frozen base has no `RiskModelVersion`
class; the canonical risk-model identity is `RiskPolicySetVersion` plus the exact
`(backend, code_version, runtime_profile_id)` triple its policies share
(`RISK_V0_BACKEND = "v3-native-decimal"`). R therefore treats "exact RiskModelVersion
identity" as **exact `RiskPolicySetVersion` binding** and fails closed on any
unknown/stale/mismatched policy set, backend, code version, or runtime profile.

## Adoption decisions

| Candidate | Exact version / revision | License / maintenance | Windows + current Python | Determinism, tests, dependency cost | Authority risk | Decision |
|---|---|---|---|---|---|---|
| Existing V3 H/I/J/Result/Reviewer runtimes | frozen base `f2cd80ee377d213a1bc1e78fb9812d2192b10cf9` | Apache-2.0 repository; existing regression suites (track_h, round3_track_i, track_j, track_l, reviewer_integration) | Repo runtime authority documents CPython 3.14 closure | Content-addressed identities, exact bindings, closed enums, deterministic tests; zero new dependency | Already canonical owners; R must only compose their public objects | **DIRECT_REUSE** |
| Existing Agent framework + PydanticAI Slim | repository pin `pydantic-ai-slim==2.27.0` (`PYDANTIC_AI_VERIFIED_VERSION`) | MIT; active; already in backend closure | Pure Python, current backend closure | Existing strict structured-output, permission and failure tests; no new dependency | Model output cannot own permission, evidence, IDs, execution, weights, or truth | **DIRECT_REUSE / THIN_ADAPTER** seam only |
| Riskfolio-Lib | `riskfolio-lib==7.3.0` (PyPI metadata 2026-08-13) | BSD-3-Clause; active | `requires_python >=3.10`; not part of V3 backend closure | Broad solver/estimator surface; large dependency closure (cvxpy/estimators); would need new admission + parity suite | Would create a second portfolio/risk representation and a parallel optimizer authority | **REJECT** for R; no dependency or runtime adapter |
| PyPortfolioOpt | `PyPortfolioOpt==1.6.0` (PyPI metadata 2026-08-13) | MIT; mature | Pure Python but not in V3 closure; EF/EfficientFrontier optimizer | New admission and parity suite required | Second optimizer authority; V0 construction explicitly admits no external optimizer (`OPTIMIZER_NOT_CONFIGURED`) | **REJECT** for R; no dependency or runtime adapter |
| cvxpy / optimizer stack | `cvxpy==1.9.2` (PyPI metadata 2026-08-13) | Apache-2.0 upstream; active | `requires_python >=3.11`; native solver binaries on Windows | Large compiled dependency; determinism of solver backends not pinned in V3 | Second optimization authority; no V3 construction seam exists to host it | **REJECT** for R; no dependency or runtime adapter |
| Qlib portfolio/execution ideas | `pyqlib==0.9.7`; `microsoft/qlib@79633dd9506ea689e5400dea0197717b5b3d74b7` (merged Track E evidence) | MIT; active; classified REFERENCE in the merged Track E adoption report | Windows through CPython 3.12 only (merged Track E evidence) | Already classified in the merged Track E report: REFERENCE, reject as V0 direct dependency | Qlib execution/portfolio objects cannot replace V3 authorities | **REFERENCE** only; no dependency or runtime adapter |

## Frozen R design

- L0 read tools are pure projections over exact caller-supplied canonical objects
  (`PortfolioIntentSource`, `TargetWeightVector`, `RiskPolicySetVersion`,
  `RiskAdjustedWeightVector`, `CostPolicyVersion`, `BacktestRunResult`,
  `BacktestResultAnalytics`, `ResearchReviewReport`). Unknown/mismatched identity fails closed.
- L1 drafts are closed `NON_CANONICAL` / `DRAFT` Pydantic objects at `L1_DRAFT`
  (`PORTFOLIO_CONSTRUCT`, `RISK_APPLY`, `BACKTEST_RUN`, `RESULT_COMPARE`, `REVIEW_RUN`).
- Scenario drafts bind only **existing canonical object identities**: construction spec
  version ref, risk policy set version, cost policy version, rule/timing profile, exact
  weight vectors, engine version. R has no free-form numeric knobs; parameters the current
  deterministic runtime cannot enforce (sector/industry bounds, turnover budgets,
  optimizer/objective selection, shorting, leverage, fractional lots) are rejected as
  unsupported rather than shadow-computed.
- A-share semantics are inherited from the J engine and never waived: T+1 sellable,
  buy-lot rounding, limit-up/down blocks, suspended/ST blocks, explicit costs. Drafts carry
  no field that could enable shorting or leverage; `extra="forbid"` closes the wire shape.
- Comparison is deterministic only for an exact context key
  (intent + construction spec + risk policy set + cost policy + timing/universe binding).
  Any mismatch returns `INCOMPARABLE_CONTEXT` with the exact differing fields; no ranking.
  Missing metrics remain `NOT_RUN` / `NOT_AVAILABLE`; no zero fill.
- Agent text never produces `TargetWeightVector`, `RiskAdjustedWeightVector`,
  `RiskModelVersion`, `CostPolicyVersion`, analytics, or causal/exposure claims. The
  user-confirm application seam (`apply_confirmed_*`) requires an exact draft hash,
  `agent_issued=False`, and re-verifies every canonical binding before calling the
  deterministic owner.
- Production ResearchLoop `COMPLETE` remains `NOT_AVAILABLE / NOT_RUN`.

## Sources

All sources are from the frozen W0 base `f2cd80ee377d213a1bc1e78fb9812d2192b10cf9`
(implementations already merged into main) plus PyPI metadata fetched 2026-08-13.
No unmerged sibling branch or worktree residue was used as reference.

- Existing H report: `docs/portfolio-construction-runtime-v0/RUNTIME_CONTRACT.md`
- Existing J report: `docs/research/a-share-backtest-core/V0_ENGINE_SEMANTICS.md`
- Existing merged Track E reuse report (Qlib/LightGBM/XGBoost classification): `docs/research/model-prediction-runtime-v0/REUSE_ADOPTION_REPORT.md`
- W0 owner matrix: `docs/research/round5-w0/ROUND5_PARALLEL_OWNER_MATRIX.md`
- Merged agent-framework pattern provenance (frozen base): `apps/backend/src/v3_backend/agents/research_evidence_integration/{contracts,tools,worker}.py` (exact-object L0 read tools with allowed-call trace and fail-closed binding) and `apps/backend/src/v3_backend/agents/generative_research_view/models.py` (StrictAgentModel closed wire shapes)
- [Riskfolio-Lib 7.3.0 package metadata](https://pypi.org/project/riskfolio-lib/)
- [PyPortfolioOpt 1.6.0 package metadata](https://pypi.org/project/PyPortfolioOpt/)
- [cvxpy 1.9.2 package metadata](https://pypi.org/project/cvxpy/)
