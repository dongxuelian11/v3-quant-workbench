import type { AgentStatementView, ArtifactView, EvidenceView, ResearchSessionView, TimelineEntryView } from "./agentWorkspace";

const hex = (character: string) => character.repeat(64);
const artifact = (character: string) => `art_sha256_${hex(character)}`;

export const researchSessions: ResearchSessionView[] = [
  {
    sessionViewId: "session-view-momentum-pit-001",
    title: "动量因子的 PIT 稳健性",
    goal: "验证因子证据能否通过时点与修订检查。",
    status: "PENDING",
    linkedExperimentRunId: `exprun_sha256_${hex("4")}`,
    linkedTaskId: "Task_01JTRACKKDEMO000000000001",
    lastEvidenceUpdate: "2026-08-11 16:12 CST",
    evidenceIds: [`dsv_sha256_${hex("2")}`, `fev_sha256_${hex("3")}`, `exprun_sha256_${hex("4")}`, `expatt_sha256_${hex("5")}`, `rwv_sha256_${hex("6")}`, `rve_sha256_${hex("c")}`]
  },
  {
    sessionViewId: "session-view-provider-revision-002",
    title: "数据提供器修订审计",
    goal: "检查 A 股日线切片的可用时间、修订与来源缺口。",
    status: "BLOCKED",
    linkedExperimentRunId: null,
    linkedTaskId: "Task_01JTRACKKDEMO000000000002",
    lastEvidenceUpdate: "2026-08-11 15:47 CST",
    evidenceIds: [`snp_sha256_${hex("1")}`, `dsv_sha256_${hex("2")}`]
  },
  {
    sessionViewId: "session-view-signal-lineage-003",
    title: "信号来源链审阅",
    goal: "把策略草案信号追溯到模型、数据集与评审证据。",
    status: "DRAFT",
    linkedExperimentRunId: `exprun_sha256_${hex("4")}`,
    linkedTaskId: null,
    lastEvidenceUpdate: "2026-08-11 14:30 CST",
    evidenceIds: [`exprun_sha256_${hex("4")}`, `mdv_sha256_${hex("7")}`, `pred_sha256_${hex("8")}`, `sdv_sha256_${hex("9")}`, `sig_sha256_${hex("a")}`, `pint_sha256_${hex("b")}`]
  },
  {
    sessionViewId: "session-view-empty-004",
    title: "未绑定证据接收区",
    goal: "在精确证据链接进入此派生会话视图前保持工作区为空。",
    status: "DRAFT",
    linkedExperimentRunId: null,
    linkedTaskId: null,
    lastEvidenceUpdate: "未绑定证据",
    evidenceIds: []
  }
];

export const agentStatements: AgentStatementView[] = [
  {
    id: "draft-research-001", sessionViewId: "session-view-momentum-pit-001", role: "RESEARCH", type: "RESEARCH_DRAFT", authorityStatus: "NON_CANONICAL", lifecycleState: "DRAFT", permission: "L1_DRAFT",
    title: "研究计划草案",
    body: "以精确 DatasetVersion 与 FactorEvaluation 检验 12 月动量定义；若可用时间或评审证据不完整则停止。",
    evidenceIds: [`dsv_sha256_${hex("2")}`, `fev_sha256_${hex("3")}`]
  },
  {
    id: "draft-data-002", sessionViewId: "session-view-provider-revision-002", role: "DATA", type: "DATA_REVIEW_FINDINGS", authorityStatus: "NON_CANONICAL", lifecycleState: "DRAFT", permission: "L1_DRAFT",
    title: "数据发现",
    body: "开发数据 · fixture 暴露修订警告并保持验证状态为 NOT_RUN；该陈述不能提高上游真值上限。",
    evidenceIds: [`snp_sha256_${hex("1")}`, `dsv_sha256_${hex("2")}`]
  },
  {
    id: "draft-reviewer-003", sessionViewId: "session-view-momentum-pit-001", role: "REVIEWER", type: "REVIEWER_FINDINGS", authorityStatus: "NON_CANONICAL", lifecycleState: "DRAFT", permission: "L1_DRAFT",
    title: "评审发现",
    body: "多重检验稳健性仍为 NOT_RUN，因此结论保持 PRE_ALPHA 且不可发布。",
    evidenceIds: [`rve_sha256_${hex("c")}`, `rwv_sha256_${hex("6")}`]
  },
  {
    id: "draft-data-004", sessionViewId: "session-view-momentum-pit-001", role: "DATA", type: "DATA_REVIEW_FINDINGS", authorityStatus: "NON_CANONICAL", lifecycleState: "DRAFT", permission: "L1_DRAFT",
    title: "数据集范围发现",
    body: "DatasetVersion 已显式绑定到当前动量会话；提供器快照证据仍在活动范围之外。",
    evidenceIds: [`dsv_sha256_${hex("2")}`]
  },
  {
    id: "draft-research-005", sessionViewId: "session-view-signal-lineage-003", role: "RESEARCH", type: "RESEARCH_DRAFT", authorityStatus: "NON_CANONICAL", lifecycleState: "DRAFT", permission: "L1_DRAFT",
    title: "信号来源链草案",
    body: "追溯精确的模型、预测、策略、信号与意图对象，但不得把 PortfolioIntent 提升为权重或执行。",
    evidenceIds: [`mdv_sha256_${hex("7")}`, `pred_sha256_${hex("8")}`, `sig_sha256_${hex("a")}`, `pint_sha256_${hex("b")}`]
  }
];

const evidence = (
  kind: EvidenceView["kind"], objectId: string, title: string, summary: string,
  truth: EvidenceView["canonicalTruthState"], admission: EvidenceView["canonicalAdmissionState"], validation: EvidenceView["validationState"],
  provenanceRefs: string[], reviewerFinding: string | null, facts: EvidenceView["facts"], openInLab: EvidenceView["openInLab"], artifactId: string | null
): EvidenceView => ({ kind, objectId, title, summary, canonicalTruthState: truth, canonicalAdmissionState: admission, validationState: validation, provenanceRefs, reviewerFinding, facts, openInLab, artifactId });

export const evidenceViews: EvidenceView[] = [
  evidence("Truth / Admission", `snp_sha256_${hex("1")}`, "A 股日线快照", "通过仅限开发的数据 · fixture 呈现 current-main Data Truth 对象。", "NOT_FORMAL", "PRE_ALPHA", "NOT_RUN", [artifact("d")], "REVISION / WARNING", [
    { label: "数据提供器", value: "AKShare 适配器元数据" }, { label: "可用时间", value: "2026-06-30T15:05:00+08:00" }, { label: "修订状态", value: "UNKNOWN / 需要审阅" }
  ], "research", artifact("d")),
  evidence("DatasetVersion", `dsv_sha256_${hex("2")}`, "中国日线因子数据集", "精确 DatasetVersion 身份及其继承的真值上限。", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("d"), artifact("e")], null, [
    { label: "特征集", value: `fsv_sha256_${hex("2")}` }, { label: "切分", value: `spl_sha256_${hex("2")}` }, { label: "行数", value: "1,248,320（开发数据 · fixture）" }
  ], "research", artifact("e")),
  evidence("FactorEvaluation", `fev_sha256_${hex("3")}`, "12 月动量评估", "因子评估绑定到精确数据集上下文与输出 Artifact。", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("e"), artifact("f")], null, [
    { label: "定义版本", value: `fdv_sha256_${hex("3")}` }, { label: "物化版本", value: `fmat_sha256_${hex("3")}` }
  ], "research", artifact("f")),
  evidence("Experiment Run", `exprun_sha256_${hex("4")}`, "动量稳健性运行", "ExperimentRun 身份与尝试及结果证据相互独立。", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("f"), artifact("4")], null, [
    { label: "代码版本", value: "track-k-fixture@f88b0ebe" }, { label: "环境", value: "CURRENT_MAIN_VIEW_MODEL" }
  ], "research", artifact("4")),
  evidence("Experiment Attempt", `expatt_sha256_${hex("5")}`, "第 1 次尝试", "成功的开发数据尝试，具备不可变结果链接；不代表实时执行。", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("5")], null, [
    { label: "状态", value: "SUCCEEDED" }, { label: "序号", value: "1" }
  ], "research", artifact("5")),
  evidence("RewardVector", `rwv_sha256_${hex("6")}`, "奖励向量 · RewardVector", "结构化指标仍受运行与评审真值上限约束。", "NOT_FORMAL", "PRE_ALPHA", "NOT_RUN", [artifact("6")], "MULTIPLE_TESTING_RISK / NOT_RUN", [
    { label: "IC", value: "0.047" }, { label: "秩 IC", value: "0.061" }, { label: "换手率", value: "0.34" }
  ], "result", artifact("6")),
  evidence("ModelVersion", `mdv_sha256_${hex("7")}`, "安全线性模型", "ModelVersion 作为 current-main 只读证据呈现。", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("7")], null, [
    { label: "训练规范", value: `trspec_sha256_${hex("7")}` }, { label: "运行时", value: `mrt_sha256_${hex("7")}` }
  ], "model", artifact("7")),
  evidence("PredictionArtifact", `pred_sha256_${hex("8")}`, "预测产物 · PredictionArtifact", "PredictionArtifact 保留精确 ModelVersion 与 DatasetVersion 来源链。", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("7"), artifact("8")], null, [
    { label: "模型", value: `mdv_sha256_${hex("7")}` }, { label: "数据集", value: `dsv_sha256_${hex("2")}` }
  ], "model", artifact("8")),
  evidence("StrategyDefinition", `sdv_sha256_${hex("9")}`, "动量策略定义", "策略定义与评估绑定及产物保持分离。", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("9")], null, [
    { label: "注册表", value: `screg_sha256_${hex("9")}` }, { label: "发布状态", value: "UNPUBLISHED" }
  ], "strategy", artifact("9")),
  evidence("SignalArtifact", `sig_sha256_${hex("a")}`, "信号产物 · SignalArtifact", "信号来源链可见，但不会把智能体草案提升为 canonical 证据。", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("8"), artifact("a")], null, [
    { label: "策略", value: `sdv_sha256_${hex("9")}` }, { label: "预测", value: `pred_sha256_${hex("8")}` }
  ], "strategy", artifact("a")),
  evidence("PortfolioIntent", `pint_sha256_${hex("b")}`, "组合意图 · PortfolioIntent", "仅为意图；不是 TargetWeightVector、风险结果、订单、成交或执行。", "NOT_FORMAL", "PRE_ALPHA", "NOT_RUN", [artifact("a"), artifact("b")], "TARGET_WEIGHT / FUTURE SLOT", [
    { label: "来源信号", value: `sig_sha256_${hex("a")}` }, { label: "目标权重 · TargetWeightVector", value: "NOT_CONNECTED" }
  ], "strategy", artifact("b")),
  evidence("Reviewer Findings", `rve_sha256_${hex("c")}`, "实验评审证据", "Reviewer 检查分别保留 PASS、FAIL 与 NOT_RUN 状态。", "NOT_FORMAL", "PRE_ALPHA", "NOT_RUN", [artifact("c")], "MULTIPLE_TESTING_RISK / BLOCKING_EVIDENCE", [
    { label: "前视偏差", value: "PASS" }, { label: "泄漏", value: "PASS" }, { label: "多重检验", value: "NOT_RUN" }
  ], "result", artifact("c"))
];

export const timelineEntries: TimelineEntryView[] = [
  { id: "tl-01", sessionViewId: "session-view-momentum-pit-001", authority: "AGENT", state: "DRAFT", title: "已提出研究草案", detail: "L1_DRAFT · NON_CANONICAL", objectId: "draft-research-001", at: "16:01:04" },
  { id: "tl-02", sessionViewId: "session-view-momentum-pit-001", authority: "PLAN", state: "PENDING", title: "PIT 证据计划", detail: "等待精确修订审阅", objectId: null, at: "16:01:06" },
  { id: "tl-03", sessionViewId: "session-view-momentum-pit-001", authority: "TOOL", state: "READ", title: "读取数据集版本 · get_dataset_version", detail: "可信工具绑定 · TrustedToolBindings · 只读", objectId: `dsv_sha256_${hex("2")}`, at: "16:01:09" },
  { id: "tl-04", sessionViewId: "session-view-momentum-pit-001", authority: "TASK", state: "QUEUED", title: "证据检索任务", detail: "任务状态保持 QUEUED", objectId: "Task_01JTRACKKDEMO000000000001", at: "16:01:10" },
  { id: "tl-05", sessionViewId: "session-view-momentum-pit-001", authority: "EXPERIMENT", state: "SUCCEEDED", title: "第 1 次实验尝试", detail: "已绑定开发数据结果；没有实时执行", objectId: `expatt_sha256_${hex("5")}`, at: "16:07:42" },
  { id: "tl-06", sessionViewId: "session-view-momentum-pit-001", authority: "EVIDENCE", state: "PRE_ALPHA", title: "证据已就绪", detail: "NOT_FORMAL / PRE_ALPHA", objectId: `rwv_sha256_${hex("6")}`, at: "16:08:03" },
  { id: "tl-07", sessionViewId: "session-view-momentum-pit-001", authority: "REVIEWER", state: "BLOCKED", title: "多重检验证据", detail: "BLOCKING_EVIDENCE", objectId: `rve_sha256_${hex("c")}`, at: "16:10:21" },
  { id: "tl-08", sessionViewId: "session-view-momentum-pit-001", authority: "VALIDATION", state: "NOT_RUN", title: "正式准入验证", detail: "不声明 PASS", objectId: null, at: "16:10:22" },
  { id: "tl-09", sessionViewId: "session-view-provider-revision-002", authority: "AGENT", state: "DRAFT", title: "数据提供器审计发现", detail: "L1_DRAFT · NON_CANONICAL", objectId: "draft-data-002", at: "15:42:04" },
  { id: "tl-10", sessionViewId: "session-view-provider-revision-002", authority: "TOOL", state: "READ", title: "读取快照 · get_snapshot", detail: "可信工具绑定 · TrustedToolBindings · 只读", objectId: `snp_sha256_${hex("1")}`, at: "15:42:08" },
  { id: "tl-11", sessionViewId: "session-view-provider-revision-002", authority: "TASK", state: "BLOCKED", title: "修订确认", detail: "任务保持 BLOCKED", objectId: "Task_01JTRACKKDEMO000000000002", at: "15:47:00" },
  { id: "tl-12", sessionViewId: "session-view-provider-revision-002", authority: "VALIDATION", state: "NOT_RUN", title: "提供器准入验证", detail: "不声明 PASS", objectId: null, at: "15:47:02" },
  { id: "tl-13", sessionViewId: "session-view-signal-lineage-003", authority: "AGENT", state: "DRAFT", title: "已提出信号来源链", detail: "L1_DRAFT · NON_CANONICAL", objectId: "draft-research-005", at: "14:21:10" },
  { id: "tl-14", sessionViewId: "session-view-signal-lineage-003", authority: "TOOL", state: "READ", title: "读取预测产物 · get_prediction_artifact", detail: "可信工具绑定 · TrustedToolBindings · 只读", objectId: `pred_sha256_${hex("8")}`, at: "14:22:15" },
  { id: "tl-15", sessionViewId: "session-view-signal-lineage-003", authority: "EVIDENCE", state: "PRE_ALPHA", title: "组合意图已就绪", detail: "仅为意图 / 无权重", objectId: `pint_sha256_${hex("b")}`, at: "14:30:00" }
];

export const artifactViews: ArtifactView[] = [
  { artifactId: artifact("e"), title: "数据集身份", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("e"), payload: { renderer: "details", entries: [{ label: "数据集版本 ID · dataset_version_id", value: `dsv_sha256_${hex("2")}` }, { label: "特征集版本 ID · feature_set_version_id", value: `fsv_sha256_${hex("2")}` }, { label: "真值上限 · truth_ceiling", value: "NOT_FORMAL / PRE_ALPHA" }] } },
  { artifactId: artifact("f"), title: "因子评估摘要", mediaType: "application/vnd.v3.metrics+json", provenanceRef: artifact("f"), payload: { renderer: "metric", metrics: [{ label: "评估", value: "PASSED" }, { label: "准入", value: "PRE_ALPHA" }, { label: "正式验证", value: "NOT_RUN" }] } },
  { artifactId: artifact("4"), title: "实验运行标识 · Experiment run identity", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("4"), payload: { renderer: "details", entries: [{ label: "实验运行 ID · experiment_run_id", value: `exprun_sha256_${hex("4")}` }, { label: "代码版本 · code_version", value: "track-k-fixture@f88b0ebe" }, { label: "执行边界 · execution", value: "FIXTURE_ONLY / NO LIVE RUN" }] } },
  { artifactId: artifact("5"), title: "实验尝试 · Experiment attempt", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("5"), payload: { renderer: "details", entries: [{ label: "实验尝试 ID · experiment_attempt_id", value: `expatt_sha256_${hex("5")}` }, { label: "状态 · state", value: "SUCCEEDED" }, { label: "声明边界 · claim_boundary", value: "FIXTURE RESULT / NOT LIVE EXECUTION" }] } },
  { artifactId: artifact("6"), title: "奖励向量指标 · RewardVector", mediaType: "application/vnd.v3.metrics+json", provenanceRef: artifact("6"), payload: { renderer: "metric", metrics: [{ label: "IC", value: "0.047" }, { label: "秩 IC", value: "0.061" }, { label: "换手率", value: "0.34" }] } },
  { artifactId: artifact("7"), title: "模型来源链 · Model lineage", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("7"), payload: { renderer: "details", entries: [{ label: "模型版本 ID · model_version_id", value: `mdv_sha256_${hex("7")}` }, { label: "训练规范 ID · training_spec_id", value: `trspec_sha256_${hex("7")}` }, { label: "准入 · admission", value: "PRE_ALPHA" }] } },
  { artifactId: artifact("8"), title: "预测来源链 · Prediction lineage", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("8"), payload: { renderer: "details", entries: [{ label: "预测产物 ID · prediction_artifact_id", value: `pred_sha256_${hex("8")}` }, { label: "模型版本 ID · model_version_id", value: `mdv_sha256_${hex("7")}` }, { label: "数据集版本 ID · dataset_version_id", value: `dsv_sha256_${hex("2")}` }] } },
  { artifactId: artifact("c"), title: "评审检查矩阵", mediaType: "application/vnd.v3.table+json", provenanceRef: artifact("c"), payload: { renderer: "table", columns: ["检查", "状态", "发现"], rows: [["前视偏差", "PASS", "—"], ["泄漏", "PASS", "—"], ["多重检验", "NOT_RUN", "BLOCKING_EVIDENCE"]] } },
  { artifactId: artifact("d"), title: "提供器来源 · Provider provenance", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("d"), payload: { renderer: "details", entries: [{ label: "提供器 · provider", value: "AKShare 适配器元数据" }, { label: "可用时间 · available_time", value: "2026-06-30T15:05:00+08:00" }, { label: "修订 · revision", value: "UNKNOWN" }] } },
  { artifactId: artifact("9"), title: "策略定义说明", mediaType: "text/plain", provenanceRef: artifact("9"), payload: { renderer: "text", text: "未发布 · UNPUBLISHED StrategyDefinitionVersion 开发数据。请在策略实验室中进行专业检查。" } },
  { artifactId: artifact("a"), title: "信号来源链 · Signal lineage", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("a"), payload: { renderer: "details", entries: [{ label: "信号产物 ID · signal_artifact_id", value: `sig_sha256_${hex("a")}` }, { label: "策略定义 ID · strategy_definition_id", value: `sdv_sha256_${hex("9")}` }, { label: "预测产物 ID · prediction_artifact_id", value: `pred_sha256_${hex("8")}` }] } },
  { artifactId: artifact("b"), title: "组合意图边界", mediaType: "text/plain", provenanceRef: artifact("b"), payload: { renderer: "text", text: "仅为 PortfolioIntent。目标权重、风险结果、订单、成交与执行均保持 NOT_CONNECTED。" } },
  { artifactId: "future-chart-slot", title: "图表渲染器", mediaType: "application/vnd.v3.future-slot", provenanceRef: "NOT_CONNECTED", payload: { renderer: "chart", availability: "FUTURE_SLOT", reason: "已预留获准 schema；尚未连接 current-main 传输 payload。" } },
  { artifactId: "future-backtest-result-slot", title: "回测 / 结果渲染器", mediaType: "application/vnd.v3.future-slot", provenanceRef: "NOT_CONNECTED", payload: { renderer: "backtest-result", availability: "FUTURE_SLOT", reason: "Track K 不声明 Track H/I/J 集成已连接。" } }
];
