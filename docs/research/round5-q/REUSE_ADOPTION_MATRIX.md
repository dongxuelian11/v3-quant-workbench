# Round 5 Q Model Agent — Reuse Adoption Matrix

Date: 2026-08-12. Base: `f2cd80ee377d213a1bc1e78fb9812d2192b10cf9`.

Q does not add a second ML orchestration, PIT, Dataset, ModelVersion, Prediction,
Experiment, Reviewer, identity, provenance, admission, permission, or publication
authority. Context7 was requested by repository instructions but no Context7 MCP
tool was available in this session (`NOT_AVAILABLE`); the bounded refresh below
uses repository pins plus official upstream/PyPI evidence.

| Candidate | Exact version/revision | License / maintenance | Windows and current Python | Determinism, tests, dependency cost | Authority risk | Decision |
|---|---|---|---|---|---|---|
| Existing V3 Dataset / Model / Experiment / Reviewer runtimes | frozen base `f2cd80ee377d213a1bc1e78fb9812d2192b10cf9` | Apache-2.0 repository; existing regression suites | Repo runtime authority documents CPython 3.14 closure | Content-addressed identities, exact bindings, closed enums, deterministic tests; zero new dependency | Already canonical owners; Q must only compose their public objects | **DIRECT_REUSE** |
| Existing scikit-learn isolated worker | `scikit-learn==1.9.0`, upstream source attestation `scikit-learn/scikit-learn@77def0ed6e3beab57244885d2a584470e96c103d`, protocol `v3.model-worker/2` | BSD-3-Clause; production/stable; released 2026-06-02 | Official CPython 3.11–3.14 Windows wheels, including x86-64 | Existing Ridge/SVD closed JSON worker, fixed seed/runtime/feature order and Track E tests; NumPy/SciPy cost already isolated | Candidate computation only; V3 creates requests, evidence, artifact and ModelVersion | **DIRECT_REUSE via existing isolated worker**; Q adds no estimator |
| PydanticAI Slim | repository pin `pydantic-ai-slim==2.27.0`; prior verified upstream `pydantic/pydantic-ai@0a42080ddb72d7e1610b7ba4ec449a9707c0734d` | MIT; active | Pure Python package in current backend closure | Existing strict structured-output, permission and failure tests; no new dependency | Model output cannot own permission, evidence, IDs, execution or truth | **THIN_ADAPTER seam only**; Q contracts reuse `StrictAgentModel` and deterministic hashing |
| Microsoft Qlib | `pyqlib==0.9.7`; `microsoft/qlib@79633dd9506ea689e5400dea0197717b5b3d74b7` | MIT; active release and broad tests, but classified Alpha | Official package evidence covers Windows through CPython 3.12, not current CPython 3.14 | Useful DatasetH/trainer/Recorder/PIT patterns; large dependency and configuration surface | Qlib Dataset/Recorder/model identities and PIT behavior cannot replace V3 authorities | **REFERENCE** only; no dependency or runtime adapter in Q |
| LightGBM | `4.7.0`, source SHA256 `f8e20f682c9aabd000bcf4a7ed8aa6f473c1adfecccae34ec24e823d156f4af0` | MIT; active release 2026-07-18 | Windows x86-64 wheel exists; no repo-verified current-Python worker fingerprint | Seed/thread/device controls need a new isolated-worker admission and parity suite; additional native binary | Would widen model family and artifact semantics beyond the existing Track E extension seam | **REJECT for Q**; future isolated-worker candidate only |
| XGBoost | `3.3.0`, Windows wheel SHA256 `b06057f6a018fc04e6b3e0c15568ca636b8151a5b5f333478e500fcaf4fc7594` | Apache-2.0; production/stable; active release 2026-06-17 | Python >=3.12; Windows x86-64 wheel | ~69.5 MB Windows wheel; seed/thread/device/model serialization require new closure | Same widening and artifact-authority risk as LightGBM | **REJECT for Q**; future isolated-worker candidate only |
| Optuna | `4.9.0` | MIT plus third-party notices; active release 2026-06-01 | Python >=3.9, OS-independent wheel | Search sampler/storage/pruning add state, attempts and resource policy; determinism needs explicit sampler seed and trial ordering | No current V3 tuning application seam; adding it would create parallel orchestration/Attempt authority | **REJECT** until a separate Adoption Gate and V3 Experiment-owned tuning contract exist |

## Frozen Q design

- Read tools are pure projections over exact caller-supplied canonical objects.
- Drafts are closed `NON_CANONICAL` / `DRAFT` Pydantic objects at `L1_DRAFT`.
- Dataset identity, label/horizon, ordered features/materializations, universe,
  snapshot, cutoff, split, Truth/PIT, ModelVersion, worker runtime, prediction,
  Experiment and Reviewer references remain exact bindings.
- Q reuses `SplitSpec.validate_for_label`, `TrainingSpecVersion.create`, and exact
  object membership/equality checks. It does not create a second PIT validator.
- Comparison is deterministic only for an exact context key. Any material
  mismatch returns `INCOMPARABLE_CONTEXT` and no ranking.
- Missing metrics/evidence remain `NOT_RUN` or `NOT_AVAILABLE`; no zero fill.
- No Q tool calls `train_model`, `predict_model`, tuning, Task creation,
  canonical ID allocation, admission, publication, or ResearchLoop completion.

## Sources

- Existing Track E report: `docs/research/model-prediction-runtime-v0/REUSE_ADOPTION_REPORT.md`
- Existing W0 report: `docs/research/round5-w0/REUSE_ADOPTION_MATRIX.md`
- [scikit-learn 1.9.0 package metadata](https://pypi.org/project/scikit-learn/1.9.0/)
- [Qlib 0.9.7 package metadata](https://pypi.org/project/pyqlib/)
- [LightGBM 4.7.0 package metadata](https://pypi.org/project/lightgbm/)
- [XGBoost 3.3.0 package metadata](https://pypi.org/project/xgboost/)
- [Optuna 4.9.0 package metadata](https://pypi.org/project/optuna/)
