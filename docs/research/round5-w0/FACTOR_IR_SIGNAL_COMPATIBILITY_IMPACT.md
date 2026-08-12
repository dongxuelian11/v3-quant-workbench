# Factor IR Signal-Compatible Extension Impact

Baseline: `a22092ea1a840f6e9bb790178eda0415379a8fdd`

Authorization: same-task bounded Signal-Compatible Canonical Factor IR V1 extension.

| Owner / consumer | Status | Impact |
|---|---|---|
| `FactorDefinitionVersion` / metadata | `BOOLEAN_SUPPORTED` | Root and metadata may be `FLOAT_SERIES` or `BOOLEAN_SERIES`. Identity remains semantic and registry-version-bound. |
| `DeterministicReferenceEvaluator` | `BOOLEAN_SUPPORTED` | Typed float/bool/missing execution; literals broadcast over a feature-defined domain; no truthiness or 1/0 coercion. Signal execution is version `1.1.1`: initialization admits only the exact registered legacy or signal registry, and native results are revalidated against the exact declared output type. |
| Existing numeric definitions and TA-Lib adapter | `UNCHANGED` | The stable legacy numeric registry and its evaluator identity `1.0.0` remain exact for already-addressed artifacts. New signal definitions bind the distinct extended registry. `Scalar`/`Series` stay numeric compatibility aliases and registry mismatch fails closed. |
| `FactorEvaluation` | `BOUNDED_ADAPTER_REQUIRED` | It can continue binding exact boolean definition/evaluator artifacts, but W0 does not define numeric IC semantics for boolean output. A future evaluation mode must be explicit. |
| `FeatureMaterialization` | `BOUNDED_ADAPTER_REQUIRED` | Artifact identity can bind boolean output, but storage schema/type evidence must be explicit before production materialization. |
| `DatasetVersion` | `BOOLEAN_NOT_APPLICABLE` | Current dataset feature/label pipelines are numeric-oriented and are not modified. Boolean factor inclusion requires a future typed feature adapter. |
| Experiment / Run / Attempt | `UNCHANGED` | They bind exact FactorEvaluation/artifact refs and do not interpret scalar types. |
| Strategy / Signal | `BOOLEAN_NOT_APPLICABLE` | Boolean FactorDefinition is signal-compatible, not automatically a `SignalArtifact`. No Strategy owner changes. |
| Reviewer / RewardVector / Result Analytics | `BOOLEAN_NOT_APPLICABLE` | No numeric metric or review outcome is inferred from boolean output. |

The W0 hard acceptance stops at a system-callable boolean `FactorDefinitionVersion` and typed evaluator result. It does not claim numeric FactorEvaluation, Dataset admission, Strategy signal publication, or financial effectiveness.

Legacy identity proof remains exact: `default_operator_registry().registry_version == opreg_sha256_17a1aee967f6cfcd7078da32c85c3b627279361bc60bf12eb9c4b46efa9d2733` and its evaluator remains `v3-factor-reference-evaluator/1.0.0`. The signal registry specs are unchanged at `opreg_sha256_2c18cf710cc20dfb80d3b5d11de8101f6e8820542f4baf6de25955351db1eef1`; only evaluator execution-admission behavior changed, hence the evaluator version bump.
