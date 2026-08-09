# Dataset Invariants

## 对象分解

`ADOPT_INVARIANT`：V3 不应让一个宽泛的 `Dataset config` 同时承担 feature selection、label、split、preprocessing、materialized bytes 与 runtime state。建议分为：

| 对象 | Authority 内容 | 明确不包含 |
|---|---|---|
| `FeatureSetVersion` | 有序 feature outputs、factor version refs、列名/schema、timing/missing policy、canonical hash | snapshot、训练区间、框架 handler |
| `LabelSpec` | label AST/version、observation/availability/decision/execution anchors、horizon、missing/censor policy | split、model、prediction |
| `SplitSpec` | train/valid/test/hidden-final-test 区间或 folds、purge/embargo、fit scope、chronology rules | 已 materialize rows |
| `DatasetSpec` | 上述对象 refs、sampling/join/preprocessing pipeline、quality thresholds | 可变 DataFrame、cache path |
| `DatasetVersion` | DatasetSpec + PublishedSnapshot + UniverseVersion + exact materialization/environment，及发布 manifest/artifacts | “latest” input、可重绑 config |

## D-01 — FeatureSetVersion 是有序、不可变的语义集合

`ADOPT_INVARIANT`：FeatureSetVersion 的 canonical identity 包括列顺序、每列 `FactorDefinitionVersion` 与 output selector、dtype/unit/index、alias、missing policy 和 timing contract。加入、删除、重排、重命名或改变任一 factor version 都创建新版本。

`ADAPT_TO_V3`：借鉴 Qlib loader 的 `fields + names` 与 feature/label column groups，但列名只是 manifest 属性；训练输入按 immutable column IDs 对齐，不能按偶然 DataFrame 顺序或同名列猜测。

## D-02 — LabelSpec 必须独立于 feature 与 model

`ADOPT_INVARIANT`：LabelSpec 至少声明：

- normalized label AST/operator versions；
- observation time、information availability time、decision time、execution/entry/exit anchors；
- forward horizon 与 calendar basis；
- price/view/adjustment convention；
- censor/delist/suspension/missing policy；
- output dtype/unit/direction 和 required right window；
- canonical hash 与 publication state。

`ADAPT_TO_V3`：Qlib 常用 `Ref($close,-2)/Ref($close,-1)-1`，vnpy Alpha158 也使用 forward delay。这些表达式揭示 horizon，却没有完整表达可交易时点与事实可知时点。V3 必须用明确 anchors，不能从字符串“猜 horizon”作为 formal proof。

## D-03 — SplitSpec 是 leakage control，不是三个日期别名

`ADOPT_INVARIANT`：SplitSpec validation 必须 fail closed：

- train、valid、test 按 event/decision time 严格单调；默认不重叠；
- 每个 sample 的所有 feature 在 decision time 前可知；
- train/valid 边界按 label outcome visibility 做 purge；
- hyperparameter/feature selection 与 final test 隔离；
- embargo 的方向、duration 与 calendar basis 明确；
- rolling/expanding folds 拥有独立 fold IDs 与 fit scopes；
- hidden final test 不得进入任何 fit、early stopping、threshold selection 或 trial pruning。

`REJECT_NOT_V3_FIT`：Qlib `DatasetH` 接受任意 named segments 的灵活性不应成为 formal admission。日期顺序错误、valid 在 test 后、重叠或 label spill 不能仅靠用户约定。

## D-04 — Purge 来自依赖编译，不来自经验常数

`ADOPT_INVARIANT`：split compiler 使用 LabelSpec right window、availability lag、entry/exit anchors 与 processor dependency，计算每个边界的最小 purge。用户可要求更大 purge/embargo，但不能小于证明值。编译结果与 proof artifact 是 DatasetVersion provenance 的必需输入。

`ADAPT_TO_V3`：Qlib `RollingGen.trunc_segments`、`label_leak_n` 和 horizon helper 提供了方向正确的工程经验；V3 需将其提升为 typed dependency proof，而不是 regex/字符串 heuristic。

## D-05 — Fit 与 transform 必须物理分离

`ADOPT_INVARIANT`：每个 learnable processor 声明 `fit_scope`, `input_schema`, `output_schema`, dependency signature 与 deterministic profile。一次 fit 产生 immutable `PreprocessingStateArtifact`，其 provenance 只能引用允许的 train rows。valid/test/inference 仅加载该 artifact 做 transform。

`ADOPT_INVARIANT`：processor pipeline 顺序是 canonical semantics。任何 processor 的 fit 输出、参数、输入 row-set hash 或版本改变，都创建新 DatasetVersion。

`ADAPT_TO_V3`：Qlib `DataHandlerLP` 的 `_data/_infer/_learn` 与 sequential/independent processor pipeline 是良好分层；但 `fit_start_time/fit_end_time` 仍可能误配，必须由 V3 SplitSpec 编译器注入且 worker 无权扩大。

`REJECT_NOT_V3_FIT`：未给 fit range 即 fit 全数据、先全量 normalize 再 split、对 test 做 feature selection、将 valid/test 统计量用于 fill 或 clipping，全部拒绝。

## D-06 — DatasetVersion 必须绑定精确输入与 materialization

`ADOPT_INVARIANT`：建议 canonical identity 至少覆盖：

```text
DatasetSpec hash
+ PublishedSnapshot ID/content hash
+ UniverseVersion ID/membership hash/knowledge cutoff
+ FeatureSetVersion hash
+ LabelSpec hash
+ SplitSpec hash/compiled leakage proof
+ preprocessing pipeline and fit-state artifact hashes
+ sampling/join/missing policies
+ calendar/schema/operator/engine compatibility fingerprints
```

`ADOPT_INVARIANT`：DatasetSpec 是意图；DatasetVersion 是对精确输入的一次已发布 materialization。相同 spec 对不同 snapshot/universe 产生不同 version。发布后 manifest、partitions、row-set 与 hashes 不可变。

`ADOPT_INVARIANT`：FactorDefinitionVersion/FeatureSetVersion 只描述定义语义，不因 Snapshot、UniverseVersion 或 knowledge cutoff变化而改变。DatasetVersion引用的是这些稳定定义，加上精确FactorEvaluation/feature materialization inputs与outputs；数据输入变化必须改变DatasetVersion/evaluation/cache/output identity，不能反向制造新的factor definition identity。

## D-07 — Manifest 必须证明内容，而不只是指向文件

`ADOPT_INVARIANT`：Dataset manifest 至少记录：

- canonical schema 与列级 semantic refs；
- partition list、byte hash、semantic/schema fingerprints；
- 每个 split/fold 的 exact row count、row-set hash、time range；
- universe membership hash 与 timestamp coverage；
- missing-reason/NaN/inf/duplicate/out-of-order summaries；
- feature/label availability maxima；
- fit-state artifacts；
- producer Run/Attempt、code/environment；
- leakage audit result与 threshold decisions。

`ADOPT_INVARIANT`：V3 现有 content-addressed Artifact、atomic descriptor+reference publication、safe-format allow-list 与 reachability closure 应直接承载这些对象；不要增加 Qlib/MLflow 第二 artifact registry。

## D-08 — Index 与 alignment 必须可证明

`ADOPT_INVARIANT`：canonical sample key 至少是 `(instrument_id, event_time, decision_time[, horizon/fold])`。join 必须声明 timezone/calendar、as-of direction、tolerance、duplicate policy 和 availability cutoff。prediction 后续也用这些 keys 对齐，不允许依赖 numpy/DataFrame 的隐含行顺序。

`REJECT_NOT_V3_FIT`：禁止自动 sort/drop duplicates、按“最近一条”隐式跨 decision interval resample、用外部 symbol 代替 permanent instrument identity，或在转换 DataFrame 时丢弃全空列而不改变 schema/status。

## D-09 — Universe 与横截面 preprocessing 共同决定结果

`ADOPT_INVARIANT`：cross-sectional z-score/rank/winsorize/neutralize 的 fit/transform scope 必须使用该 timestamp 的 PIT membership；输出 manifest 记录有效 denominator 与排除原因。UniverseVersion 不同即使源 values 相同，也不能复用横截面 cache/output。

`REJECT_NOT_V3_FIT`：禁止按整个研究区间是否有数据筛标的、用今天成分股回算历史、在 split 后用全量 universe 统计，或把 no-data 自动解释为“不在 universe”。

## D-10 — Dataset publication state 与 failure semantics

`ADOPT_INVARIANT`：建议状态保持 `DRAFT/VALIDATED`（spec）与 `MATERIALIZING/PUBLISHED/REJECTED`（version）分离。只有 mandatory partitions、manifest、fit state、quality report 与 leakage audit 全部原子可达时才能 `PUBLISHED`。worker success 不等于 DatasetVersion published。

`ADOPT_INVARIANT`：retry/resume 使用同一 Run 的新 Attempt；Attempt scratch/staged outputs 不得覆盖已发布 artifacts。若 canonical inputs、code 或 environment identity 改变，则新 Run/新 DatasetVersion，不是 retry。

## D-11 — Framework boundary

`ADAPT_TO_V3`：Qlib DatasetH/DataHandler 或 vnpy AlphaDataset 可作为 Attempt 内 adapter；输入由 V3 生成只读 frozen view，输出回到 staging，由 V3 校验 row/schema/hashes/leakage 后发布。

`REJECT_NOT_V3_FIT`：框架 handler config、local pickle、mutable Parquet path、instrument name、cache URI 或 segment dict 均不是 DatasetVersion。框架禁止自行下载数据、解析 latest universe 或将 warning/empty result 当成功。

`FUTURE_ONLY`：online feature serving、distributed materialization、incremental partition reuse 和跨引擎 certified equivalence 在最小 formal DatasetVersion 完成后再做。

## D-12 — Dataset 不得突破 upstream truth ceiling

`ADOPT_INVARIANT`：`PUBLISHED`、Strict PIT PASS、leakage audit PASS、split validation PASS 与train-only preprocessing PASS是彼此独立的必要条件，任何一个都不能把 `PRE_ALPHA / NOT_FORMAL` upstream提升为Formal。DatasetVersion必须持久化每个exact upstream的truth state与计算出的minimum ceiling。

```text
DatasetVersion.truth_state <= minimum(
  Snapshot validation/admission truth,
  Universe resolution truth,
  all FactorEvaluation/materialization truth states,
  label/source truth,
  preprocessing fit-state input truth,
  dataset validation/admission result
)
```

`ADOPT_INVARIANT`：同一个DatasetSpec在 `PRE_ALPHA + STRICT_PIT` Snapshot上，即使factor dependency、leakage、chronology、purge/embargo与fit proof全部PASS，发布输出最多仍是`PRE_ALPHA / NOT_FORMAL`。只有exact Snapshot validation profile已`FORMAL_ADMITTED`，Universe/PIT/revision/knowledge-cutoff满足required gates，全部factor/dataset proofs PASS且provenance完整，才有资格继续Dataset Formal admission。

`REJECT_NOT_V3_FIT`：不得把Qlib Dataset构建成功、Artifact完整、无NaN、回测表现良好或下游人工批准当作提升上游truth state的依据。
