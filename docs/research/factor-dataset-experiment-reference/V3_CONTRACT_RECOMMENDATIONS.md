# V3 Contract Recommendations

## 文档地位

本文件是后续 contract design input，不修改也不替代当前 17-ASL。所有名称、字段与状态机都必须在未来独立 contract task 中重新评审、版本化和迁移设计。

`ADOPT_INVARIANT`：继续以 V3 Control Catalog、content-addressed Artifact Store、通用 Task/Run/TaskAttempt 与 provenance graph 为唯一 authority。Qlib/OpenBB/vnpy.alpha/MLflow 均只能位于 worker adapter 内。

## 当前 V3 基础的对齐判断

| 现有基础 | 判断 | 分类 |
|---|---|---|
| `factor_definition` / `factor_version` 已分 stable identity 与 published version | 保留；未来补 canonical AST、operator/dependency/output/missing semantic identity，不能只依赖 code artifact/hash | `ADAPT_TO_V3` |
| `dataset_spec` 已限制 chronological/rolling/expanding、purge/embargo、`TRAIN_ONLY` | 方向正确；未来将 FeatureSetVersion/LabelSpec/SplitSpec显式化，并保存compiled leakage proof | `ADAPT_TO_V3` |
| `dataset_version` 已绑定 snapshot + universe，发布需manifest/leakage audit/hash | 直接沿用；补feature/label/split/fit-state/schema/row-set lineage closure | `ADOPT_INVARIANT` |
| `study`/`trial` 与 backtest `experiment` 已存在 | 不再增加含糊的第三套tracking；先定义通用Experiment语义或清楚保留Study与Backtest Experiment边界 | `ADAPT_TO_V3` |
| 通用 `run` / `task_attempt` 已冻结input/code/environment并支持retry lineage | 直接复用所有research/factor/dataset/model/signal/backtest operations | `ADOPT_INVARIANT` |
| Artifact byte identity、immutable descriptor、active reference atomic publish、safe format、reachability/GC | 直接承载所有dataset/model/prediction/metric/result artifacts；保持pickle拒绝 | `ADOPT_INVARIANT` |
| provenance entity/edge 已表达USED/DERIVED/generated/published/executed关系 | 扩展/规范domain edge profile，但不建框架专用lineage store | `ADAPT_TO_V3` |
| `prediction_signal_version` 当前合并prediction与signal | 未来拆分semantic boundary，或至少以不同object kind/version contract严格区分raw output与tradable interpretation | `ADAPT_TO_V3` |

## 1. `FactorDefinitionVersion`

`ADOPT_INVARIANT`：建议 authority fields：

```text
factor_definition_version_id
factor_definition_id + version/display metadata
normalized_ast_artifact_id + ast_schema_version + canonical_hash
operator_registry_version_id + operator_semantic_fingerprints
source_field_dependencies[] + field_schema_fingerprints[]
dependency_signature {left, right, availability_lag, state_extent, calendar_basis}
universe_dependency_kind
timing_contract + missing_policy_version
output_schema {dtype, unit, nullability, index/shape}
determinism_profile + compatible_engine_profiles[]
admission_report_artifact_id + provenance_entity_id
state {DRAFT, VALIDATED, PUBLISHED, RETIRED, REJECTED}
```

`REJECT_NOT_V3_FIT`：不要让 `code_artifact_id/code_hash` 单独定义 factor semantics；同一代码在不同operator/field/calendar/missing约定下不是同一个 factor。

## 2. `FeatureSetVersion`

`ADOPT_INVARIANT`：新增独立versioned object，保存有序 entries：`column_id/name → factor_definition_version_id + output_selector + expected schema/timing/missing contract`。canonical hash覆盖顺序与所有semantic refs。可保存manifest artifact；不绑定某次snapshot。

`ADAPT_TO_V3`：为Qlib loader生成adapter projection（expressions/names），但projection artifact由V3派生，不能反向定义FeatureSetVersion。

## 3. `LabelSpec`

`ADOPT_INVARIANT`：新增immutable spec/version，字段至少包括normalized AST、source field/version refs、event/availability/decision/entry/exit anchors、forward horizon/calendar basis、adjustment/view、censor/missing/delist/suspension policy、right dependency与output schema。

`REJECT_NOT_V3_FIT`：不要把label只作为FeatureSet中的特殊列，也不要从表达式字符串猜horizon后直接formal publish。

## 4. `SplitSpec`

`ADOPT_INVARIANT`：新增immutable spec/version，支持chronological、rolling、expanding；每个split/fold显式interval/role；包含fit scope、purge、embargo、hidden final test、selection visibility policy。validation生成 `CompiledSplitProofArtifact`，证明label availability与processor fit boundary。

`ADAPT_TO_V3`：现有 `dataset_spec.split_kind/purge_duration/embargo_duration/TRAIN_ONLY` 可作为未来字段迁移的基础，但不要在本研究直接改表或contract。

## 5. `DatasetVersion`

`ADOPT_INVARIANT`：未来 spec需显式引用：

```text
DatasetSpec
├─ FeatureSetVersion
├─ LabelSpec
├─ SplitSpec
├─ ordered PreprocessingPipelineVersion
├─ sampling/join/index/missing/quality policies
└─ required artifact roles

DatasetVersion
├─ DatasetSpec hash
├─ PublishedSnapshotId + content hash
├─ UniverseVersionId + membership hash + knowledge cutoff
├─ preprocessing fit-state artifacts
├─ partitions + manifest + schema/row-set/coverage hashes
├─ leakage/quality reports
└─ producer Run/Attempt + provenance closure
```

`ADOPT_INVARIANT`：只有所有mandatory artifacts、proofs与references原子可达才能`PUBLISHED`。现有 `MATERIALIZING/PUBLISHED/REJECTED` 与manifest/leakage audit publication guard应保留。

## 6. `ResearchRunSpec`

`ADOPT_INVARIANT`：新增或标准化为所有研究operation的immutable canonical input envelope，而非配置日志。字段包括 operation kind、全部输入version refs/hashes、code/operator/environment、seed/determinism、resource/admission、requested outputs、mandatory artifact roles、metrics/quality thresholds。`run.canonical_input_json/input_hash` 应由此导出。

`ADAPT_TO_V3`：factor analysis、dataset materialize、model train/predict、signal promote、evaluation/backtest可共享envelope schema与operation-specific closed payload；不必各自再做一套recorder。

## 7. `Experiment`

`ADOPT_INVARIANT`：定义为immutable hypothesis/comparison spec + mutable aggregate state/read model：

- objective/metric definition versions；
- fixed inputs与allowed varying dimensions；
- search/matrix/trial generation policy；
- hidden-test/access/admission/completion policy；
- child ResearchRunSpec/Run refs与expansion manifest；
- all-runs/trials visibility，不能只保留best run。

`ADAPT_TO_V3`：需要先决策现有 `study` 和 backtest `experiment` 的domain boundary：可统一公共tracking core并保留domain views，或明确Study=optimization、Experiment=predeclared comparison。禁止仅因Qlib也叫Experiment就新增同名表。

## 8. `Run` 与 `Attempt`

`ADOPT_INVARIANT`：直接复用当前通用模型：

- Run identity = canonical ResearchRunSpec input hash + code version + environment profile；
- input变更创建新Run；
- retry/resume始终新Attempt，旧Attempt immutable；
- checkpoint属于同Run且已作为admitted Artifact发布；
- Attempt记录worker/lease/timing/error/log artifacts；
- Run terminal success依赖required-output publication barrier。

`REJECT_NOT_V3_FIT`：不要映射为“每次retry一个新的Qlib Recorder就是新Run”，也不要让external run ID参与canonical V3 identity。

## 9. `Artifact`

`ADOPT_INVARIANT`：沿用现有 `art_sha256_*`、immutable descriptor、ArtifactReference与atomic publication。为研究链新增/版本化 role/format admission profile，例如：

- `FACTOR_AST`, `FACTOR_ADMISSION_REPORT`；
- `FEATURE_PARTITION`, `DATASET_MANIFEST`, `PREPROCESSOR_STATE`, `LEAKAGE_AUDIT`；
- `SAFE_MODEL`, `PREDICTION_TABLE`, `SIGNAL_TABLE`；
- `METRIC_SERIES`, `RUN_LOG`, `ENVIRONMENT_MANIFEST`, `RESULT_MANIFEST`。

每个role定义allowed media type、schema ID/fingerprint、semantic fingerprint rules、required provenance与size/resource policy。未知role/format fail closed。

`REJECT_NOT_V3_FIT`：继续拒绝pickle和任意executable object作为formal model/processor artifact。若未来支持特定安全model format，应通过独立admission/version task，不开放任意反序列化。

## 10. `Metrics`

`ADOPT_INVARIANT`：建议 `MetricDefinitionVersion` 与 `MetricResult` 分开：definition定义名称、公式/implementation version、unit、direction、aggregation、compatible scope/schema；result引用definition、Run/Attempt、dataset/split/fold/horizon、value/sample/denominator/missing counts与supporting artifact。

`ADAPT_TO_V3`：Catalog存可检索标量/read model，大型series/distribution存在Artifact。两者必须由同一producer Attempt/provenance关联。Qlib/MLflow name/value只作为导出/镜像。

## 11. Prediction / Signal boundary

`ADOPT_INVARIANT`：建议明确拆为：

```text
PredictionVersion/Artifact
  = ModelVersion × DatasetVersion/split × LabelSpec × sample-key schema

SignalSpec/SignalVersion
  = PredictionVersion + interpretation/calibration/rank/threshold
    + as-of/resampling + tradability/missing + UniverseVersion/timing
```

Portfolio/Backtest 只接收published SignalVersion。Prediction不保证可交易，不隐含score方向、持有期或position sizing。

`ADAPT_TO_V3`：当前 `prediction_signal_version` 可暂时以不同typed artifact roles与closed sub-spec表达边界；正式拆表/contract需另开设计与migration任务。

## 12. Provenance closure 与 Result publication

`ADOPT_INVARIANT`：每种published object声明required provenance edge profile。Result publication执行closure validation，至少能遍历到：

```text
Result / Metric
← Backtest / Evaluation Run + Attempt
← SignalVersion ← Prediction ← ModelVersion
← DatasetVersion ← FeatureSet/Factor + Label + Split/FitState
← PublishedSnapshot + UniverseVersion
← code/operator/environment/actor/project context
```

closure中的每个Artifact需published、hash一致、descriptor immutable且可达。任何mandatory edge/artifact缺失时Result只能`PARTIAL/REJECTED`，不能formal finalized。

## 13. 推荐状态与命令边界

`ADOPT_INVARIANT`：保持“定义/验证/物化/发布”分离：

1. validate factor/feature/label/split/dataset/research specs（同步或短任务，无伪造outputs）；
2. publish immutable definitions/specs；
3. enqueue materialization/research Run，创建Task/Run/Attempt；
4. stage outputs；
5. validate schema/coverage/leakage/safe format/provenance closure；
6. atomic publish artifacts + refs + version/result state；
7. project Experiment/read models。

`ADOPT_INVARIANT`：`SUCCEEDED`、`PUBLISHED`、`COMPLETED`各自有不同guard，不能互相替代。

## 14. 分阶段实施建议

### Phase A — Identity 与 proof（最先）

1. `ADOPT_INVARIANT`：先冻结FactorDefinitionVersion closed AST/operator/dependency semantics；实现reference evaluator与lookahead rejection。
2. `ADOPT_INVARIANT`：定义FeatureSetVersion、LabelSpec、SplitSpec及compiled leakage proof；让fit scope成为执行访问边界。
3. `ADOPT_INVARIANT`：强化DatasetVersion manifest/row-set/schema/coverage/fit-state/provenance closure并使用现有Artifact publication。

### Phase B — Run/Artifact vertical slice

4. `ADOPT_INVARIANT`：以一个小型 `Snapshot + Universe → Factor → Dataset` end-to-end golden接通ResearchRunSpec、Task/Run/Attempt、mandatory-output publication barrier。
5. `ADOPT_INVARIANT`：随后接安全reference model，分离PredictionArtifact与SignalVersion，再连接evaluation/backtest/Result closure。

### Phase C — Adapters 与规模

6. `ADAPT_TO_V3`：实现Qlib adapter，输入只读frozen view，禁止外部fetch/cache authority，输出回V3 staging并重验。
7. `FUTURE_ONLY`：增量materialization、distributed evaluator、MLflow mirror/import、remote experiment federation与多引擎certification。

## 不建议做的事

- `REJECT_NOT_V3_FIT`：把Qlib DatasetH config、Experiment/Recorder ID或MLflow artifact URI直接写成V3 canonical foreign key。
- `REJECT_NOT_V3_FIT`：先做UI/Notebook workflow，再事后补Run/Attempt/Artifact/provenance。
- `REJECT_NOT_V3_FIT`：把current `prediction_signal_version` 的命名当作语义已统一，继续让raw prediction直接驱动portfolio。
- `REJECT_NOT_V3_FIT`：为了兼容任意模型/processor而允许pickle或任意Python eval。
- `REJECT_NOT_V3_FIT`：只记录best run或best metric，丢弃失败/取消/被剪枝attempts与selection lineage。
