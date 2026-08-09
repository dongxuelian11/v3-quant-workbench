# V3 Data Truth / Universe Recommendations

## 决策边界

本页不创建新 authority、不替代冻结架构，也不建议安装 OpenBB/Qlib/RQAlpha/vn.py。所有建议落到现有 DataSourceService、InstrumentService、DataSnapshotService、UniverseService、Artifact、Task 和 Control Catalog；证据见 [`SOURCES.md`](./SOURCES.md)，行为测试见 [`TEST_IDEAS.md`](./TEST_IDEAS.md)。

分类定义：

- **ADOPT_INVARIANT**：作为 formal truth 必须满足的稳定约束。
- **ADAPT_TO_V3**：吸收行为或分层思想，但用 V3 现有合同和实现语言独立落地。
- **REJECT_NOT_V3_FIT**：明确不进入 V3 Authority 或 WS-F。
- **FUTURE_ONLY**：保留证据和测试思想，但不扩张当前阶段。

## ADOPT_INVARIANT

| ID | Recommendation | Primary mapping | Supporting planes / control |
|---|---|---|---|
| A-01 | connector capability 以 connector version × canonical operation × semantic profile 显式登记；missing/incompatible 为 typed unavailable | DataSourceService | Control Catalog admission；Task canonical input |
| A-02 | permanent InstrumentId 与所有 provider/gateway symbols 分离；alias 按 effective/available interval 解析且歧义失败 | InstrumentService | Control Catalog instrument/revision/alias；Universe resolution audit |
| A-03 | 所有可修订事实保留 effective time、available time、ingested time 和 provider revision | DataSnapshotService | RawCapture、Artifact manifest、Control Catalog validation |
| A-04 | venue calendar 是带 coverage、source、version 的 published fact；越界不 fallback/clamp | DataSnapshotService | Artifact；Task 固定 calendar ID/hash；Control Catalog capability |
| A-05 | published snapshot 的 manifest、bytes、selected revisions 与 truth profile 不可变；修订产生新 snapshot | DataSnapshotService | Artifact staged/verified/published；Task immutable inputs |
| A-06 | Universe membership 具有有效期、available time、evidence，resolve 固定 PUBLISHED snapshot + knowledge cutoff | UniverseService | Artifact membership/audit；Control Catalog universe_version |
| A-07 | requested symbol 集合必须 resolution-conserving：resolved/unresolved/ambiguous/excluded 总数守恒 | InstrumentService / UniverseService | Artifact audit；publication validation |
| A-08 | corporate-action raw events、adjustment factor/view、未来 portfolio accounting 分离 | DataSnapshotService | Artifact partitions/derived artifacts；Control Catalog validation |
| A-09 | adjustment spec 明确 raw marker、basis、anchor、fields 和 factor artifact，且只能应用一次 | DataSnapshotService | Dataset materialization；Artifact lineage；Task hash |
| A-10 | suspension、ST、limit up/down 是独立 temporal facts；unknown 不等于 False | DataSnapshotService | InstrumentService identity join；Control Catalog capability/completeness |
| A-11 | provider/source/version/request/capture/revision lineage 不因 normalization 丢失；跨源冲突不自动择优 | DataSourceService | RawCapture、Artifact evidence、snapshot validation |
| A-12 | Universe 与 benchmark 各自显式绑定并独立进入 canonical input | UniverseService / Task | Dataset spec；Artifact manifest |
| A-13 | formal path 禁止 silent fallback、warning-and-drop、empty-as-success、wall-clock defaults | DataSourceService | Control Catalog admission；Task error taxonomy |
| A-14 | 许可证 provenance 与 data provenance 同样进入 connector/research governance；不能复制 AGPL 或受自定义限制代码 | Control Catalog | Artifact source metadata；code review control |

## ADAPT_TO_V3

| ID | External lesson | V3 adaptation | Mapping |
|---|---|---|---|
| D-01 | OpenBB standard model + provider fetcher pipeline | 将 adapter conformance 明确为 validate canonical query → provider request → raw capture → normalized candidate；provider extras 只进入 namespaced evidence | DataSourceService、DataSnapshotService、Control Catalog |
| D-02 | OpenBB RegistryMap capability discovery | 在已有 connector capability/admission 表上生成可查询 matrix；不引入其 registry 或动态插件 authority | Control Catalog、DataSourceService |
| D-03 | Qlib CalendarProvider / InstrumentProvider | 把 calendar 与 membership spans 作为独立 snapshot partitions；不复用其全局 handler/cache | DataSnapshotService、UniverseService、Artifact |
| D-04 | Qlib publication-date PIT revision selection | 扩展为全域 available timestamp + revision chain，并由 candidate admission 证明 cutoff | DataSnapshotService、InstrumentService、Control Catalog |
| D-05 | Qlib Loader → Handler → Dataset segments | 保持 V3 既有 snapshot → Universe → dataset materialization；processor/split spec 都 canonical-hashable，infer/learn dependency 分开审计 | DataSnapshotService、UniverseService、Task、Artifact |
| D-06 | RQAlpha time-qualified instrument resolution | 用 V3 permanent ID + alias intervals 独立实现；保留 delisted history，不依赖当前 active list | InstrumentService、Control Catalog |
| D-07 | RQAlpha China-market status/action/limit boundary tests | 建立 V3 自有最小 A 股 fixture，覆盖戴帽/摘帽、停牌、制度变化、tick edge、分红拆分时序 | DataSnapshotService、InstrumentService、Control Catalog tests |
| D-08 | RQAlpha as-of index APIs | Universe API 要求 explicit as-of + knowledge cutoff，future date/cutoff violation 显式失败；不调用其 proprietary provider | UniverseService、Task |
| D-09 | vn.py symbol + exchange + gateway source DTO | normalized capture 必带 venue/source；`symbol.exchange` 仅 routing/display alias，不是 InstrumentId | DataSourceService、InstrumentService、RawCapture |
| D-10 | vn.py gateway capability heterogeneity | capability 精确到 venue、asset、frequency、history/status/actions；不以“connector 已安装”推断全能力 | Control Catalog、DataSourceService |
| D-11 | 上游 boundary tests | 将 typed stages、revision publication、calendar edges、limit precision、event ordering转译为 V3 behavior/metamorphic suite | 各 Service、Artifact、Task tests |

## REJECT_NOT_V3_FIT

| ID | Rejected pattern | Reason | Guard location |
|---|---|---|---|
| R-01 | 把 OpenBB symbol、RQAlpha order_book_id 或 vn.py vt_symbol 当 permanent InstrumentId | 都是 provider/dataset/routing scope 的标识，存在漂移、复用或 source collision | InstrumentService / Control Catalog |
| R-02 | 把 Qlib/RQAlpha bundle、handler/cache 或任一 provider 变成 V3 Authority | 上游存储可变、版本/PIT/provenance 保证不足；会建立第二 truth source | DataSnapshotService / Artifact |
| R-03 | provider 参数 warning 后丢弃，或缺能力返回空结果/False | 把 semantic failure 伪装成可用数据 | DataSourceService admission |
| R-04 | future calendar 回退当前 calendar、previous/next 越界钳制 | 会把 coverage gap 伪装成合法交易日 | DataSnapshotService validation |
| R-05 | 默认 skip suspended、默认 pre-adjust、缺日期取 wall clock | 同一请求的样本/语义会隐式改变 | DataSourceService query contract / Task hash |
| R-06 | database/datafeed/source 自动 fallback | lineage 与 requested capability 不再真实 | DataSourceService / Task / Artifact |
| R-07 | fixed 10% 推导所有 A 股 price limits | 忽略 ST、板块、制度日期、IPO 和 tick rules | DataSnapshotService controls |
| R-08 | 用 latest constituents、current name、zero volume 推导历史 membership/ST/suspension | 造成 future/survivorship/status leakage | UniverseService / Snapshot validation |
| R-09 | 复制 OpenBB AGPL、RQAlpha 自定义许可或任何上游测试代码 | 与本研究 clean-room 行为转译原则及 Apache-2.0 交付风险不符 | Code review / Control Catalog provenance |
| R-10 | 在 WS-F 引入外部回测器、matcher、gateway runtime 或插件系统 | 超出 Data Truth / Universe 范围并冲击冻结架构 | Architecture boundary / Task admission |
| R-11 | 新建宏大 data authority、registry 或第二 artifact/task plane | V3 已有 Control Catalog、Artifact、Task；应深化而非替代 | Architecture review |

## FUTURE_ONLY

| ID | Topic | Why deferred | Future dependency |
|---|---|---|---|
| F-01 | order lifecycle、partial fill、cancel remainder、matching price | RQAlpha 测试很成熟，但 WS-F 目标是数据真值，不是执行模拟 | 先有可靠 suspension/limit/lot/liquidity facts 和冻结 execution contract |
| F-02 | intraday session、night session、live gateway reconciliation | 当前 V3 目标为中国 A 股 daily/EOD | calendar/session model、timestamp provenance、live connector admission |
| F-03 | corporate-action portfolio tax/reinvestment accounting | 应与 raw events/adjustment 分域 | 税则版本、account/position contract、event ordering spec |
| F-04 | multi-provider consensus/scoring | 自动择优容易形成隐式 authority | 先建立每源 capture、disagreement findings 与人工 source-of-record policy |
| F-05 | generalized expression engine for dynamic Universe | 可能引入 future refs 和复杂 leakage surface | dependency graph、static time-direction audit、resource governance |
| F-06 | provider plugin marketplace/runtime discovery | 不应为研究目标扩张运行时 | capability/admission 稳定后另行评估 |

## 映射总览

| V3 component | 立即承担的 invariant | 不承担的职责 |
|---|---|---|
| DataSourceService | adapter boundary、strict query、capability check、raw capture + lineage、no fallback | 不铸造 InstrumentId，不发布 snapshot，不决定 Universe |
| InstrumentService | permanent identity、time-qualified alias/revision resolution、完整 resolution audit | 不把 provider symbol 升格为 authority，不隐式删 unresolved |
| DataSnapshotService | three-time PIT、calendar/status/action partitions、validation、immutable publication、adjustment derivation | 不拥有 provider runtime，不执行 portfolio accounting |
| UniverseService | definition resolve、temporal membership、knowledge cutoff、snapshot binding、audit artifact | 不用当前 constituents 回填历史，不把 benchmark 隐式等同 Universe |
| Artifact | raw/normalized/derived/membership/audit bytes 的 content address、verification、immutable publication | 不解释金融语义，不自行选择 source |
| Task | canonical inputs、Run/Attempt、exact retry/replay、resource/error provenance | 不用 retry 改 source/default/cutoff，不把 input change 当同一 Run |
| Control Catalog | connector version/capability/admission、instrument/alias/revision、capture/snapshot/universe records、validation/control evidence | 不成为第二数据 blob store，不绕过 Artifact publication |

## 对 WS-F 最值得立刻吸收

WS-F 应优先完成一条窄但可证明的 daily/EOD truth path，而不是扩 provider 数量：

1. **Capability truth first**：为首个 connector version 固定 bars、calendar、instrument master、suspension、ST、limits、corporate actions 的 `FORMAL / DEMO / UNAVAILABLE` matrix；任何缺口都不可伪装为空数据。
2. **Identity before ingestion scale**：先证明 permanent InstrumentId + alias interval + available time + ambiguity audit，再扩大股票数或 provider 数。
3. **Calendar as a published partition**：固定 SSE/SZSE/BSE coverage、session dates 和 source；越界 fail closed。
4. **Three-time raw captures**：每条可修订事实保留 effective、available、ingested time，以及 request/provider revision/raw hash。
5. **One immutable snapshot slice**：用极小 A 股 fixture 走完 capture → validate → publish；发布后重修订只生成新 snapshot。
6. **Separate temporal facts**：suspension、ST、daily limits、corporate-action events、adjustment factors 分区，unknown 不转 False，raw 不预调整。
7. **PIT Universe artifact**：membership 带有效期、available time、evidence，绑定 published snapshot + cutoff，并输出 resolution-conservation audit。
8. **Behavioral admission suite**：优先落地 `PIT-001`、`INS-ID-001/003/004`、`CAL-002`、`STATUS-001/002`、`CA-003`、`ADJ-001`、`UNI-002/003`、`SRC-001`。
9. **Reuse existing planes**：snapshot/membership/audit 都走 Artifact；执行与重试走 Task；状态与证据写 Control Catalog，不新增 authority。
10. **License firewall**：研究文档只保留 pinned citations 与独立行为描述；实现人员不得从 OpenBB/RQAlpha 源码或测试复制，MIT 项目复用也必须经单独审查。

这十项不要求本研究 PR 修改任何 canonical contract 或 migration；它们是 WS-F 在现有冻结边界内的 admission 与实现优先级。
