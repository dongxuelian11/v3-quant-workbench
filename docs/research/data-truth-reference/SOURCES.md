# Data Truth / Universe OSS Reference Sources

## 研究口径

本研究只使用官方仓库、官方文档、源码、测试和许可证。所有上游链接固定到审阅时的 commit，避免默认分支后续变化把结论悄悄改写。

证据标签：

- **SOURCE**：源码直接体现的接口、状态或行为。
- **TEST**：官方测试锁定的可观察行为。
- **DOC**：官方文档声明的概念或使用方式。
- **V3**：V3 当前冻结合同、Control Catalog 或测试已经表达的约束。
- **INFERENCE**：基于多项证据提出的 V3 建议，不声称是上游原有保证。

“未发现”只表示在下列固定修订和审阅范围内没有找到可验证保证，不证明项目其他组件绝对不存在该能力。

## 修订与许可证

| Project | Reviewed revision | Current license at revision | 对 Apache-2.0 V3 的使用边界 |
|---|---|---|---|
| OpenBB | [`3e071fcc`](https://github.com/OpenBB-finance/OpenBB/tree/3e071fcc2cd9f891cac6040ae60296dba76dab46) | [GNU AGPL v3.0](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/LICENSE) | 仅学习架构与外部可观察行为；本研究不复制源码或测试。若未来拟复用任何代码，必须单独进行许可证审查。 |
| Qlib | [`79633dd9`](https://github.com/microsoft/qlib/tree/79633dd9506ea689e5400dea0197717b5b3d74b7) | [MIT](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/LICENSE) | 可学习设计；本研究仍只提炼行为，不复制实现。任何未来复用需保留 MIT 通知并经项目流程审查。 |
| RQAlpha | [`3503ab57`](https://github.com/ricequant/rqalpha/tree/3503ab57932540cd36bf8375134e52c6923bf0d2) | [Ricequant 自定义条款](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/LICENSE)：非商业条款引用 Apache-2.0，组织或商业使用要求授权，并含额外限制 | 不能把它当作普通 Apache-2.0 代码来源。本研究仅独立概括行为与失败模式，不复制代码、测试、结构化实现或受保护表达。未来任何复用必须先取得明确法律/项目许可。 |
| vn.py | [`fa5206fe`](https://github.com/vnpy/vnpy/tree/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09) | [MIT](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/LICENSE) | 可学习设计；本研究不复制实现。未来代码复用仍需保留 MIT 通知并经项目流程审查。 |
| V3 | [`d3da225d`](https://github.com/dongxuelian11/v3-quant-workbench/tree/d3da225de4132e2514c50eb0f9b83f6caada1763) | Apache-2.0 | 本研究不修改冻结合同、生产 Backend、migrations、ASL 或 UI。 |

许可证结论不是法律意见。这里的工程规则更严格：**学习设计/行为不等于复制代码**；本 PR 没有复制上游测试夹具、实现代码或文本表达。

## OpenBB 证据

- **O1 SOURCE** — [`Provider`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/openbb_core/provider/abstract/provider.py) 通过 `fetcher_dict` 声明 canonical model 到 provider fetcher 的映射。
- **O2 SOURCE** — [`Fetcher`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/openbb_core/provider/abstract/fetcher.py) 把 query transform、extract、data transform 组织成带类型的阶段。
- **O3 SOURCE** — [`QueryParams`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/openbb_core/provider/abstract/query_params.py)、[`Data`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/openbb_core/provider/abstract/data.py) 与 [`AnnotatedResult`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/openbb_core/provider/abstract/annotated_result.py) 区分标准字段、provider 扩展和结果元数据。
- **O4 SOURCE** — [`QueryExecutor`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/openbb_core/provider/query_executor.py) 对未知 provider、缺失 model/fetcher 和凭证显式报错。
- **O5 SOURCE** — [`RegistryMap`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/openbb_core/provider/registry_map.py) 生成 model/provider 能力映射及标准字段、扩展字段描述。
- **O6 SOURCE, NEGATIVE** — [`filter_extra_params`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/openbb_core/app/query.py) 会警告并丢弃不受支持的 provider 参数；[`yfinance equity historical`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/providers/yfinance/openbb_yfinance/models/equity_historical.py) 展示 provider 特有 adjustment/action 语义及依赖当前时间的默认日期。这些不适合 V3 formal truth。
- **O7 TEST** — [`Fetcher tests`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/tests/provider/abstract/test_fetcher.py)、[`QueryExecutor tests`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/tests/provider/test_query_executor.py) 和 [`RegistryMap tests`](https://github.com/OpenBB-finance/OpenBB/blob/3e071fcc2cd9f891cac6040ae60296dba76dab46/openbb_platform/core/tests/provider/test_registry_map.py) 验证阶段类型、能力发现和错误路径。

## Qlib 证据

- **Q1 SOURCE** — [`CalendarProvider`, `InstrumentProvider`, `DatasetProvider`, `PITProvider`](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/qlib/data/data.py) 把 calendar、instrument spans、dataset 访问和 PIT 访问作为一等概念。
- **Q2 SOURCE, NEGATIVE** — 同一文件中 future calendar 缺失时会警告并回退到当前 calendar；instrument cache 的键不足以表达 provider/version/frequency 全部语义。这些是 V3 不应继承的模式。
- **Q3 SOURCE** — [`instrument filters`](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/qlib/data/filter.py) 在时间序列上修改股票池；表达式若含未来引用可能导致泄漏，因此 V3 需要显式 leakage audit。
- **Q4 DOC, SOURCE, TEST** — [PIT 文档](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/docs/advanced/PIT.rst) 说明“使用最新修订”会泄漏；[`LocalPITProvider`](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/qlib/data/data.py) 依据发布日期选择修订；[`test_pit.py`](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/tests/test_pit.py) 验证值只在相应发布日期后可见。
- **Q5 SOURCE** — [`Dataset` 与 handler`](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/qlib/data/dataset/__init__.py)、[`DataHandler`](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/qlib/data/dataset/handler.py) 区分加载、处理和 train/valid/test segments。
- **Q6 DOC** — [workflow 文档](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/docs/component/workflow.rst) 将研究 market/universe 与回测 benchmark 分别配置；这是“二者不应隐式等同”的证据，不是不可变快照保证。
- **Q7 DOC, TEST** — [data layer 文档](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/docs/component/data.rst) 将股票池表达为 symbol 与生效日期区间；[`test_datalayer.py`](https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/tests/dataset_tests/test_datalayer.py) 包含数据健康 smoke checks，但 provider 差异导致断言放宽，不能充当 V3 admission proof。

## RQAlpha 证据

- **R1 SOURCE** — [`AbstractDataSource`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/interface.py) 明确 calendar、instrument、dividend、split、bars、adjustment、suspension、ST 等数据边界。
- **R2 SOURCE** — [`BaseDataSource`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/data/base_data_source/data_source.py) 分开存储 bars、dividends、splits、ex-cum factors、calendar、suspension 和 ST，并按历史区间取 instrument/factor。
- **R3 SOURCE** — [`InstrumentsMixin`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/data/instruments_mixin.py) 明确同一 `order_book_id` 可被复用，活跃 instrument 必须由标识与交易日共同确定，歧义应失败。
- **R4 SOURCE, TEST, NEGATIVE** — [`TradingDatesMixin`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/data/trading_dates_mixin.py) 区分 calendar type，但区间外 previous/next 会钳制到端点；[测试](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/tests/unittest/test_data/test_trading_dates_mixin.py) 固定了该行为。V3 应显式 unavailable，而不是沿用钳制。
- **R5 SOURCE, TEST** — [`price_limits`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/utils/price_limits.py) 使用 tick-size band 和容差；[测试](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/tests/unittest/test_utils/test_price_limits.py) 覆盖边界与向量/标量一致性。
- **R6 SOURCE, TEST** — [`matcher tests`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/tests/unittest/test_mod/test_sys_simulation/test_matcher.py) 覆盖非成交、部分成交、余量、缺失流动性、价格限制和 order state；对 WS-F 属于 future-only 行为参考。
- **R7 SOURCE, TEST** — [`position_model.py`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/mod/rqalpha_mod_sys_accounts/position_model.py) 区分股息登记/应收/支付、拆分与再投资顺序；[`account model tests`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/tests/integration_tests/test_api/mod/sys_accounts/test_account_model.py) 验证时序。源码同时承认同日多个股息不同支付日的处理假设，是重要失败模式。
- **R8 SOURCE** — [`index_components` / `index_weights`](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/rqalpha/apis/api_rqdatac.py) 带 date/as-of 约束并拒绝未来日期；实现依赖外部 `rqdatac`，因此只作为 API 行为证据，不能证明 OSS bundle 提供完整 PIT constituents。
- **R9 DOC, NEGATIVE** — [data source 文档](https://github.com/ricequant/rqalpha/blob/3503ab57932540cd36bf8375134e52c6923bf0d2/docs/source/development/data_source.rst) 描述每日更新 bundle；它是可变分发物，不是 V3 意义上的 content-addressed published snapshot。

## vn.py 证据

- **V1 SOURCE** — [`Exchange`](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/constant.py) 显式枚举 SSE、SZSE、BSE 等 venue。
- **V2 SOURCE** — [`BaseData`, `TickData`, `BarData`, `ContractData`](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/object.py) 使用 `symbol + exchange` 生成 `vt_symbol`，并保留 `gateway_name` 来源。
- **V3 SOURCE** — [`BaseGateway`](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/gateway.py) 是连接器与标准事件对象之间的边界，并声明 gateway 支持的 exchange。
- **V4 SOURCE, NEGATIVE** — [`BaseDatafeed`](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/datafeed.py) 未初始化/未实现时可能警告后返回空；[`get_database`](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/database.py) 缺少配置驱动时会回退 SQLite，且数据库时区转换后去掉时区信息。这些都不适合 formal truth。
- **V5 SOURCE, NEGATIVE** — [`OmsEngine`](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py) 以 `vt_symbol` 缓存最新对象；若多 gateway 同标识，来源不在 key 中，存在最后写入覆盖风险。
- **V6 DOC** — [gateway](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/docs/community/info/gateway.md)、[datafeed](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/docs/community/info/datafeed.md)、[database](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/docs/community/info/database.md) 文档显示 provider/gateway 覆盖范围、标识方式和历史数据能力并不一致；例如部分接口使用 provider 自身 ID，而不是交易所代码。

## V3 基线证据

- **B1 V3** — [`BACKEND_FUTURE_CONTRACT.md`](../../architecture/BACKEND_FUTURE_CONTRACT.md) 已冻结 canonical backend 边界，并要求 PIT、Universe、calendar、adjustment、suspension 等事实 fail closed。
- **B2 V3** — [`data_snapshot` contract](../../../apps/backend/src/v3_backend/contracts/data_snapshot.py)、[`universe` contract](../../../apps/backend/src/v3_backend/contracts/universe.py) 和 [`dataset` contract](../../../apps/backend/src/v3_backend/contracts/dataset.py) 已表达 pinned snapshot、knowledge cutoff、PIT 和 leakage audit 方向。
- **B3 V3** — [`Control Catalog migration`](../../../apps/backend/src/v3_backend/migrations/versions/0001_control_catalog.sql) 已有 connector capability、instrument/revision/alias、raw capture、snapshot、Universe version 等基础表。本研究不修改 migration。
- **B4 V3** — [`Artifact publication`](../../../apps/backend/src/v3_backend/domain/artifacts/publication.py)、[`Task contract`](../../../apps/backend/src/v3_backend/contracts/task.py) 与相应测试已提供 content addressing、不可变发布、Run/Attempt 语义。本研究建议复用这些既有平面，不另造权威系统。
