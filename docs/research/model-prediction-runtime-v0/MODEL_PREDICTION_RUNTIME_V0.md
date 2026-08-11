# Model / Prediction Runtime V0

## Owner boundary

Track E owns the raw model chain only:

```text
DatasetVersion
-> TrainingSpecVersion
-> ModelTrainingRequest
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

### Exact worker requests

V3 Core creates immutable request descriptors before worker execution. The
worker is not a request authority; protocol `v3.model-worker/2` only permits it
to echo the parent-issued request ID.

`ModelTrainingRequest` binds the exact DatasetVersion and dataset artifact,
TrainingSpecVersion, training binding, ModelRun, TRAIN/VALIDATION row-set
hashes, feature-schema and worker-runtime fingerprints, seed, and code version.
`WorkerTrainingCandidate` must echo that exact ID. Core also computes a digest
over the complete validated candidate, including coefficients and metrics, so
TrainingEvidence and the safe model artifact cannot be mixed across requests
or across different candidate contents.

`ModelPredictionRequest` binds the exact ModelVersion, safe model artifact,
originating training request, TrainingSpecVersion, prediction DatasetVersion
and dataset artifact, prediction row-set hash, feature-schema and runtime
fingerprints, and target semantics. `WorkerPredictionCandidate` must echo the
exact request ID; runtime, feature order, and sample IDs alone are insufficient.

### ModelVersion

ModelVersion binds the exact DatasetVersion, ModelRun, TrainingSpecVersion,
ModelTrainingRequest, validated worker-candidate digest, V3 safe model artifact
ID/media type, ordered feature schema fingerprint, worker runtime, seed,
training evidence, provenance artifact and propagated truth/admission state. A
worker response containing a canonical model or request ID other than the
parent-issued echo is rejected.

### PredictionArtifact

PredictionArtifact binds the exact ModelVersion, exact safe model artifact,
ModelPredictionRequest, prediction DatasetVersion, canonical sample row set,
instrument/sample identity, event and decision time, explicit prediction
timestamp, target/Label semantics, feature schema, validated finite values,
worker runtime, provenance and truth/admission state. Candidate rows must match
the requested sample IDs exactly; positional, partial, or cross-request output
is rejected.

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

The selected worker is a closed JSON stdin/stdout subprocess using explicit
protocol `v3.model-worker/2`. The parent fixes
`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, and
`NUMEXPR_NUM_THREADS` to one, consumes the existing worker sandbox policy to
strip credentials, admits no network endpoints, and verifies the worker
runtime before use.

The worker never returns pickle/joblib/cloudpickle. It returns coefficients,
intercept, exact row IDs, metrics, its runtime descriptor, and only an echoed
parent-issued request ID. V3 produces
canonical UTF-8 JSON with media type
`application/vnd.v3.safe-linear-model+json;version=1`, validates exact keys and
finite numbers, binds the training request and candidate digest, and hashes the
canonical payload. Unsupported media types,
non-canonical JSON, worker stderr/nonzero exit, timeouts, runtime drift,
missing rows, extra rows, NaN and infinity all fail explicitly. There is no
fallback backend.

## Dataset row-materialization V0 boundary

Track C DatasetVersion owns `dataset_artifact_id`, but V0 does not yet expose a
canonical resolver or row-materialization receipt that proves caller-provided
`ModelSample` values were decoded from those exact artifact bytes. Track E does
not create that missing Dataset authority.

TrainingDatasetView and PredictionDatasetView therefore describe an exact
content-addressed model-runtime input view: they bind DatasetVersion,
`dataset_artifact_id`, exact typed rows, and deterministic row-set hashes. This
is exact request provenance, not proof of owner-resolved artifact decoding. The
unresolved materialization boundary remains PRE_ALPHA and successful training,
prediction, artifact validation, or metrics cannot promote it to FORMAL.

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
