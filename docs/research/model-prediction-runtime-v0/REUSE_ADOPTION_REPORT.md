# Track E Model Runtime Reuse / Adoption Report

## Scope and evidence date

This bounded scan was completed on 2026-08-11 for one deterministic local
research baseline. It is not a general model-family survey. V3 remains the
only authority for identity, truth/admission, DatasetVersion binding, artifact
validation, publication, and provenance.

Current sources checked:

- [Qlib 0.9.7 release](https://github.com/microsoft/qlib/releases/tag/v0.9.7),
  [package metadata](https://pypi.org/project/pyqlib/), and
  [current project metadata](https://github.com/microsoft/qlib/blob/main/pyproject.toml)
- [scikit-learn 1.9.0 release](https://github.com/scikit-learn/scikit-learn/releases/tag/1.9.0),
  [package metadata](https://pypi.org/project/scikit-learn/), and
  [model persistence guidance](https://scikit-learn.org/stable/model_persistence.html)
- [LightGBM 4.7.0 release](https://github.com/lightgbm-org/LightGBM/releases/tag/v4.7.0),
  [package metadata](https://pypi.org/project/lightgbm/), and
  [determinism parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html)
- [XGBoost 3.4.0 release](https://github.com/dmlc/xgboost/releases/tag/v3.4.0),
  [package metadata](https://pypi.org/project/xgboost/), and
  [model IO guidance](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html)

Repository activity and public CI surfaces were also checked through the
projects' GitHub repositories on the evidence date. All four projects were
active and unarchived. A project's CI success is maintenance evidence only;
it never grants V3 truth or admission.

## Adoption matrix

| Candidate | Coverage and maintenance | License / tests | Python 3.14 + Windows | Determinism and errors | Artifact / dependency / authority risk | Decision |
|---|---|---|---|---|---|---|
| Qlib 0.9.7 | Broad quant research stack; latest release 2025-08-15 and repository active in 2026 | MIT; large upstream test/workflow surface | Windows is classified, but published wheels stop at CPython 3.12; no CPython 3.14 wheel | Framework-level seeds, processors, recorders and optional model backends create a large reproducibility surface; some workflows permit warning/skip behavior | Heavy dependency graph includes MLflow, LightGBM, dill and joblib; provider/cache/recorder IDs and pickle-like artifacts create second-authority and unsafe-load risk | `REFERENCE`. Reject as V0 direct dependency. A future separate Python 3.12 worker may be evaluated independently. |
| scikit-learn 1.9.0 | Exact Ridge/SVD coverage for the chosen explainable baseline; production/stable and actively maintained | BSD-3-Clause; mature estimator and platform test suites | Official CPython 3.14 Windows x86-64/ARM64 wheels | Closed `Ridge(solver="svd")`; fixed feature order; single-thread environment; V0 rejects every missing/nonfinite value and every worker error | Moderate NumPy/SciPy dependency weight. Pickle/joblib/cloudpickle are explicitly unsafe and unsupported across versions, so V3 accepts only closed coefficient JSON and structured predictions | `ISOLATED_WORKER_API_CLI`. Selected worker backend. |
| LightGBM 4.7.0 | Mature boosted-tree backend; released 2026-07-18 and actively maintained | MIT; extensive native/Python CI | Python 3.14 classifier and Windows x86-64 wheel | CPU `deterministic=true` plus forced row/column histogram mode is available, but compiler, thread, seed and device surfaces remain wider than Ridge | Native binary and broader missing/GPU behavior add weight; native model format would remain worker-opaque and require extra validation | `REFERENCE` for V0; future isolated worker only. |
| XGBoost 3.4.0 | Mature boosted-tree backend; released 2026-08-04 and actively maintained | Apache-2.0; extensive cross-platform CI | Python >=3.12 and Windows CPython 3.14 wheels | Seed/thread/device/tree-method controls are available, but CPU/GPU and booster options exceed the first baseline | JSON/UBJSON model IO is safer than pickle and useful design evidence, but official guidance still requires loading only producer-generated model JSON; dependency/runtime surface remains unnecessary | `REFERENCE` for V0; future isolated worker only. |
| V3 canonical model domain `track-e-v0/1` | Owns the missing contract, validation and publication boundary | Apache-2.0; Track E mutation and end-to-end tests | Standard-library core on the repository's CPython 3.14 authority | Canonical JSON, exact row/schema checks, explicit failure, no ambient clock, and truth meet rules | No external ID, recorder, cache or model object becomes authority | `V3_NATIVE_REQUIRED` for identity, truth, leakage, safe artifact validation and provenance. |

## Selected dependency closure

The process-isolated worker rejects any version drift from its reported
fingerprint. The repository pins the tested closure:

```text
scikit-learn==1.9.0
numpy==2.5.2
scipy==1.18.0
joblib==1.5.3
threadpoolctl==3.6.0
narwhals==2.24.0
```

The worker also reports the exact CPython version, OS/platform string,
protocol version, backend version, and the four single-thread environment
limits. This descriptor is hashed into `TrainingSpecVersion`, `ModelRun`, and
`ModelVersion`. No floating version or display name is used as identity.

## Why the selected reuse is not a direct canonical dependency

scikit-learn performs bounded numeric fitting inside a subprocess. It cannot:

- select or resolve DatasetVersion, rows, label, split, feature order, or truth;
- assign TrainingSpecVersion, ModelRun, ModelVersion, PredictionArtifact, or
  evidence identity;
- load a pickle/joblib model into V3 Core;
- silently impute, drop, reorder, retry, or switch backend;
- emit SignalArtifact, Strategy interpretation, or Portfolio intent.

The worker returns a candidate coefficient vector and candidate prediction
rows. V3 Core validates the closed response, rebuilds a canonical safe JSON
artifact, computes all IDs, propagates truth ceilings, and publishes only
validated raw prediction values.

## Deferred candidates

LightGBM and XGBoost require separate adoption tasks for parameter allow-lists,
CPU/GPU equivalence, native model format validation, missing-value semantics,
compiler/runtime fingerprints, and resource isolation. Qlib additionally needs
a separate supported Python environment and explicit removal of provider,
recorder, cache, pickle and signal authority. None is silently substituted when
the selected Ridge worker fails.
