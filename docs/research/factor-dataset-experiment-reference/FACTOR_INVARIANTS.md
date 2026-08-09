# Factor Invariants

## 结论对象：`FactorDefinitionVersion`

`ADOPT_INVARIANT`：Factor 不是一个列名、Python 类、表达式字符串或缓存条目。描述“因子怎么算”的最小 authority 单元是不可变 `FactorDefinitionVersion`；描述“这一定义在什么精确数据上算了一次”的 authority 单元是 `FactorEvaluation`（批量持久化时也可称 `FeatureMaterialization`）。两者 identity 必须分离。

`FactorDefinitionVersion` 建议至少包含：

| 字段组 | 必需语义 |
|---|---|
| Identity | `factor_definition_id`、`factor_definition_version_id`、stable display name、canonical hash、publication state |
| Expression | closed normalized AST、root output、operator registry ID、每个 operator semantic version |
| Data semantics | logical input field IDs/semantics、frequency/calendar basis、adjustment/view semantics；不绑定某次 Snapshot |
| Time | observation time、available-time policy、decision-time convention、left lookback、right lookahead、warm-up |
| Universe semantics | universe dependency kind：per-instrument / cross-sectional / membership-derived；不绑定某次 UniverseVersion |
| Output | dtype、unit、shape/index contract、nullability、missing-reason vocabulary |
| Definition execution semantics | deterministic/compiler semantics、numeric/tie-break contract、seed policy（若定义级）；不绑定某次 runtime environment |
| Definition admission | AST/operator allow-list、dependency proof schema、definition-level review/evidence versions；不声明数据truth |
| Provenance | author/actor、code/operator artifacts、review/admission artifact、supersedes/revision edges |

一次 `FactorEvaluation` / `FeatureMaterialization` identity 必须绑定：

- `FactorDefinitionVersion`；
- exact `DataSnapshotVersion` 与 content hash；
- exact `UniverseVersion`、historical membership resolution 与 membership hash；
- `knowledge_cutoff`、exact calendar version；
- materialization-time schema/fingerprints；
- environment/engine fingerprint与time range。

`ADOPT_INVARIANT`：producer ResearchRun/Attempt作为求值provenance记录；retry产生新Attempt，但在canonical inputs与semantics完全相同时，不应仅因Attempt ID不同而强制改变FactorEvaluation semantic identity。

`ADOPT_INVARIANT`：Snapshot、UniverseVersion、historical membership、knowledge cutoff、calendar version或 runtime engine变化时，`FactorDefinitionVersion` identity 保持不变；`FactorEvaluation` / `FeatureMaterialization` / `ResearchRun` identity、cache key、output semantic hash与provenance必须改变。只有“怎么算”的语义变化才创建新的FactorDefinitionVersion。

## F-01 — 表达式图必须 canonical、封闭且可审计

`ADAPT_TO_V3`：采用 Qlib expression graph 的可组合思想，但使用 typed AST，而不是以 `str(expression)` 或 Python `eval` 作为 formal identity。canonicalization 必须稳定处理 operator 名、版本、参数类型/精度、字段 ID、子节点顺序；只有明确声明 commutative 的 operator 才允许子节点重排。

`REJECT_NOT_V3_FIT`：禁止 formal factor AST 包含任意 import、attribute traversal、I/O、network、动态代码、lambda 或未登记 operator。展示字符串、源代码路径、类名、Qlib cache URI、vnpy expression name 都不能代替 canonical hash。

## F-02 — 名称与版本不可混同

`ADOPT_INVARIANT`：`stable_name` 用于人类发现；语义由 `FactorDefinitionVersion` 决定。同名但 AST、operator version、字段、时序、missing policy、输出 schema 任一不同，必须生成新版本和新 canonical hash。不同名称但 canonical semantics 相同，可建立 alias，不复制 authority。

`ADAPT_TO_V3`：保留 Qlib Alpha158/360 的友好 feature names，但 dataset manifest 的列必须同时记录 `feature_name`、`factor_definition_version_id`、output path 与 semantic hash，避免 rename 或 rebinding 改写历史结果。

## F-03 — Window dependency 是类型系统的一部分

`ADOPT_INVARIANT`：每个 operator 必须声明可组合的 dependency signature：

- `left_observation_window`：计算时需向过去扩展的 calendar/trading steps；
- `right_observation_window`：计算当前输出需读取未来 observation 的 steps；
- `availability_lag`：事实发生到可知的延迟；
- `state_extent`：expanding/stateful operator 的 checkpoint 或完整历史需求；
- `calendar_basis`：trading sessions、calendar duration 或 event count。

`ADOPT_INVARIANT`：formal feature 默认要求 `right_observation_window = 0`。非零右窗口只能用于明确标记为 label/diagnostic 的输出，不能进入 FeatureSet。嵌套 `Ref`、rolling、resample、join、forward-fill 和 stateful operator 的签名必须组合计算；无法证明时拒绝，而不是用 heuristic extended days。

`ADAPT_TO_V3`：Qlib `get_extended_window_size` 和 operator propagation 是良好起点，但源码承认某些嵌套 Ref 与 expanding window 估计不完整，因此不能直接作为 V3 leakage proof。

## F-04 — 数据依赖必须指向已发布事实

`ADOPT_INVARIANT`：FactorDefinitionVersion 只声明逻辑字段与时间/缺失/输出语义；一次 `FactorEvaluation` / `FeatureMaterialization` 还必须绑定：

- 精确 `PublishedSnapshotId` 与 content hash；
- 精确 `UniverseVersionId` 与 membership artifact hash；
- field schema/normalization/adjustment semantic fingerprints；
- calendar version、knowledge cutoff 与 available-time policy；
- operator registry/engine compatibility fingerprint。

`REJECT_NOT_V3_FIT`：禁止 factor runtime 直接请求“latest provider data”、当前 instruments、可变本地文件或框架全局 provider。Qlib/OpenBB 只能读取 V3 已冻结的适配视图，不能补齐、刷新或替换输入。

## F-05 — Universe dependency 必须显式

`ADOPT_INVARIANT`：逐标的时序求值也要绑定 UniverseVersion，以确定 row membership 与 coverage；cross-sectional rank/z-score/neutralization 则必须将每个 timestamp 的精确成员集合纳入求值依赖。Universe membership 或 knowledge cutoff 改变时，FactorDefinitionVersion identity 不变，但 cross-sectional FactorEvaluation/materialization identity、cache key、output hash与provenance必须改变。

`REJECT_NOT_V3_FIT`：禁止用“有数据的标的集合”反推 universe，禁止以全样本期是否存在数据过滤标的，禁止用今天的 constituents 回填历史截面。这覆盖 Qlib `TimeRangeFlt` 自己警告的 leakage 类型。

## F-06 — Missing value 是事实，不只是 NaN

`ADOPT_INVARIANT`：定义版本必须声明 `missing_policy_version`，至少区分：source absent、not-yet-available、not-in-universe、not-listed、suspended/no-trade、warm-up insufficient、invalid arithmetic、join miss 与 policy-masked。materialization manifest 记录每列/时间/标的的 coverage 与 reason counts。

`ADAPT_TO_V3`：Qlib 的 `Fillna`、`Dropna`、`ProcessInf` 和 rolling `min_periods=1` 可作为 processor 行为参考，但 V3 必须显式选择 min periods、fill scope 与 reason preservation。默认不得因 `min_periods=1` 在 warm-up 不足时产生看似完整的值。

`REJECT_NOT_V3_FIT`：禁止 silent drop/fill、把 unknown 当 false/zero、把 suspension 与 source outage 合并、或因 DataFrame 转换自动删除全 NaN 列后仍保持同一 schema identity。

## F-07 — Cache 不是 authority

`ADOPT_INVARIANT`：factor evaluation cache key 必须来自 canonical execution input，至少覆盖：

`snapshot hash + universe membership hash + knowledge cutoff + factor definition version hash + time range/calendar version + materialized field schema + runtime engine/environment fingerprint`。

cache entry 必须有 checksum、producer attempt、coverage、schema fingerprint 与 provenance。命中后仍执行 manifest/identity 校验；损坏、陈旧或缺字段时 discard/recompute，不得发布 cache key 为 V3 object ID。

`ADAPT_TO_V3`：Qlib expression/dataset caching 展示了图节点复用和区间扩展价值，但其 instrument/field/date/processor 参数组合不足以证明 V3 snapshot revision、universe membership 与 operator semantics。

## F-08 — 计算必须 deterministic 或诚实声明不确定性

`ADOPT_INVARIANT`：排序 tie-break、浮点 policy、timezone、calendar alignment、parallel reduction、seed、library/runtime profile 必须固定。相同 canonical input 的重复 Attempt 应产生相同 semantic fingerprint；byte-level 不稳定时需定义 canonical semantic hash，并保留 byte hashes。

`FUTURE_ONLY`：GPU/分布式表达式执行、增量 state checkpoint 和多引擎 equivalence certification 可后置；第一阶段先支持小型 closed operator set 与确定性 CPU reference evaluator。

## F-09 — Factor publication 与 Artifact/Provenance 同时设计

`ADOPT_INVARIANT`：发布 FactorDefinitionVersion 时即建立 AST/spec artifact、admission report、operator registry 与 provenance entity；运行开始时创建 Run/Attempt envelope；运行结束时原子关联 output partitions、manifest、coverage/leakage report。Artifact 不是 factor 完成后补录的附件。

`ADOPT_INVARIANT`：任一 published feature partition 都能沿 provenance closure 回到 snapshot、universe membership、factor definition/operator versions、producer Attempt、environment/code version。closure 不完整则不得发布 DatasetVersion。

## F-10 — Framework boundary

`ADAPT_TO_V3`：Qlib 可实现 AST 子集、窗口计算与 feature evaluation，vnpy.alpha/Polars 可做研究期 reference implementation；adapter 输出只能进入 V3 staging。

`REJECT_NOT_V3_FIT`：框架的 feature name、provider state、cache、pickle、experiment ID、recorder status 或本地文件路径均不能成为 V3 authority。适配器必须接收冻结输入、禁止外部读取，并由 V3 验证输出后发布。

## F-11 — 显式继承 Data Truth truth ceiling

`ADOPT_INVARIANT`：`PUBLISHED + STRICT_PIT` 不等于 `FORMAL_ADMITTED`。`PUBLISHED` 是生命周期状态，Strict PIT 是可见性/修订证明，upstream validation profile 的 admission state 才定义其 truth ceiling。Factor dependency/lookahead proof PASS 只能证明因子求值自身的必要条件，不能提升上游数据权威。

`ADOPT_INVARIANT`：任何 FactorEvaluation / FeatureMaterialization 均满足：

```text
output truth_state <= minimum(
  Snapshot validation/admission truth,
  Universe resolution truth,
  required field/calendar/revision truth,
  Factor evaluation admission gates
)
```

若 exact Snapshot 或 Universe upstream truth 是 `PRE_ALPHA / NOT_FORMAL`，即使 Strict PIT、dependency、lookahead、coverage 全部 PASS，输出最多仍是 `PRE_ALPHA / NOT_FORMAL`。只有 exact upstream Snapshot profile 已 `FORMAL_ADMITTED`、Universe/PIT/revision/knowledge-cutoff gates满足、factor proof PASS且provenance完整，才有资格继续下游Formal admission；“有资格继续”仍不等于自动成为Formal。
