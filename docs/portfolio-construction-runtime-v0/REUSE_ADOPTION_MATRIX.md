# Portfolio Construction Runtime V0 reuse and adoption matrix

Status date: 2026-08-11. The scan used current official project documentation,
PyPI release metadata, official repositories, and the existing pinned V3
portfolio/risk research under `docs/research/target-weight-portfolio-risk-reference/`.
Context7 was required by repository instructions but was not callable in this
session; no undocumented API behavior was assumed.

## Decision

V0 uses a V3-native deterministic Decimal baseline and introduces no optimizer
dependency. Mature libraries remain useful references, but none owns the exact
W0 `PortfolioIntentSource` admission, V3 content identity, truth ceiling,
canonical 12-place residual allocation, typed fail-closed rejection, or sole
`TargetWeightVector` publisher boundary. Reusing their allocator output directly
would create a second authority and would still require a V3 reimplementation of
every admission invariant.

| Candidate | Current evidence | Functional coverage | License / maintenance / tests | Windows / Python 3.14 | Determinism and performance | PIT, identity, provenance, fallback and authority | V0 disposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [skfolio 0.20.1](https://pypi.org/project/skfolio/) | Released 2026-04-21; official docs expose `EqualWeighted` plus solver-backed portfolio optimization | Broad allocation, risk and model-selection coverage | BSD-3-Clause; active releases; documented estimator/test ecosystem | OS-independent wheel and Python >=3.10, but PyPI classifiers do not explicitly claim 3.14 | Equal weight is simple; advanced paths bring NumPy/pandas/scikit-learn/CVXPY/Clarabel and solver settings | No V3 exact-source admission, canonical artifact identity, truth lattice or publisher boundary; fallback is library policy | `REFERENCE` |
| [Riskfolio-Lib 7.3.0](https://pypi.org/project/riskfolio-lib/) | Released 2026-05-31; 26+ convex risk measures and multiple solver families | Very broad optimization, risk parity, clustering and constraints | BSD-3-Clause; current release; large dependency graph and solver matrix | Explicit CPython 3.14 Windows wheel | Powerful but far beyond a deterministic source-only baseline; numerical/solver status must be isolated and revalidated | Requires CVXPY and many financial/statistical dependencies; cannot assign V3 identity or truth and risks a second policy authority | `REJECT` |
| [PyPortfolioOpt 1.6.0](https://pypi.org/project/pyportfolioopt/) | Released 2026-02-26; mean-variance, Black-Litterman, shrinkage and HRP | Mature research/prototyping optimizer coverage | MIT; maintained since 2018; tests and release attestation visible | Explicit Python 3.14 classifier; OS independent | Solver/covariance/return inputs are unnecessary for V0 equal or desired-exposure normalization | Does not consume W0 objects or preserve V3 identity/truth; direct use would silently add estimator semantics | `REFERENCE` |
| [SciPy optimize 1.18.0](https://pypi.org/project/scipy/) | Released 2026-06-19; official docs expose constrained local/global solvers and typed results | General numerical optimization, not a portfolio domain contract | BSD; production/stable; mature tests and maintainers | Explicit CPython 3.14 Windows wheel | Determinism depends on method, tolerances, initial state and numerical platform; unnecessary overhead for V0 | No finance/PIT semantics, identity, provenance or V3 validation; future use must be an isolated candidate producer | `REFERENCE` |
| [CVXPY 1.9.2](https://pypi.org/project/cvxpy/) | Released 2026-06-22; convex DSL with multiple bundled/optional solvers | Strong convex constraint modeling | Apache-2.0; active community project | Explicit CPython 3.14 Windows wheel | Solver/backend/version/status/tolerance materially affect output; V0 does not need them | Solver success is not Target admission; direct dependency would add backend/fallback authority | `REFERENCE` |
| [FinRL-X / FinRL-Trading](https://github.com/AI4Finance-Foundation/FinRL-Trading) | 2026 weight-centric modular architecture; official repository | Stock selection, allocation, timing, risk overlays, backtest and execution | Apache-2.0; active research repository | Environment is broader than the bounded pure Python domain baseline | Weight-centric interface is a useful system design reference; RL/LLM paths are not a deterministic V0 baseline | Target/execution integration does not supply V3 exact source, PIT identity or truth admission and crosses wider owner boundaries | `REFERENCE` |
| Existing pinned LEAN/WonderTrader/Qlib research | In-repo exact-commit evidence already records target-vs-execution separation | Cross-domain architectural boundary evidence | Licenses and commits are recorded in the existing research matrix | Not adopted at runtime | Supports separating desired weights from order generation | Confirms that price, holdings, orders and fills stay downstream | `REFERENCE` |
| V3 Decimal baseline | Implemented in `domain/portfolio_construction` | Equal selected weights, normalized desired exposure, explicit cash, bounds and canonical residuals | Repository Apache-2.0; covered by Track H and full backend tests | Pure Python 3.14; no new dependency | Fixed 64-digit working precision, floor to 12 places, largest remainder, canonical ID tie-break | Directly consumes W0/Track F objects, publishes through W0 only, preserves PRE_ALPHA ceiling and never silently falls back | `V3_NATIVE_REQUIRED` |

## Adoption gate

- `DIRECT_DEPENDENCY`: none.
- `ADAPTER`: none in V0.
- `ISOLATED_WORKER_API_CLI`: boundary reserved for a future exact-version
  optimizer candidate, but no worker is enabled in V0.
- `SELECTIVE_MODULE_REUSE`: none; copying allocator code would add license and
  maintenance surface without satisfying the V3 seam.
- `REFERENCE`: skfolio, PyPortfolioOpt, SciPy, CVXPY, FinRL-X, and existing
  pinned architecture research.
- `REJECT`: Riskfolio-Lib as a V0 runtime dependency because its solver and
  transitive dependency surface is disproportionate to the required baseline.
- `V3_NATIVE_REQUIRED`: the bounded deterministic Decimal construction and V3
  admission layer.

An `OptimizerCandidate` records backend, version, objective, constraints hash,
tolerance, status, seed, rows and candidate content hash. It has no Target ID.
V0 rejects every optimizer candidate with a typed
`OPTIMIZER_NOT_CONFIGURED`; a future adopted worker must pass V3 revalidation
before W0 publication.
