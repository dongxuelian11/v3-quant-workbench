# Model / Prediction Runtime V0

## Owner boundary

Track E owns the raw model chain only:

```text
DatasetVersion
-> TrainingSpecVersion
-> process-isolated model worker candidate
-> V3 safe model artifact
-> ModelVersion
-> PredictionArtifact
-> ModelEvaluationEvidence
```

Track E does not define or publish SignalArtifact, Strategy IR,
PortfolioIntent, Portfolio/Risk, Backtest, or trading-return metrics.

The current `ModelService.v1.generatePredictionSignals` ASL name and its
`PredictionSignalVersion` terminology are a bounded legacy incompatibility.
This runtime does not consume that combined semantic boundary and does not
modify the generated ASL. Raw prediction remains a distinct Track E artifact;
Track F must own any later interpretation, calibration, ranking, thresholding,
resampling, or intent emission.

Track C V0 currently identifies FeatureSetVersion from exact FactorEvaluation
IDs rather than stable definition-level output schema entries. Track E does not
replace that owner. For this first vertical slice, TrainingSpecVersion consumes
the exact ordered FactorEvaluation IDs already published by DatasetVersion, and
prediction is limited to a DatasetVersion with the same exact FeatureSet and
evaluation bindings (including the held-out TEST split of the training
DatasetVersion). Cross-DatasetVersion inference needs a future Track C-owned
stable feature-schema compatibility contract; Track E does not create a shadow
schema authority.

## Canonical identities

### TrainingSpecVersion

The immutable identity includes:

- admitted algorithm family and closed hyperparameters;
- ordered feature column IDs and dtypes, which must exactly equal the consumed
  DatasetVersion's canonical ordered FactorEvaluation IDs;
- exact FeatureSetVersion and FactorEvaluation references;
- exact LabelSpec and SplitSpec IDs;
- fixed TRAIN and VALIDATION split references;
- seed and environment profile;
- exact worker dependency/runtime fingerprint;
- explicit `REJECT` missing-value policy.

### ModelTrainingBinding and ModelRun

The binding consumes the exact DatasetVersion and TrainingSpecVersion, code
version, worker protocol/backend/package/platform/thread fingerprint, seed, and
the DatasetVersion truth ceiling. ModelRun adds exact ordered TRAIN and
VALIDATION row-set hashes. Retry/attempt timing is deliberately absent from the
semantic identity.

### ModelVersion

ModelVersion binds the exact DatasetVersion, ModelRun, TrainingSpecVersion,
V3 safe model artifact ID/media type, ordered feature schema fingerprint,
worker runtime, seed, training evidence, provenance artifact and propagated
truth/admission state. A worker response containing a canonical model ID is
rejected as an unknown field.

### PredictionArtifact

PredictionArtifact binds the exact ModelVersion, prediction DatasetVersion,
canonical sample row set, instrument/sample identity, event and decision time,
explicit prediction timestamp, target/Label semantics, feature schema,
validated finite values, worker runtime, provenance and truth/admission state.
Candidate rows must match the requested sample IDs exactly; positional or
partial output is rejected.

## Leakage and truth behavior

Training rows are derived from Track C SplitSpec ordinals. Only TRAIN and
VALIDATION rows cross the worker boundary. Any TEST row in a training view is
rejected before worker execution. Labels are required for training/evaluation;
prediction identity does not include evaluation labels.

The canonical lattice owner is consumed directly:

```text
ModelVersion.ceiling
  <= DatasetVersion.ceiling

PredictionArtifact.ceiling
  <= meet(ModelVersion.ceiling, prediction DatasetVersion.ceiling)
```

Successful fitting, complete artifacts, finite predictions, and a passing
metric never upgrade upstream truth. The current Track C PRE_ALPHA ceiling is
therefore preserved through the model and prediction chain.

## Safe artifact and worker boundary

The selected worker is a closed JSON stdin/stdout subprocess. The parent fixes
`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, and
`NUMEXPR_NUM_THREADS` to one, consumes the existing worker sandbox policy to
strip credentials, admits no network endpoints, and verifies the worker
runtime before use.

The worker never returns pickle/joblib/cloudpickle. It returns coefficients,
intercept, exact row IDs, metrics and its runtime descriptor. V3 produces
canonical UTF-8 JSON with media type
`application/vnd.v3.safe-linear-model+json;version=1`, validates exact keys and
finite numbers, and hashes the canonical payload. Unsupported media types,
non-canonical JSON, worker stderr/nonzero exit, timeouts, runtime drift,
missing rows, extra rows, NaN and infinity all fail explicitly. There is no
fallback backend.

## Evaluation evidence

ModelEvaluationEvidence records:

- exact ModelVersion, DatasetVersion, PredictionArtifact and SplitSpec;
- evaluated split role;
- TRAIN, VALIDATION and evaluated sample counts;
- prediction coverage and RMSE;
- missing/nonfinite counts;
- deterministic prediction digest;
- seed, worker runtime fingerprint and provenance artifact.

This is model evidence only. It does not calculate portfolio returns or claim
strategy performance.
