# Factor IR Signal-Compatible Extension Impact

Baseline: `a22092ea1a840f6e9bb790178eda0415379a8fdd`

Authorization: same-task bounded Signal-Compatible Canonical Factor IR V1 extension.

| Owner / consumer | Status | Impact |
|---|---|---|
| `FactorDefinitionVersion` / metadata | `BOOLEAN_SUPPORTED` | Root and metadata may be `FLOAT_SERIES` or `BOOLEAN_SERIES`. Identity remains semantic and registry-version-bound. |
| `DeterministicReferenceEvaluator` | `BOOLEAN_SUPPORTED` | Typed float/bool/missing execution; literals broadcast over a feature-defined domain; no truthiness or 1/0 coercion. Signal-compatible registry execution is version `1.1.0`. |
| Existing numeric definitions and TA-Lib adapter | `UNCHANGED` | The stable legacy numeric registry and its evaluator identity `1.0.0` remain exact for already-addressed artifacts. New signal definitions bind the distinct extended registry. `Scalar`/`Series` stay numeric compatibility aliases and registry mismatch fails closed. |
| `FactorEvaluation` | `BOUNDED_ADAPTER_REQUIRED` | It can continue binding exact boolean definition/evaluator artifacts, but W0 does not define numeric IC semantics for boolean output. A future evaluation mode must be explicit. |
| `FeatureMaterialization` | `BOUNDED_ADAPTER_REQUIRED` | Artifact identity can bind boolean output, but storage schema/type evidence must be explicit before production materialization. |
| `DatasetVersion` | `BOOLEAN_NOT_APPLICABLE` | Current dataset feature/label pipelines are numeric-oriented and are not modified. Boolean factor inclusion requires a future typed feature adapter. |
| Experiment / Run / Attempt | `UNCHANGED` | They bind exact FactorEvaluation/artifact refs and do not interpret scalar types. |
| Strategy / Signal | `BOOLEAN_NOT_APPLICABLE` | Boolean FactorDefinition is signal-compatible, not automatically a `SignalArtifact`. No Strategy owner changes. |
| Reviewer / RewardVector / Result Analytics | `BOOLEAN_NOT_APPLICABLE` | No numeric metric or review outcome is inferred from boolean output. |

The W0 hard acceptance stops at a system-callable boolean `FactorDefinitionVersion` and typed evaluator result. It does not claim numeric FactorEvaluation, Dataset admission, Strategy signal publication, or financial effectiveness.
