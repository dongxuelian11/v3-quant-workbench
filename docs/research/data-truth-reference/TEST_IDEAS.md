# V3 Data Truth / Universe Test Ideas

## 测试转译规则

这些案例只提炼上游测试的**可观察行为**，fixture、断言文本和实现均由 V3 独立编写，不复制任何上游代码。上游 evidence 见 [`SOURCES.md`](./SOURCES.md)。

测试优先级：P0 阻断 formal publication/run；P1 阻断相关 capability；P2 用于兼容性和 future contract。

| ID | Pri | V3 target | 独立 fixture / action | 必须断言的行为 | Inspiration |
|---|---:|---|---|---|---|
| DS-CAP-001 | P0 | DataSourceService / Control Catalog | connector v1 声明 bars，不声明 corporate actions；分别请求两者 | bars 可执行；actions 返回 typed `CAPABILITY_UNAVAILABLE`；不调用 adapter、不返回空成功 | O4–O5、O7 |
| DS-CAP-002 | P0 | DataSourceService | formal query 含未知 `adjust_mode` 或该 provider 不支持的 interval | hard error 包含字段与 connector version；normalized request 未生成成功 Artifact | O6 |
| DS-CAP-003 | P0 | DataSourceService / Task | 指定 source A 不可用，但 source B 可用 | 不自动改用 B；Run 失败原因和 requested source 保持可审计 | V4 |
| DS-CAP-004 | P1 | Connector admission | capability schema 声称支持字段，但 adapter transform 返回错类型/缺标准字段 | admission 失败；错误定位到 query/extract/transform stage | O2、O7 |
| INS-ID-001 | P0 | InstrumentService | provider code `000001` 在不重叠时期映射到两个 instrument | as-of 各时期解析不同永久 ID；不带 as-of 的 formal resolve 拒绝歧义 | R3 |
| INS-ID-002 | P0 | InstrumentService / Control Catalog | 两条同 connector/version/code 的 alias effective intervals 重叠 | 写入或 publication validation 失败；不能靠排序选择一个 | R3、B3 |
| INS-ID-003 | P0 | InstrumentService | alias effective_from 已生效，但 mapping 的 available_time 晚于 knowledge cutoff | cutoff 前 unresolved，cutoff 后 resolved；两次 audit 都保留 | Q4、R3 |
| INS-ID-004 | P0 | InstrumentService / UniverseService | 请求 100 个 codes，其中 96 resolved、2 ambiguous、2 absent | 四类计数总和等于 100；published formal Universe 必须按 policy 明确拒绝或保留审计，绝不返回 96 个静默成功 | O6、R3 |
| CAL-001 | P0 | DataSnapshotService | 固定一个包含周末、法定假日和正常 A 股交易日的 calendar fixture | 每个日期状态精确；calendar hash 稳定；venue/profile 明确 | Q1、R4 |
| CAL-002 | P0 | DataSourceService / Calendar | 请求早于/晚于 calendar coverage 的 previous/next session | typed unavailable；不得返回首日/末日，不得使用当前 calendar | Q2、R4 |
| CAL-003 | P1 | Dataset / Task | SSE 与另一 venue 在同一自然日 session 不同，进行 join | 未提供 alignment policy 时失败；提供 policy 后结果与 manifest 记录一致 | Q1、V1 |
| PIT-001 | P0 | DataSnapshotService | 同一 2025Q1 value 有 v1 available 05-01、v2 available 05-10 | cutoff 05-09 只见 v1，05-10 起见 v2；旧 snapshot 重跑仍为 v1 | Q4 |
| PIT-002 | P0 | DataSnapshotService | effective date 早于 cutoff，但 available time 晚于 cutoff | formal candidate validation 失败，不能仅凭 effective date 纳入 | Q4、R8 |
| PIT-003 | P0 | Snapshot / Artifact | provider 在 snapshot 发布后修订同一记录 | 旧 snapshot bytes/hash/result 不变；新修订只能形成新 candidate/version | Q4、B3–B4 |
| UNI-001 | P0 | UniverseService | A 在 `[d1,d3)`、B 在 `[d2,d4)`，membership publication times 不同 | d1/d2/d3 截面精确；knowledge cutoff 再过滤当时未知 membership | Q3、Q7、R8 |
| UNI-002 | P0 | UniverseService | 用 d5 发布的 constituents resolve d2 | future constituent 被拒绝或不可见；audit 标记 available-time violation | R8 |
| UNI-003 | P0 | UniverseService / Artifact | 同一 definition + snapshot + cutoff resolve 两次 | membership bytes、排序、manifest、hash 完全相同 | B2–B4 |
| UNI-004 | P1 | Dataset / Task | Universe 不变，benchmark 改变；反向再测 | 两者各自进入 canonical input；任一改变都产生新 Run，但不暗改另一方 | Q6 |
| UNI-005 | P0 | UniverseService | dynamic filter 在时点 t 依赖 t+2 close | static/lineage audit 阻断 publication；错误列出未来 dependency | Q3 |
| STATUS-001 | P0 | DataSnapshotService | suspension capability/partition 缺失，但 bars 存在 | formal China-A profile 不发布；不得把全体标记为 not suspended | R1–R2 |
| STATUS-002 | P0 | Dataset | 三行：正常零量、明确停牌、数据缺失 | 三种状态保持可区分；默认 materialization 不删除 calendar row | R1–R2 |
| STATUS-003 | P1 | Instrument/DataSnapshot | security 在 d2 戴帽、d4 摘帽；当前名称不含 ST | d1/d2/d4 as-of 状态精确；名称不能覆盖 status evidence | R1–R2 |
| LIMIT-001 | P0 | DataSnapshot validation | limit price、tick size、epsilon 附近各一点，标量与批量两条路径 | 两路径结果完全一致；等于边界和越界一 tick 的判断精确 | R5 |
| LIMIT-002 | P0 | Control Catalog / Snapshot | 同 code 跨制度日期使用不同 limit rule/profile | 每日 limit facts 或 rule version 正确切换；固定 10% 实现被 fixture 揭穿 | R5 |
| CA-001 | P0 | DataSnapshotService | dividend 含 announcement/record/ex/payable，另有 split | 原始 event 字段、IDs 和日期完整；factor 是独立 derived artifact | R1–R2、R7 |
| CA-002 | P1 | Future accounting contract | 同日 split + dividend payable/reinvestment | 事件排序产生预期数量/现金；改变排序测试必须失败 | R7 |
| CA-003 | P0 | Snapshot validation | 同一证券同日两个 dividend records，payable dates 不同 | 两个 event 保持独立；不可聚合成单一 payable date | R7 |
| ADJ-001 | P0 | DataSnapshotService / Dataset | raw close + factor；再把已 adjusted close 作为输入重复处理 | 一次调整得到 expected；第二次应用被 metadata/lineage 阻断 | O6、R1–R2 |
| ADJ-002 | P0 | DataSnapshotService | factor history 首段缺失 | formal adjustment unavailable；不得无 evidence 补 1 | R2 |
| ADJ-003 | P1 | Dataset | pre/post adjustment 使用同一 raw/factors 和不同 anchor | 两个 result/hash 均不同且 manifest 清楚声明 anchor/fields | O6、R1–R2 |
| SRC-001 | P0 | RawCapture / Snapshot | 两个 providers 同 symbol/timestamp 给不同 close | 两条 capture 都保留；validation 产生 disagreement；不 last-write-wins | V2、V5 |
| SRC-002 | P0 | Cache / Task | 同 vt_symbol，gateway A/B；同 market，不同 frequency/version | cache key 不碰撞；source/version/frequency 任一变化均产生不同 canonical hash | Q2、V5 |
| TIME-001 | P0 | DataSourceService / Storage | aware timestamps 跨 UTC、Asia/Shanghai，含 session date | 写入读取后 instant、timezone/venue session date 均一致；禁止无说明 naive timestamp | V4 |
| SNAP-001 | P0 | Artifact / Snapshot | 发布后尝试替换 manifest、partition bytes 或 selected revision | update 被拒；rehash/tamper test 失败并有 audit event | B3–B4 |
| SNAP-002 | P0 | Snapshot / Task | 同 request、同 connector version、同 raw captures 重跑 | candidate manifest 确定性一致；若 provider response 变更，必须因 raw hash 产生新 snapshot | B3–B4 |
| TASK-001 | P0 | Task | 同 immutable inputs 重试；然后改变 cutoff 或 calendar | 重试为同 Run 新 Attempt；任一 semantic input 变化产生新 Run | B4 |
| PROV-001 | P0 | Artifact / Snapshot | 从 published dataset 任取一行反向追踪 | 能定位 normalized partition、raw capture、request fingerprint、connector version 和 evidence hash | O3–O5、V2、B3 |
| HEALTH-001 | P1 | Snapshot admission | 总行数/收益分布正常，但一个 alias 或一个 revision 时间错误 | smoke health 通过不影响 precise invariant test 阻断 publication | Q7 |
| EXEC-001 | P2 | Future order/fill contract | suspension、limit、partial liquidity、lot size 的组合 fixture | order state、partial fill、remainder 可验证；Data Truth 只提供事实，不在 WS-F 实现 matcher | R5–R6 |

## 必做 metamorphic properties

1. **Cutoff monotonicity**：knowledge cutoff 向后移动只能增加当时可得 revisions/memberships；不能改变更早 published snapshot。
2. **Provider permutation invariance**：capture 输入顺序变化不能改变 canonical manifest；冲突仍产生相同 validation findings。
3. **Adjustment single-application**：明确 raw 输入可被调整一次；任何已调整输入再次进入同 spec 都必须拒绝，而不是得到另一个“看似连续”的序列。
4. **Resolution conservation**：requested 数量始终等于 resolved + unresolved + ambiguous + explicitly excluded。
5. **Publication immutability**：发布前可产生新 candidate，发布后相同 version 的 bytes/hash/selection 永不变化。
6. **Source non-substitutability**：requested connector/version 不可用时，加入另一个可用 connector 不会把失败变成功。
7. **Calendar coverage**：扩大 calendar artifact coverage 可以让原 unavailable query 成功，但不得改变旧 coverage 内的 session definitions，除非发布新 calendar version。

## 分层执行建议

- **Unit/property**：alias intervals、time axes、calendar boundary、factor math、limit tick boundary、canonical hashing。
- **Contract**：capability unavailable、query strictness、resolution audit、snapshot state machine、Universe publication。
- **Fixture integration**：小型人工 A 股历史，包含 code reuse、ST、suspension、limit rule change、dividend + split、constituent revision。
- **Provider conformance**：每个 connector version 跑同一行为套件；不能用 provider-specific 宽松阈值替代 formal assertions。
- **Golden replay**：只对 V3 自有小 fixture 固定 hash/result；不导入上游数据包或测试样本。
