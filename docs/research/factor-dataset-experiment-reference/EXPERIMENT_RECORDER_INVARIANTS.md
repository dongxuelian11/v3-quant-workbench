# Experiment / Recorder Invariants

## Qlib → V3 映射

Qlib 的运行模型是 `ExperimentManager → Experiment → Recorder`；Recorder 是一次运行，记录 parameters、metrics、models、predictions 与 artifacts。V3 已有通用 `Task → Run → TaskAttempt`、内容寻址 Artifact 与 provenance graph，因此不应照搬名词层级。

| Qlib 概念 | V3 对象 | 判定 |
|---|---|---|
| Experiment | `Experiment` | `ADAPT_TO_V3`：保留比较/组织能力，但 spec/identity 由 V3 定义 |
| Recorder / MLflow run | `Run` | `ADAPT_TO_V3`：一次 canonical input 的逻辑运行 |
| Recorder resume/restart | `Attempt` | `ADAPT_TO_V3`：每次 retry/resume 是新的 immutable Attempt |
| parameters | `ResearchRunSpec` + display metadata | `ADOPT_INVARIANT`：typed canonical spec 是 authority，日志参数只是索引 |
| metrics | typed `MetricResult` + artifact | `ADAPT_TO_V3`：定义、scope、denominator、lineage 完整 |
| saved model | `ModelVersion` + safe Artifact refs | `ADAPT_TO_V3`：不得以 pickle/path 为 authority |
| `pred.pkl` | `PredictionArtifact` | `ADAPT_TO_V3`：typed schema + dataset/label/model lineage |
| arbitrary artifacts | `Artifact` + active references | `REJECT_NOT_V3_FIT`：只允许 admitted role/format、content address 与原子发布 |

## E-01 — Experiment 是假设/比较容器，不是执行单位

`ADOPT_INVARIANT`：Experiment 描述研究问题、比较维度、固定/变化参数、objective/metric definitions、admission policy 与 stop policy。它引用一个或多个 immutable ResearchRunSpec/Run；Experiment 的 display name、tags、notes 可变，但 canonical experiment spec/version 不可原地改写。

`ADOPT_INVARIANT`：Experiment state 是其 children 的聚合 read model，不覆盖 Run/Attempt truth。`COMPLETED` 必须按预声明 completion policy 计算；存在失败可为 `PARTIAL`，不能把缺失 trials 隐藏成完成。

## E-02 — ResearchRunSpec 在排队前冻结

`ADOPT_INVARIANT`：ResearchRunSpec 至少绑定：

- operation kind：factor analysis、dataset build、train、predict、signal promotion、backtest 或 evaluation；
- snapshot、universe、factor/feature set、label/split、dataset、model/signal/backtest 等适用的 immutable refs；
- exact code/operator/environment profile、seed/determinism、resource/admission profile；
- requested outputs、mandatory artifact roles、metric definitions 与 quality thresholds；
- canonical hash、actor/project context 与 provenance envelope。

`REJECT_NOT_V3_FIT`：不得从 MLflow/Qlib logged params 事后重建 authority spec；自由文本参数不参与 canonical input 的做法会造成“相同 run ID、不同含义”。

## E-03 — Run 与 Attempt 必须分离

`ADOPT_INVARIANT`：Run 表示同一 canonical input + code + environment 下的逻辑运行；Attempt 表示一次调度/执行。retry/resume：

- 使用相同 Run，创建 `attempt_no + 1`；
- 记录 `retry_of_attempt_id` 或 checkpoint artifact；
- 旧 Attempt、logs、error artifacts 与 staged outputs 不可修改；
- 新 Attempt 只能从已校验且属于同一 Run 的 checkpoint 恢复；
- canonical input、code version 或 environment identity 改变时必须新 Run。

`ADAPT_TO_V3`：Qlib Recorder 的 running/finished/failed 状态与 resume ergonomics 有用，但缺少 V3 需要的独立 Attempt lineage。V3 现有 Catalog `run`/`task_attempt` 模型应成为统一语义，不再建立研究专用第二套 execution tables。

## E-04 — Artifact 与 Provenance 从运行开始即存在

`ADOPT_INVARIANT`：Run admission 时建立 provenance entity 与 required-output plan；Attempt 启动时记录 worker/lease/code/environment；每个 staged artifact 写入 producer Attempt、upstream IDs/hashes、role/media/schema/semantic fingerprints；terminal publication 检查完整 closure。它横切：

```text
Snapshot → Universe → Factor → FeatureSet/Label/Split → Dataset
         → Model → Prediction → Signal → Portfolio/Backtest → Result
```

`ADOPT_INVARIANT`：Artifact 是内容寻址 bytes + immutable descriptor；ArtifactReference 表达 owner/role/reachability。同 bytes 可被多个 owner 引用，但 descriptor 不能被重写。Experiment/Run/Result 删除或归档不能绕过 reachability/GC confirmation。

`REJECT_NOT_V3_FIT`：禁止把本地 path、MLflow artifact URI、Qlib recorder ID、pickle name 或数据库 blob 当 Artifact ID。V3 现有 safe-format policy 对 pickle 的拒绝必须继续保持。

## E-05 — Publication 必须先于成功

`ADOPT_INVARIANT`：Attempt 的 compute 完成、bytes flush、artifact publish、owner references、provenance edges 与 result projection 是不同步骤。只有所有 mandatory artifacts 已 hash/validate 并原子 publish 后，Attempt 才能 `SUCCEEDED`，Run 才能 terminal-success，Experiment 才能聚合完成。

`REJECT_NOT_V3_FIT`：Qlib async metric/artifact logging 可能在 compute 后才完成；V3 不接受“recorder 已 finished，但 mandatory artifact 仍异步上传”。依赖 artifact 缺失时 warning-and-skip 只能生成 `PARTIAL/FAILED`，不能成功。

## E-06 — Metrics 是 typed results

`ADOPT_INVARIANT`：MetricResult 至少包含：

- `metric_definition_version_id`；
- value dtype/decimal policy、unit、direction、aggregation；
- dataset/split/fold/horizon/universe scope；
- sample count、valid count、denominator 与 missing/exclusion counts；
- uncertainty/CI 或明确 `not_computed` reason（若适用）；
- producer Attempt 与 source prediction/signal/result artifact refs；
- computed-at 与 code/environment fingerprints。

`ADAPT_TO_V3`：Qlib `log_metrics(name=value)` 适合 UI/search projection，但不能成为 canonical MetricResult。大表/series 用 Artifact，小型 JSON/decimal 可进 Catalog read model；两者共享 identity/provenance。

## E-07 — Parameter logging 与 spec identity 分工

`ADAPT_TO_V3`：像 Qlib flatten task config 一样生成 searchable parameter projection，便于比较 Experiment runs。projection 必须从 immutable ResearchRunSpec 导出，并带 spec hash；UI tag/notes 不得参与或覆盖 authority inputs。

`ADOPT_INVARIANT`：任何结果都能回答“这次运行实际使用了什么”，答案来自 Run 的 canonical inputs，而不是当前配置、默认值或事后编辑的 experiment parameters。

## E-08 — Model、Prediction、Signal 是不同 publication boundary

`ADOPT_INVARIANT`：

- ModelVersion：safe model representation + training DatasetVersion/splits + training Run/Attempt；
- PredictionArtifact：ModelVersion 对某 DatasetVersion/split/sample keys 的原始输出，绑定 LabelSpec 与 score schema；
- SignalVersion：对 prediction 做解释、校准、rank、threshold、resample、可交易性过滤后的独立 spec/output；
- Portfolio/Backtest：消费 SignalVersion 和明确 market/execution inputs，不直接消费模糊 score 表。

`REJECT_NOT_V3_FIT`：禁止 `model.predict()` 输出因“能被策略读取”就自动成为 signal；禁止隐式 latest resampling、用数组行序对齐、或在 portfolio 阶段反向改变 label/feature semantics。

## E-09 — Evaluation 不回写上游 truth

`ADOPT_INVARIANT`：IC、prediction analysis、portfolio analysis、backtest 与 Result 是下游 artifacts/results。它们可导致创建新的 FactorDefinitionVersion/FeatureSetVersion/Experiment，但不得修改已发布 DatasetVersion、把 test feedback 写回 processor fit state，或把最佳 trial 重新标记为未曾使用 test。

`ADAPT_TO_V3`：Qlib record template 的依赖链便于复现“model → prediction → analysis → portfolio”，V3 应保留图形编排，但每条边引用 typed published object，而不是约定的 `pred.pkl` 路径。

## E-10 — Framework recorder 是镜像/适配器

`ADAPT_TO_V3`：可把 V3 Run ID 写入 Qlib/MLflow tags，并把外部 run/experiment IDs 记录为 non-authoritative provenance metadata。导入时 V3 重新 hash、schema validate、safe-format admit 并建立 Artifact refs。

`REJECT_NOT_V3_FIT`：外部 recorder 不得创建 canonical V3 IDs、决定 retry 是否同一 Run、直接标记 V3 success、绕过 Artifact publication，或成为唯一 metrics/models/predictions 存储。

`FUTURE_ONLY`：双向 MLflow federation、remote experiment catalog、跨 workspace run import/export 在本地 Run/Attempt/Artifact closure 稳定后再设计。

## E-11 — Experiment、Run 与 Prediction 继承 truth ceiling

`ADOPT_INVARIANT`：Experiment/Run/Attempt 的执行成功、Artifact closure完整与truth admission是不同维度。它们可以证明“按spec成功执行并完整发布”，但不能把upstream `PRE_ALPHA / NOT_FORMAL` 输入提升为Formal。聚合对象的truth state不得高于任一required child/input：

```text
Run/Result truth_state <= minimum(all exact input truth states, run admission result)
Experiment truth_state <= minimum(all required child Run truth states, experiment admission result)
Prediction truth_state <= minimum(ModelVersion truth, inference DatasetVersion truth, prediction admission result)
Signal truth_state <= minimum(Prediction truth, SignalSpec inputs, signal admission result)
```

`ADOPT_INVARIANT`：`PUBLISHED + STRICT_PIT != FORMAL_ADMITTED` 同样横切Research、Model、Prediction、Signal、Backtest与Result。只有upstream exact Snapshot validation profile已经Formal-admitted且后续每层required gates/provenance均通过，才有资格继续Formal admission；任何层都不能自行提权。

`REJECT_NOT_V3_FIT`：Prediction即使来自成功Run、完整Artifact与Formal模型，也不得高于其Dataset truth ceiling；它仍不能自动升级为Signal。Signal promotion是独立语义与admission boundary，但也只能保持或降低truth state。
