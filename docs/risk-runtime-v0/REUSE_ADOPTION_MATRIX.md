# Risk Runtime V0 reuse and adoption matrix

Checked on 2026-08-11 for `V3-TRACK-I-RISK-RUNTIME-V0-01`. This is a bounded adoption gate, not a second implementation authority. V3's merged W0 seam and canonical truth lattice remain authoritative.

| Candidate | Current evidence | License / maintenance | Windows + CPython 3.14 | Determinism, PIT, identity and fallback fit | Decision |
|---|---|---|---|---|---|
| Merged W0 `domain.weights` seam | `TargetWeightVector`, receipt/stage evidence and `RiskAdjustedWeightVector` exist at base `f88b0ebe5af4733e46a00ab373ff61c159e82ff2`; 21 seam tests pass | In-repo Apache-2.0, current owner W0 | Exact canonical runtime | Already content-addressed, truth-bounded and fail-closed | **DIRECT_DEPENDENCY** — import and call without modification |
| Accepted V3 target/risk research | Pinned LEAN, skfolio and Qlib boundary analysis under `docs/research/target-weight-portfolio-risk-reference/` | In-repo Apache-2.0 documentation; upstream licenses recorded | Runtime-neutral | Reference only; no copied runtime authority | **REFERENCE** |
| [Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | Current repository describes portfolio/risk optimization, CVXPY solvers, Python 3.9+ and a broad numerical dependency graph | BSD-3-Clause; active | Declared Python range includes 3.14, but exact Windows/native dependency closure is not canonical V3 | Solver/backend state does not provide V3 ordered identity, PIT bindings, typed no-fallback semantics or publication authority | **REJECT** as core dependency; future **ISOLATED_WORKER_API_CLI** candidate |
| [skfolio](https://github.com/skfolio/skfolio) | Current repository provides optimization, constraints, risk measures and sklearn-style validation with numpy/scipy/pandas/cvxpy/clarabel/scikit-learn | BSD-3-Clause; active | Python >=3.10 declared; exact Windows 3.14 closure must be pinned per worker | Optimizer objects/weights are not canonical artifacts; solver/fallback and data-leakage controls require separate evidence | **REFERENCE** now; future **ISOLATED_WORKER_API_CLI** candidate |
| [PyPortfolioOpt 1.6.0](https://pypi.org/project/pyportfolioopt/1.6.0/) | Mean-variance, Black-Litterman, shrinkage, HRP, objectives and constraints; Python 3.10-3.14 classifiers | MIT; maintained 2026 release | CPython 3.14 declared | Does not own V3 target identity, policy ordering, state PIT, truth lattice or W0 publication | **REJECT** as V0 dependency; future **ISOLATED_WORKER_API_CLI** candidate |
| [CVXPY 1.9.2](https://pypi.org/project/cvxpy/) | Convex modeling with Clarabel, OSQP, SCS and HiGHS dependencies | Apache-2.0; active | Official Windows CPython 3.14 wheel observed | Solver choice/status/tolerances and packages must be exact evidence; result cannot mint canonical output | **ISOLATED_WORKER_API_CLI** only; not used in V0 core |
| [SciPy 1.18.0](https://pypi.org/project/scipy/) `optimize` | General optimization algorithms; production/stable | BSD; active | Official Windows CPython 3.14 wheels observed | Result depends on algorithm, tolerances, native runtime and starting state; no V3 provenance or authority | **ISOLATED_WORKER_API_CLI** only; not used in V0 core |
| [LEAN Risk Management](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/risk-management/supported-models) | Risk receives portfolio targets before Execution; an explicit null model leaves targets unchanged | LEAN Apache-2.0; active | Python algorithm surface targets Python 3.11, not V3 canonical 3.14 | Strong stage-boundary reference, but operational targets are not durable V3 identities and models may depend on live state | **REFERENCE** — adopt boundary, reject contract/runtime reuse |

## Adoption decision

V0 uses a small V3-native, standard-library `Decimal` policy algebra because higher-priority reuse choices do not satisfy the combined invariants:

- accept the actual canonical W0 object and recompute its identity;
- preserve immutable source lineage and publish only through the W0 seam;
- make policy order and every parameter/state binding identity-bearing;
- emit complete deterministic stage evidence;
- fail closed with typed rejection and never translate errors into cash, prior weights or implicit pass-through;
- propagate the weakest truth ceiling;
- avoid a second canonical authority or a large solver graph for three simple rules.

No third-party implementation is copied or vendored. Complex optimization stays outside canonical core behind a future isolated worker contract whose candidate cannot assign canonical identity or truth.
