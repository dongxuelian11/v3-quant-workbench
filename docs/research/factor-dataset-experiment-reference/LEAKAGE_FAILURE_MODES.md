# Leakage Failure Modes

## Admission rule

`ADOPT_INVARIANT`：leakage audit 不是一份运行后生成的“提示报告”。DatasetVersion 发布前必须通过静态 dependency proof、row/split proof 与 materialized output checks；无法证明即 `REJECTED` 或明确 `UNAVAILABLE`。下列 failure modes 必须拥有稳定 error code、evidence artifact 与测试。

| ID | Failure mode | 典型成因/OSS 观察 | 检测与处理 | 分类 |
|---|---|---|---|---|
| LF-01 | Latest-revision leakage | runtime 读取 provider/latest local files，而不是 Published PIT Snapshot；Qlib PIT 文档说明修订值可造成未来信息 | 验证所有 facts 的 `available_time <= decision_time/knowledge_cutoff`，输入只能是 published snapshot hash | `ADOPT_INVARIANT` |
| LF-02 | Future feature reference | Qlib `Ref` 负参数/right window 可读取未来；表达式被误放入 feature group | 编译 AST dependency，FeatureSet 任一 root right window > 0 直接拒绝 | `ADOPT_INVARIANT` |
| LF-03 | Hidden nested lookahead | nested Ref/rolling/resample 的窗口传播不完整，字符串 horizon guess 漏检 | operator registry 必须提供组合签名；unknown/unproven dependency fail closed | `ADOPT_INVARIANT` |
| LF-04 | Availability-time mismatch | event date 已发生，但财报/指数成分/修订当时尚未发布 | 同时验证 effective/event time 与 available time，不用 event date 代替 knowledge time | `ADOPT_INVARIANT` |
| LF-05 | Wrong calendar basis | 把 calendar days、trading sessions、event count 混用于 window/purge | 所有 duration 带 calendar basis/version；边界编译与 materialized rows 双重验证 | `ADOPT_INVARIANT` |
| LF-06 | Current-universe survivorship | 用今天 constituents 回算历史，或用“全区间有数据”过滤标的 | membership 必须来自 UniverseVersion 的 PIT interval；按 timestamp hash/coverage 审计 | `ADOPT_INVARIANT` |
| LF-07 | Cross-sectional universe leakage | rank/z-score 使用未来成员、split 外成员或有数据者集合 | processor 输入记录 exact membership/denominator；membership mutation 必须改变 hash/output | `ADOPT_INVARIANT` |
| LF-08 | Train/test preprocessing leakage | processor 未设 fit range 时对全数据 fit；Qlib/vnpy 均允许误配 | fit-state provenance row-set 必须是 SplitSpec fit scope 子集；否则拒绝 publication | `ADOPT_INVARIANT` |
| LF-09 | Sequential pipeline leakage | 先全量 fill/winsorize/normalize，再切 train/valid/test | pipeline compiler 将 learnable state 限定 train；每阶段记录 input/output row hashes | `ADOPT_INVARIANT` |
| LF-10 | Label spill across boundary | train sample 的 forward outcome 落在 valid/test；仅按 feature timestamp 切分 | 用 LabelSpec anchors/right window 计算 purge；逐 sample 验证 outcome availability | `ADOPT_INVARIANT` |
| LF-11 | Valid/test overlap | 任意 segment dict 接受重叠、倒序或 test 早于 valid | SplitSpec 静态 validation，formal mode 不接受 overlapping interval，除非明确 nested CV 语义 | `ADOPT_INVARIANT` |
| LF-12 | Final-test tuning | 用 test 指标选择 features、threshold、hyperparameters 或 early stopping | hidden final-test policy；Run provenance 检查所有 selection inputs，越界即污染 Experiment | `ADOPT_INVARIANT` |
| LF-13 | Rolling fold state reuse | 后续 fold 的 fit state/checkpoint 被前一 fold或反向 fold 复用 | fit-state artifact 绑定 fold ID/row hash；只允许时间向前的 declared reuse | `ADOPT_INVARIANT` |
| LF-14 | Forward/backfill leakage | fill 方法跨过 decision time，从未来 observation backfill | operator 声明 fill direction/tolerance；right dependency 非零时不得进 features | `ADOPT_INVARIANT` |
| LF-15 | Resampling leakage | Qlib signal interval 取 latest，但 latest 可能晚于 decision time或跨 calendar | SignalSpec 显式 as-of direction、cutoff、tolerance；验证 source available time | `ADAPT_TO_V3` |
| LF-16 | Corporate-action/adjustment leakage | 使用事后完整 adjustment factors 修正历史 price | factor dependency 引用 PIT-safe view/version与 anchor；不允许 provider 默认 adjustment | `ADOPT_INVARIANT` |
| LF-17 | Missing-as-information leakage | silent drop/fill 让未来存活/完整性决定样本；全 NaN 列被转换层删除 | 保留 missing reasons与原始 membership；manifest 比较 pre/post counts/schema | `ADOPT_INVARIANT` |
| LF-18 | Cache cross-contamination | cache key 未含 snapshot revision、universe、operator/missing semantics | mutation test key；hit 后验证 input/semantic fingerprints，不匹配则 discard | `ADOPT_INVARIANT` |
| LF-19 | Mutable dataset overwrite | 同一路径 Parquet merge/dedupe 或 handler refresh 改变历史 Dataset | content addressing + immutable manifest；相同 DatasetVersion bytes/hash 不可变化 | `REJECT_NOT_V3_FIT` |
| LF-20 | Instrument/index misalignment | prediction numpy order、symbol alias、duplicate key 造成 label/feature错配 | canonical sample key join；禁止 positional alignment；验证 one-to-one/cardinality | `ADOPT_INVARIANT` |
| LF-21 | Timezone/session leakage | UTC/local、overnight session、close/open timestamp 解释不一致 | calendar/session version + timezone-aware timestamps；边界 golden tests | `ADOPT_INVARIANT` |
| LF-22 | Hyperparameter search multiplicity | 多 trial 反复看 valid/test，只发布最好结果且无完整 trial ledger | Experiment 固定 search/objective policy，保存全部 trials/attempts与multiple-testing metadata | `ADAPT_TO_V3` |
| LF-23 | Failed-attempt artifact reuse | retry 读取前一失败 Attempt 的未校验 scratch output | checkpoint/Artifact 必须已 hash、schema validate、同 Run admission；其余 staged output隔离 | `ADOPT_INVARIANT` |
| LF-24 | Async publication race | recorder 标记 finished 时 metrics/artifacts 仍异步上传 | success barrier 等待 mandatory artifact原子发布；超时为 FAILED/PARTIAL | `ADOPT_INVARIANT` |
| LF-25 | Warning-and-skip success | Qlib record依赖缺失或空 label 时可 warning/return；下游结果缺失却仍成功 | required-output plan；缺失 mandatory role 不允许 Attempt/Run success | `ADAPT_TO_V3` |
| LF-26 | Prediction promoted as signal | model score 含义依赖 label，却直接被策略按可交易 signal 使用 | 独立 SignalSpec/SignalVersion，声明 interpretation、calibration、timing与universe | `ADOPT_INVARIANT` |
| LF-27 | Metric scope ambiguity | 同名 IC/return 未记录 split、horizon、denominator、direction | typed MetricDefinitionVersion + scope；不完整 metric 只可 debug，不能 formal compare | `ADOPT_INVARIANT` |
| LF-28 | Environment/operator drift | 相同名称/配置在库升级后产生不同 semantics | Run identity绑定 code/operator/environment；semantic replay test，改变即新 Run/version | `ADOPT_INVARIANT` |
| LF-29 | Nondeterministic tie/order | parallel rank/reduction、unstable sort、seed遗漏改变结果 | canonical tie-break、seed/float profile；重复 Attempt semantic hash 对比 | `ADOPT_INVARIANT` |
| LF-30 | Evaluation feedback mutation | IC/backtest Result 被写回已发布 feature/dataset或 processor state | provenance graph只允许新 version derived-from，不允许 upstream descriptor rewrite | `ADOPT_INVARIANT` |
| LF-31 | Provider standardization mistaken for truth | OpenBB标准 Data/metadata便于消费，但不证明 revision completeness/PIT | adapter result必须进入 snapshot validation/publication；provider name/metadata不等于 provenance closure | `ADAPT_TO_V3` |
| LF-32 | Executable artifact/config injection | Qlib/vnpy expressions或pickle在运行/加载时执行代码 | closed AST与safe-format allow-list；pickle/executable默认拒绝或隔离，不进入formal chain | `REJECT_NOT_V3_FIT` |
| LF-33 | Definition/evaluation identity collision | Snapshot、Universe或knowledge cutoff被写入FactorDefinition identity，或数据输入变化却复用同一evaluation ID | definition hash只覆盖“怎么算”；evaluation/materialization identity强制绑定exact data inputs，分别做正反mutation tests | `ADOPT_INVARIANT` |
| LF-34 | Truth escalation | `PUBLISHED + STRICT_PIT`、leakage PASS、Run success或Artifact完整被误当`FORMAL_ADMITTED` | 持久化upstream truth states并计算minimum ceiling；任何PRE_ALPHA/NOT_FORMAL input阻止downstream Formal | `ADOPT_INVARIANT` |

## Failure disposition

`ADOPT_INVARIANT`：failure 应分为三类且不可互换：

- `REJECTED`：spec/数据违反 invariant，例如 feature lookahead、split overlap、fit scope越界；
- `UNAVAILABLE`：当前 evaluator、operator proof、safe format或数据能力不足，不能假装空结果；
- `FAILED/PARTIAL`：admitted Run 执行失败或只发布可明确识别的部分 outputs。

`REJECT_NOT_V3_FIT`：warning、空 DataFrame、填零、fallback latest provider、跳过 dependent record 或复用旧 cache 都不能将上述状态降级为成功。
