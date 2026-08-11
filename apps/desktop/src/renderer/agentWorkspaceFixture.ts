import type { AgentStatementView, ArtifactView, EvidenceView, ResearchSessionView, TimelineEntryView } from "./agentWorkspace";

const hex = (character: string) => character.repeat(64);
const artifact = (character: string) => `art_sha256_${hex(character)}`;

export const researchSessions: ResearchSessionView[] = [
  {
    sessionViewId: "session-view-momentum-pit-001",
    title: "Momentum PIT robustness",
    goal: "Verify whether factor evidence survives point-in-time and revision checks.",
    status: "PENDING",
    linkedExperimentRunId: `exprun_sha256_${hex("4")}`,
    linkedTaskId: "Task_01JTRACKKDEMO000000000001",
    lastEvidenceUpdate: "2026-08-11 16:12 CST",
    evidenceIds: [`dsv_sha256_${hex("2")}`, `fev_sha256_${hex("3")}`, `exprun_sha256_${hex("4")}`, `rve_sha256_${hex("c")}`]
  },
  {
    sessionViewId: "session-view-provider-revision-002",
    title: "Provider revision audit",
    goal: "Inspect available-time, revision, and provenance gaps for the A-share daily slice.",
    status: "BLOCKED",
    linkedExperimentRunId: null,
    linkedTaskId: "Task_01JTRACKKDEMO000000000002",
    lastEvidenceUpdate: "2026-08-11 15:47 CST",
    evidenceIds: [`snp_sha256_${hex("1")}`, `dsv_sha256_${hex("2")}`]
  },
  {
    sessionViewId: "session-view-signal-lineage-003",
    title: "Signal lineage review",
    goal: "Trace the draft strategy signal to model, dataset, and reviewer evidence.",
    status: "DRAFT",
    linkedExperimentRunId: `exprun_sha256_${hex("4")}`,
    linkedTaskId: null,
    lastEvidenceUpdate: "2026-08-11 14:30 CST",
    evidenceIds: [`mdv_sha256_${hex("7")}`, `pred_sha256_${hex("8")}`, `sdv_sha256_${hex("9")}`, `sig_sha256_${hex("a")}`, `pint_sha256_${hex("b")}`]
  }
];

export const agentStatements: AgentStatementView[] = [
  {
    id: "draft-research-001", role: "RESEARCH", type: "RESEARCH_DRAFT", authorityStatus: "NON_CANONICAL", lifecycleState: "DRAFT", permission: "L1_DRAFT",
    title: "Research plan draft",
    body: "Test the 12-month momentum definition against the exact DatasetVersion and FactorEvaluation, then stop if available-time or reviewer evidence is incomplete.",
    evidenceIds: [`dsv_sha256_${hex("2")}`, `fev_sha256_${hex("3")}`]
  },
  {
    id: "draft-data-002", role: "DATA", type: "DATA_REVIEW_FINDINGS", authorityStatus: "NON_CANONICAL", lifecycleState: "DRAFT", permission: "L1_DRAFT",
    title: "Data finding",
    body: "The fixture exposes a revision warning and keeps validation at NOT_RUN. This statement cannot raise the upstream truth ceiling.",
    evidenceIds: [`snp_sha256_${hex("1")}`, `dsv_sha256_${hex("2")}`]
  },
  {
    id: "draft-reviewer-003", role: "REVIEWER", type: "REVIEWER_FINDINGS", authorityStatus: "NON_CANONICAL", lifecycleState: "DRAFT", permission: "L1_DRAFT",
    title: "Reviewer finding",
    body: "Multiple-testing robustness remains NOT_RUN, so the conclusion remains PRE_ALPHA and is not publishable.",
    evidenceIds: [`rve_sha256_${hex("c")}`, `rwv_sha256_${hex("6")}`]
  }
];

const evidence = (
  kind: EvidenceView["kind"], objectId: string, title: string, summary: string,
  truth: EvidenceView["canonicalTruthState"], admission: EvidenceView["canonicalAdmissionState"], validation: EvidenceView["validationState"],
  provenanceRefs: string[], reviewerFinding: string | null, facts: EvidenceView["facts"], openInLab: EvidenceView["openInLab"], artifactId: string | null
): EvidenceView => ({ kind, objectId, title, summary, canonicalTruthState: truth, canonicalAdmissionState: admission, validationState: validation, provenanceRefs, reviewerFinding, facts, openInLab, artifactId });

export const evidenceViews: EvidenceView[] = [
  evidence("Truth / Admission", `snp_sha256_${hex("1")}`, "A-share daily snapshot", "Current-main Data Truth object rendered through a development-only fixture.", "NOT_FORMAL", "PRE_ALPHA", "NOT_RUN", [artifact("d")], "REVISION / WARNING", [
    { label: "Provider", value: "AKShare adapter metadata" }, { label: "Available time", value: "2026-06-30T15:05:00+08:00" }, { label: "Revision", value: "UNKNOWN / review required" }
  ], "research", artifact("d")),
  evidence("DatasetVersion", `dsv_sha256_${hex("2")}`, "CN daily factor dataset", "Exact DatasetVersion identity with its inherited truth ceiling.", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("d"), artifact("e")], null, [
    { label: "Feature set", value: `fsv_sha256_${hex("2")}` }, { label: "Split", value: `spl_sha256_${hex("2")}` }, { label: "Rows", value: "1,248,320 (fixture)" }
  ], "research", artifact("e")),
  evidence("FactorEvaluation", `fev_sha256_${hex("3")}`, "Momentum 12M evaluation", "Factor evaluation bound to the exact dataset context and output Artifact.", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("e"), artifact("f")], null, [
    { label: "Definition", value: `fdv_sha256_${hex("3")}` }, { label: "Materialization", value: `fmat_sha256_${hex("3")}` }
  ], "research", artifact("f")),
  evidence("Experiment Run", `exprun_sha256_${hex("4")}`, "Momentum robustness run", "ExperimentRun identity is separate from its attempts and result evidence.", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("f"), artifact("4")], null, [
    { label: "Code version", value: "track-k-fixture@f88b0ebe" }, { label: "Environment", value: "CURRENT_MAIN_VIEW_MODEL" }
  ], "research", artifact("4")),
  evidence("Experiment Attempt", `expatt_sha256_${hex("5")}`, "Attempt 1", "A succeeded fixture attempt with immutable result linkage; not a live execution claim.", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("5")], null, [
    { label: "State", value: "SUCCEEDED" }, { label: "Ordinal", value: "1" }
  ], "research", artifact("5")),
  evidence("RewardVector", `rwv_sha256_${hex("6")}`, "Reward vector", "Structured metrics remain bounded by run and reviewer truth ceilings.", "NOT_FORMAL", "PRE_ALPHA", "NOT_RUN", [artifact("6")], "MULTIPLE_TESTING_RISK / NOT_RUN", [
    { label: "IC", value: "0.047" }, { label: "Rank IC", value: "0.061" }, { label: "Turnover", value: "0.34" }
  ], "result", artifact("6")),
  evidence("ModelVersion", `mdv_sha256_${hex("7")}`, "Safe linear model", "ModelVersion is rendered as read-only current-main evidence.", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("7")], null, [
    { label: "Training spec", value: `trspec_sha256_${hex("7")}` }, { label: "Runtime", value: `mrt_sha256_${hex("7")}` }
  ], "model", artifact("7")),
  evidence("PredictionArtifact", `pred_sha256_${hex("8")}`, "Prediction artifact", "PredictionArtifact retains exact ModelVersion and DatasetVersion lineage.", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("7"), artifact("8")], null, [
    { label: "Model", value: `mdv_sha256_${hex("7")}` }, { label: "Dataset", value: `dsv_sha256_${hex("2")}` }
  ], "model", artifact("8")),
  evidence("StrategyDefinition", `sdv_sha256_${hex("9")}`, "Momentum strategy definition", "Strategy definition stays separate from evaluation binding and artifacts.", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("9")], null, [
    { label: "Registry", value: `screg_sha256_${hex("9")}` }, { label: "Publication", value: "UNPUBLISHED" }
  ], "strategy", artifact("9")),
  evidence("SignalArtifact", `sig_sha256_${hex("a")}`, "Signal artifact", "Signal lineage is visible without promoting the Agent draft to canonical evidence.", "NOT_FORMAL", "PRE_ALPHA", "PASSED", [artifact("8"), artifact("a")], null, [
    { label: "Strategy", value: `sdv_sha256_${hex("9")}` }, { label: "Prediction", value: `pred_sha256_${hex("8")}` }
  ], "strategy", artifact("a")),
  evidence("PortfolioIntent", `pint_sha256_${hex("b")}`, "Portfolio intent", "Intent only; it is not a TargetWeightVector, risk result, order, fill, or execution.", "NOT_FORMAL", "PRE_ALPHA", "NOT_RUN", [artifact("a"), artifact("b")], "TARGET_WEIGHT / FUTURE SLOT", [
    { label: "Source signal", value: `sig_sha256_${hex("a")}` }, { label: "TargetWeightVector", value: "NOT_CONNECTED" }
  ], "strategy", artifact("b")),
  evidence("Reviewer Findings", `rve_sha256_${hex("c")}`, "Experiment reviewer evidence", "Reviewer checks preserve individual PASS, FAIL, and NOT_RUN states.", "NOT_FORMAL", "PRE_ALPHA", "NOT_RUN", [artifact("c")], "MULTIPLE_TESTING_RISK / BLOCKING_EVIDENCE", [
    { label: "Look-ahead", value: "PASS" }, { label: "Leakage", value: "PASS" }, { label: "Multiple testing", value: "NOT_RUN" }
  ], "result", artifact("c"))
];

export const timelineEntries: TimelineEntryView[] = [
  { id: "tl-01", authority: "AGENT", state: "DRAFT", title: "Research draft proposed", detail: "L1_DRAFT · NON_CANONICAL", objectId: "draft-research-001", at: "16:01:04" },
  { id: "tl-02", authority: "PLAN", state: "PENDING", title: "PIT evidence plan", detail: "Await exact revision review", objectId: null, at: "16:01:06" },
  { id: "tl-03", authority: "TOOL", state: "READ", title: "get_dataset_version", detail: "TrustedToolBindings · read only", objectId: `dsv_sha256_${hex("2")}`, at: "16:01:09" },
  { id: "tl-04", authority: "TASK", state: "QUEUED", title: "Evidence retrieval task", detail: "Task state remains QUEUED", objectId: "Task_01JTRACKKDEMO000000000001", at: "16:01:10" },
  { id: "tl-05", authority: "EXPERIMENT", state: "SUCCEEDED", title: "Experiment Attempt 1", detail: "Fixture result linked; no live execution", objectId: `expatt_sha256_${hex("5")}`, at: "16:07:42" },
  { id: "tl-06", authority: "EVIDENCE", state: "PRE_ALPHA", title: "Evidence ready", detail: "NOT_FORMAL / PRE_ALPHA", objectId: `rwv_sha256_${hex("6")}`, at: "16:08:03" },
  { id: "tl-07", authority: "REVIEWER", state: "BLOCKED", title: "Multiple-testing evidence", detail: "BLOCKING_EVIDENCE", objectId: `rve_sha256_${hex("c")}`, at: "16:10:21" },
  { id: "tl-08", authority: "VALIDATION", state: "NOT_RUN", title: "Formal admission validation", detail: "No PASS claim", objectId: null, at: "16:10:22" }
];

export const artifactViews: ArtifactView[] = [
  { artifactId: artifact("e"), title: "Dataset identity", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("e"), payload: { renderer: "details", entries: [{ label: "dataset_version_id", value: `dsv_sha256_${hex("2")}` }, { label: "feature_set_version_id", value: `fsv_sha256_${hex("2")}` }, { label: "truth_ceiling", value: "NOT_FORMAL / PRE_ALPHA" }] } },
  { artifactId: artifact("f"), title: "Factor evaluation summary", mediaType: "application/vnd.v3.metrics+json", provenanceRef: artifact("f"), payload: { renderer: "metric", metrics: [{ label: "Evaluation", value: "PASSED" }, { label: "Admission", value: "PRE_ALPHA" }, { label: "Formal validation", value: "NOT_RUN" }] } },
  { artifactId: artifact("4"), title: "Experiment run identity", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("4"), payload: { renderer: "details", entries: [{ label: "experiment_run_id", value: `exprun_sha256_${hex("4")}` }, { label: "code_version", value: "track-k-fixture@f88b0ebe" }, { label: "execution", value: "FIXTURE_ONLY / NO LIVE RUN" }] } },
  { artifactId: artifact("5"), title: "Experiment attempt", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("5"), payload: { renderer: "details", entries: [{ label: "experiment_attempt_id", value: `expatt_sha256_${hex("5")}` }, { label: "state", value: "SUCCEEDED" }, { label: "claim_boundary", value: "FIXTURE RESULT / NOT LIVE EXECUTION" }] } },
  { artifactId: artifact("6"), title: "RewardVector metrics", mediaType: "application/vnd.v3.metrics+json", provenanceRef: artifact("6"), payload: { renderer: "metric", metrics: [{ label: "IC", value: "0.047" }, { label: "Rank IC", value: "0.061" }, { label: "Turnover", value: "0.34" }] } },
  { artifactId: artifact("7"), title: "Model lineage", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("7"), payload: { renderer: "details", entries: [{ label: "model_version_id", value: `mdv_sha256_${hex("7")}` }, { label: "training_spec_id", value: `trspec_sha256_${hex("7")}` }, { label: "admission", value: "PRE_ALPHA" }] } },
  { artifactId: artifact("8"), title: "Prediction lineage", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("8"), payload: { renderer: "details", entries: [{ label: "prediction_artifact_id", value: `pred_sha256_${hex("8")}` }, { label: "model_version_id", value: `mdv_sha256_${hex("7")}` }, { label: "dataset_version_id", value: `dsv_sha256_${hex("2")}` }] } },
  { artifactId: artifact("c"), title: "Reviewer check matrix", mediaType: "application/vnd.v3.table+json", provenanceRef: artifact("c"), payload: { renderer: "table", columns: ["Check", "State", "Finding"], rows: [["Look-ahead", "PASS", "—"], ["Leakage", "PASS", "—"], ["Multiple testing", "NOT_RUN", "BLOCKING_EVIDENCE"]] } },
  { artifactId: artifact("d"), title: "Provider provenance", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("d"), payload: { renderer: "details", entries: [{ label: "provider", value: "AKShare adapter metadata" }, { label: "available_time", value: "2026-06-30T15:05:00+08:00" }, { label: "revision", value: "UNKNOWN" }] } },
  { artifactId: artifact("9"), title: "Strategy definition note", mediaType: "text/plain", provenanceRef: artifact("9"), payload: { renderer: "text", text: "UNPUBLISHED StrategyDefinitionVersion fixture. Open in Strategy Lab for professional inspection." } },
  { artifactId: artifact("a"), title: "Signal lineage", mediaType: "application/vnd.v3.details+json", provenanceRef: artifact("a"), payload: { renderer: "details", entries: [{ label: "signal_artifact_id", value: `sig_sha256_${hex("a")}` }, { label: "strategy_definition_id", value: `sdv_sha256_${hex("9")}` }, { label: "prediction_artifact_id", value: `pred_sha256_${hex("8")}` }] } },
  { artifactId: artifact("b"), title: "Portfolio intent boundary", mediaType: "text/plain", provenanceRef: artifact("b"), payload: { renderer: "text", text: "PortfolioIntent only. Target weights, risk result, orders, fills, and execution remain NOT_CONNECTED." } },
  { artifactId: "future-chart-slot", title: "Chart renderer", mediaType: "application/vnd.v3.future-slot", provenanceRef: "NOT_CONNECTED", payload: { renderer: "chart", availability: "FUTURE_SLOT", reason: "Approved schema is reserved; no current-main transport payload is connected." } },
  { artifactId: "future-backtest-result-slot", title: "Backtest / result renderer", mediaType: "application/vnd.v3.future-slot", provenanceRef: "NOT_CONNECTED", payload: { renderer: "backtest-result", availability: "FUTURE_SLOT", reason: "Track H/I/J integration is intentionally not claimed in Track K." } }
];
