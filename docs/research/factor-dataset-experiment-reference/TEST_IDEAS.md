# Test Ideas

## 测试原则

`ADOPT_INVARIANT`：测试目标是证明 V3 自有 contract 与 publication 行为，而不是证明 Qlib API 被正确调用。测试可学习上游的表达式、processor、segment 与 workflow 场景，但不复制大段源码、fixtures 或 golden outputs。

每个 formal negative case 应验证：稳定 error code、无 published output、Attempt/Run terminal truth、evidence artifact、无 descriptor/reference/provenance 残缺写入。

## Factor / Expression

| ID | 测试 | 预期 | 分类 |
|---|---|---|---|
| TF-01 | canonical AST 对空白、display alias、JSON key order变化 | semantic hash不变；display metadata不影响identity | `ADOPT_INVARIANT` |
| TF-02 | non-commutative child重排；commutative operator重排 | 前者hash变化，后者仅在registry声明时canonical等价 | `ADOPT_INVARIANT` |
| TF-03 | operator semantic version或field schema变更 | FactorDefinitionVersion hash变化 | `ADOPT_INVARIANT` |
| TF-04 | nested `Ref/Rolling/Resample` dependency composition | left/right/availability签名与手算golden一致 | `ADAPT_TO_V3` |
| TF-05 | 未知、递归、expanding或无法证明window | formal admission=`UNAVAILABLE/REJECTED`，无求值 | `ADOPT_INVARIANT` |
| TF-06 | feature root含future Ref | FeatureSet validation失败；同AST可作为LabelSpec候选 | `ADOPT_INVARIANT` |
| TF-07 | expression含import/attribute/call未登记operator | parser拒绝且不执行副作用 | `REJECT_NOT_V3_FIT` |
| TF-08 | AST、operator semantic version、input field/timing/missing/output或definition compiler semantics逐一mutation | “怎么算”变化，FactorDefinitionVersion ID/hash改变 | `ADOPT_INVARIANT` |
| TF-09 | 同一FactorDefinitionVersion：Run A=`Snapshot S1 + Universe U1`；Run B=`Snapshot S2`或`Universe U2` | FactorDefinitionVersion ID相同；FactorEvaluation/Materialization/ResearchRun ID、cache key、output semantic hash与provenance不同 | `ADOPT_INVARIANT` |
| TF-10 | 相同source values但historical membership或knowledge cutoff不同的cross-sectional rank | definition ID相同；evaluation/output identity不同，denominator与membership lineage正确 | `ADOPT_INVARIANT` |
| TF-11 | missing reasons混合：warm-up/suspended/source absent/not-in-universe | NaN可相同但reason counts与policy输出正确 | `ADOPT_INVARIANT` |
| TF-12 | parallel重复执行、ties、NaN/inf/float edge | semantic output hash稳定或明确声明non-deterministic | `ADOPT_INVARIANT` |
| TF-13 | cache poison/corrupt/schema mismatch | cache被拒绝并重算，不发布错误output | `ADOPT_INVARIANT` |

## Dataset / Split / Processor

| ID | 测试 | 预期 | 分类 |
|---|---|---|---|
| TD-01 | train-valid-test正常chronology golden | exact row ranges/hash、无overlap、label visibility通过 | `ADAPT_TO_V3` |
| TD-02 | segment倒序、重叠、空hidden test | SplitSpec validation拒绝 | `ADOPT_INVARIANT` |
| TD-03 | label horizon跨train/valid边界 | compiler生成最小purge；缩小1 step即拒绝 | `ADOPT_INVARIANT` |
| TD-04 | availability lag跨边界但event time未跨 | 仍被purge/reject，证明按knowledge time而非仅event time | `ADOPT_INVARIANT` |
| TD-05 | calendar days与sessions混用 | schema/validation拒绝；明确basis时边界正确 | `ADOPT_INVARIANT` |
| TD-06 | processor fit尝试读取valid/test row | sandbox/read view拒绝；fit-state provenance不发布 | `ADOPT_INVARIANT` |
| TD-07 | 同processor不同ordering | DatasetSpec/DatasetVersion hash与output均变化 | `ADOPT_INVARIANT` |
| TD-08 | fit-state artifact从其他fold/run复用 | identity/row-set mismatch拒绝 | `ADOPT_INVARIANT` |
| TD-09 | positional feature-label-prediction alignment被shuffle | canonical key join保持正确；positional API被拒绝 | `ADOPT_INVARIANT` |
| TD-10 | duplicate sample key、timezone ambiguous、session跨午夜 | admission失败并有具体evidence | `ADOPT_INVARIANT` |
| TD-11 | UniverseVersion单个timestamp成员mutation | row-set/cross-section/manifest/cache hashes变化 | `ADOPT_INVARIANT` |
| TD-12 | DatasetSpec相同、Snapshot或Universe不同 | 生成不同DatasetVersion | `ADOPT_INVARIANT` |
| TD-13 | materialize重复运行 | manifests/semantic hashes一致；Attempt IDs不同且lineage完整 | `ADOPT_INVARIANT` |
| TD-14 | partition缺失/bytes tamper/schema drift | atomic publication不发生，staged bytes不可达 | `ADOPT_INVARIANT` |
| TD-15 | silent drop/fill或全NaN列消失 | coverage/schema diff触发threshold/rejection | `ADOPT_INVARIANT` |
| TD-16 | final test被processor fit/early stop/search读取 | access/provenance guard失败，Experiment标污染 | `ADOPT_INVARIANT` |

## Experiment / Run / Attempt / Artifact

| ID | 测试 | 预期 | 分类 |
|---|---|---|---|
| TE-01 | 同canonical input retry | 同Run新Attempt，`retry_of`正确，旧Attempt不变 | `ADOPT_INVARIANT` |
| TE-02 | retry时改spec/code/environment | 必须新Run，不能挂入旧Run | `ADOPT_INVARIANT` |
| TE-03 | resume其他Run checkpoint | fail closed，无worker启动 | `ADOPT_INVARIANT` |
| TE-04 | failed Attempt遗留同role staged artifact | 新Attempt隔离；未published bytes不可被Result引用 | `ADOPT_INVARIANT` |
| TE-05 | mandatory artifact异步延迟/上传失败 | success barrier阻止Attempt/Run成功 | `ADAPT_TO_V3` |
| TE-06 | dependency prediction/label artifact缺失 | `PARTIAL/FAILED`，不得warning后`SUCCEEDED` | `ADAPT_TO_V3` |
| TE-07 | 同artifact bytes多owner引用 | descriptor唯一不可变，references独立，GC保持reachable | `ADOPT_INVARIANT` |
| TE-08 | 相同artifact ID尝试改role/media/schema/provenance | descriptor conflict，原值保持 | `ADOPT_INVARIANT` |
| TE-09 | pickle model/prediction或未知role/format | safe-format policy拒绝/隔离 | `REJECT_NOT_V3_FIT` |
| TE-10 | Artifact发布中途catalog transaction失败 | descriptor+references全部回滚；bytes可清理但不可达 | `ADOPT_INVARIANT` |
| TE-11 | provenance closure缺Snapshot/Universe/producer Attempt | Dataset/Result publication拒绝 | `ADOPT_INVARIANT` |
| TE-12 | Experiment有success、failed、cancelled runs | state按completion policy成为PARTIAL/FAILED，完整counts可见 | `ADOPT_INVARIANT` |
| TE-13 | metrics同名但definition/split/horizon不同 | 不合并；comparison要求兼容definition | `ADOPT_INVARIANT` |
| TE-14 | metric缺denominator/sample count或artifact lineage | formal comparison拒绝 | `ADOPT_INVARIANT` |
| TE-15 | tag/notes/外部MLflow run ID变化 | 不改变Run/Result identity | `ADAPT_TO_V3` |

## Prediction / Signal / Portfolio boundary

| ID | 测试 | 预期 | 分类 |
|---|---|---|---|
| TP-01 | model raw score发布 | 只能生成PredictionArtifact，不能被portfolio直接admit | `ADOPT_INVARIANT` |
| TP-02 | promotion spec声明rank/calibration/threshold/resample | 生成独立SignalVersion并完整lineage | `ADOPT_INVARIANT` |
| TP-03 | decision cutoff后才available的prediction | signal row被排除/拒绝，不能latest回填 | `ADOPT_INVARIANT` |
| TP-04 | prediction sample order打乱 | Signal按canonical keys相同；positional alignment拒绝 | `ADOPT_INVARIANT` |
| TP-05 | SignalVersion与backtest UniverseVersion不一致 | submitBacktest admission失败 | `ADOPT_INVARIANT` |
| TP-06 | evaluation后尝试改Dataset/Prediction descriptor | immutable conflict；只能创建新derived version | `ADOPT_INVARIANT` |

## Truth ceiling

| ID | 测试 | 预期 | 分类 |
|---|---|---|---|
| TT-01 | 同一Factor/Dataset spec，Case A绑定`PRE_ALPHA + STRICT_PIT` Snapshot，Case B绑定`FORMAL_ADMITTED + STRICT_PIT` Snapshot | definition IDs可保持一致；evaluation/materialization IDs必须不同；A最多non-formal，B仅有资格继续Formal admission | `ADOPT_INVARIANT` |
| TT-02 | Snapshot lifecycle=`PUBLISHED`且Strict PIT proof PASS，但validation profile admission=`PRE_ALPHA` | FactorEvaluation、DatasetVersion、Run、Prediction均不得成为Formal | `ADOPT_INVARIANT` |
| TT-03 | 多个upstream truth states中任一个由Formal降为PRE_ALPHA/NOT_FORMAL | downstream ceiling精确降为minimum；spec/definition identity不因数据truth变化而重建 | `ADOPT_INVARIANT` |
| TT-04 | factor dependency、lookahead、leakage、split、train-only fit与Artifact closure全部PASS，但upstream非Formal | proofs保存为PASS，truth admission仍为non-formal，禁止把proof success折叠成Formal | `ADOPT_INVARIANT` |
| TT-05 | Formal model对PRE_ALPHA Dataset生成Prediction，再执行Signal promotion | Prediction与Signal均不得高于PRE_ALPHA；Prediction仍不是Signal | `ADOPT_INVARIANT` |
| TT-06 | Case B upstream Formal-admitted，但缺Universe revision gate或provenance edge | 只表示具备部分必要条件；Formal admission仍拒绝 | `ADOPT_INVARIANT` |

## End-to-end reference scenarios

`ADAPT_TO_V3`：学习 Qlib all-pipeline test 的完整形状，建立 V3 自有最小 golden：

1. 发布一个小型 PIT Snapshot 与两次历史 membership change 的 UniverseVersion；
2. 发布一个纯时序 factor 和一个cross-sectional factor；
3. 发布FeatureSetVersion、forward LabelSpec、chronological SplitSpec；
4. materialize DatasetVersion，产生manifest、fit state、coverage/leakage artifacts；
5. 创建Experiment/ResearchRunSpec/Run/Attempt，训练安全reference model；
6. 发布PredictionArtifact，再通过显式promotion spec发布SignalVersion；
7. 运行evaluation/backtest并发布typed Metrics/Result；
8. 从Result反向遍历到Snapshot/Universe/Factor/Dataset/Model/Signal/Attempt，验证closure与hashes。

`ADOPT_INVARIANT`：同一scenario再运行mutation matrix：只改变snapshot revision或universe membership时，FactorDefinitionVersion保持不变而Evaluation/Materialization及下游identities变化；只改变factor operator version时definition及下游identities变化；再分别改变label horizon、purge、processor fit rows、model seed、signal resampling与upstream truth admission，逐项断言identity与truth ceiling只在正确边界变化且无对象被覆盖。

`FUTURE_ONLY`：在reference evaluator稳定后，再加入Qlib adapter conformance suite、不同计算引擎semantic equivalence、大规模partition fault injection与remote recorder import tests。
