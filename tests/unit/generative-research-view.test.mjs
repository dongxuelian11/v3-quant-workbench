import test from "node:test";
import assert from "node:assert/strict";
import { parseResearchViewSpec } from "../../apps/desktop/src/renderer/generative_ui/schemaParser.ts";
import { buildClosedChartOption } from "../../apps/desktop/src/renderer/generative_ui/closedRenderer.ts";
import { CLOSED_RESEARCH_RENDERER_KEYS, getClosedResearchRenderer } from "../../apps/desktop/src/renderer/generative_ui/rendererRegistry.ts";
import { createGenerativeResearchViewFixture } from "../../apps/desktop/src/renderer/generative_ui/integrationFixture.ts";

const evidenceId = (character) => `evidence_sha256_${character.repeat(64)}`;

const sessionEvidence = [
  {
    kind: "RewardVector",
    objectId: evidenceId("a"),
    title: "Reward vector",
    summary: "Current-session canonical projection.",
    canonicalTruthState: "NOT_FORMAL",
    canonicalAdmissionState: "PRE_ALPHA",
    validationState: "NOT_RUN",
    provenanceRefs: ["artifact_sha256_source"],
    reviewerFinding: "MULTIPLE_TESTING_RISK / NOT_RUN",
    facts: [
      { label: "IC", value: "0.047" },
      { label: "Rank IC", value: "0.061" },
      { label: "As of", value: "2026-08-11T16:08:03+08:00" }
    ],
    openInLab: "result",
    artifactId: "artifact_sha256_reward"
  },
  {
    kind: "RewardVector",
    objectId: evidenceId("b"),
    title: "Reward vector follow-up",
    summary: "Second current-session canonical projection.",
    canonicalTruthState: "NOT_FORMAL",
    canonicalAdmissionState: "PRE_ALPHA",
    validationState: "NOT_RUN",
    provenanceRefs: ["artifact_sha256_source_b"],
    reviewerFinding: null,
    facts: [
      { label: "IC", value: "0.052" },
      { label: "Rank IC", value: "0.064" },
      { label: "As of", value: "2026-08-12T16:08:03+08:00" }
    ],
    openInLab: "result",
    artifactId: "artifact_sha256_reward_b"
  }
];

const canonicalMetricSpec = {
  schema_version: "v3.generative_research_view/1.0.0",
  spec_id: "grv-spec-001",
  session_view_id: "session-a",
  permission: "L1_DRAFT",
  authority: "AGENT_DRAFT_PROPOSAL",
  title: "Momentum evidence view",
  blocks: [
    {
      type: "MetricGroup",
      block_id: "metric-001",
      title: "Reward metrics",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [evidenceId("a")],
      metrics: [
        { label: "IC", evidence_id: evidenceId("a"), selector: { kind: "FACT", label: "IC", normalization: "NUMBER" } },
        { label: "Admission", evidence_id: evidenceId("a"), selector: { kind: "EVIDENCE_FIELD", field: "canonicalAdmissionState", normalization: "NONE" } }
      ]
    }
  ]
};

test("valid canonical metric values are resolved only from active-session evidence", () => {
  const parsed = parseResearchViewSpec(canonicalMetricSpec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "VALID");
  assert.deepEqual(parsed.blocks, [{
    type: "MetricGroup",
    blockId: "metric-001",
    title: "Reward metrics",
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds: [evidenceId("a")],
    metrics: [
      { label: "IC", value: "0.047", sourceEvidenceId: evidenceId("a") },
      { label: "Admission", value: "PRE_ALPHA", sourceEvidenceId: evidenceId("a") }
    ]
  }]);
});

test("data table columns resolve approved selectors over declared evidence rows", () => {
  const spec = {
    ...canonicalMetricSpec,
    spec_id: "grv-table-001",
    blocks: [{
      type: "DataTable",
      block_id: "table-001",
      title: "Evidence rows",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [evidenceId("a")],
      columns: [
        { key: "title", header: "Evidence", selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" } },
        { key: "ic", header: "IC", selector: { kind: "FACT", label: "IC", normalization: "NUMBER" } }
      ],
      rows: [{ evidence_id: evidenceId("a") }],
      sort: { column_key: "ic", direction: "DESC" },
      top_n: 10
    }]
  };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "VALID");
  assert.deepEqual(parsed.blocks[0], {
    type: "DataTable",
    blockId: "table-001",
    title: "Evidence rows",
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds: [evidenceId("a")],
    columns: [{ key: "title", header: "Evidence" }, { key: "ic", header: "IC" }],
    rows: [{ evidenceId: evidenceId("a"), cells: ["Reward vector", "0.047"] }]
  });
});

test("time-series chart resolves bounded points and date window from evidence selectors", () => {
  const spec = {
    ...canonicalMetricSpec,
    spec_id: "grv-timeseries-001",
    blocks: [{
      type: "TimeSeriesChart",
      block_id: "timeseries-001",
      title: "IC observations",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [evidenceId("a"), evidenceId("b")],
      x_label: "As of",
      y_label: "IC",
      points: [evidenceId("b"), evidenceId("a")].map((id) => ({
        evidence_id: id,
        x_selector: { kind: "FACT", label: "As of", normalization: "ISO_DATE" },
        y_selector: { kind: "FACT", label: "IC", normalization: "NUMBER" }
      })),
      date_window: { start: "2026-08-11T00:00:00.000Z", end: "2026-08-13T00:00:00.000Z" }
    }]
  };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "VALID");
  assert.deepEqual(parsed.blocks[0].points, [
    { x: "2026-08-11T08:08:03.000Z", y: 0.047, sourceEvidenceId: evidenceId("a") },
    { x: "2026-08-12T08:08:03.000Z", y: 0.052, sourceEvidenceId: evidenceId("b") }
  ]);
});

test("bar chart applies only the closed sort and topN display transforms", () => {
  const spec = {
    ...canonicalMetricSpec,
    spec_id: "grv-bar-001",
    blocks: [{
      type: "BarChart",
      block_id: "bar-001",
      title: "IC comparison",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [evidenceId("a"), evidenceId("b")],
      category_label: "Evidence",
      value_label: "IC",
      bars: [evidenceId("a"), evidenceId("b")].map((id) => ({
        evidence_id: id,
        category_selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" },
        value_selector: { kind: "FACT", label: "IC", normalization: "NUMBER" }
      })),
      sort: "VALUE_DESC",
      top_n: 1
    }]
  };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "VALID");
  assert.deepEqual(parsed.blocks[0].bars, [
    { category: "Reward vector follow-up", value: 0.052, sourceEvidenceId: evidenceId("b") }
  ]);
});

test("agent-derived narrative remains visibly NON_CANONICAL and source-bound", () => {
  const spec = {
    ...canonicalMetricSpec,
    spec_id: "grv-narrative-001",
    blocks: [{
      type: "Narrative",
      block_id: "narrative-001",
      title: "Draft interpretation",
      data_authority: "AGENT_DRAFT_DERIVED",
      evidence_ids: [evidenceId("a")],
      text: "IC is positive in the cited projection, but validation remains NOT_RUN."
    }]
  };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "VALID");
  assert.deepEqual(parsed.blocks[0], {
    type: "Narrative",
    blockId: "narrative-001",
    title: "Draft interpretation",
    dataAuthority: "AGENT_DRAFT_DERIVED",
    authorityLabel: "NON_CANONICAL / DRAFT",
    evidenceIds: [evidenceId("a")],
    text: "IC is positive in the cited projection, but validation remains NOT_RUN."
  });
});

test("evidence list exposes exact bound IDs and only approved display fields", () => {
  const spec = {
    ...canonicalMetricSpec,
    spec_id: "grv-evidence-list-001",
    blocks: [{
      type: "EvidenceList",
      block_id: "evidence-list-001",
      title: "Sources",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [evidenceId("a"), evidenceId("b")],
      fields: [
        { key: "title", label: "Evidence", selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" } },
        { key: "admission", label: "Admission", selector: { kind: "EVIDENCE_FIELD", field: "canonicalAdmissionState", normalization: "NONE" } }
      ]
    }]
  };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "VALID");
  assert.deepEqual(parsed.blocks[0].items[0], {
    evidenceId: evidenceId("a"),
    openInLab: "result",
    values: [{ key: "title", label: "Evidence", value: "Reward vector" }, { key: "admission", label: "Admission", value: "PRE_ALPHA" }]
  });
});

test("draft callout keeps a closed tone and cannot masquerade as canonical evidence", () => {
  const spec = {
    ...canonicalMetricSpec,
    spec_id: "grv-callout-001",
    blocks: [{
      type: "Callout",
      block_id: "callout-001",
      title: "Validation boundary",
      data_authority: "AGENT_DRAFT_DERIVED",
      evidence_ids: [evidenceId("a")],
      tone: "WARNING",
      text: "Formal validation remains NOT_RUN."
    }]
  };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "VALID");
  assert.deepEqual(parsed.blocks[0], {
    type: "Callout",
    blockId: "callout-001",
    title: "Validation boundary",
    dataAuthority: "AGENT_DRAFT_DERIVED",
    authorityLabel: "NON_CANONICAL / DRAFT",
    evidenceIds: [evidenceId("a")],
    tone: "WARNING",
    text: "Formal validation remains NOT_RUN."
  });
});

test("canonical blocks reject Agent-supplied replacement values", () => {
  const spec = structuredClone(canonicalMetricSpec);
  spec.blocks[0].metrics[0].value = "999";
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.match(parsed.invalidBlocks[0].reason, /closed schema/);
});

test("wrong evidence ID is rejected instead of globally resolved", () => {
  const spec = structuredClone(canonicalMetricSpec);
  spec.blocks[0].evidence_ids = [evidenceId("f")];
  spec.blocks[0].metrics[0].evidence_id = evidenceId("f");
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.match(parsed.invalidBlocks[0].reason, /active session/);
});

test("session switch rejects a prior session ResearchViewSpec", () => {
  const parsed = parseResearchViewSpec(canonicalMetricSpec, { sessionViewId: "session-b", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.match(parsed.error, /cross-session/);
  assert.deepEqual(parsed.blocks, []);
});

test("unknown block is isolated as an explicit unsupported renderer state", () => {
  const spec = structuredClone(canonicalMetricSpec);
  spec.blocks.push({ type: "ArbitraryWidget", block_id: "unsupported-001" });
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "PARTIAL_INVALID");
  assert.equal(parsed.blocks.length, 1);
  assert.deepEqual(parsed.invalidBlocks, [{ blockId: "unsupported-001", reason: "unknown research view block" }]);
});

test("unknown selector and formula language are rejected", () => {
  const spec = structuredClone(canonicalMetricSpec);
  spec.blocks[0].metrics[0].selector = { kind: "FORMULA", expression: "IC * 100" };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.match(parsed.invalidBlocks[0].reason, /unknown selector/);
});

test("arbitrary HTML in Agent-authored text is rejected", () => {
  const spec = {
    ...canonicalMetricSpec,
    blocks: [{
      type: "Narrative",
      block_id: "bad-html",
      title: "Bad",
      data_authority: "AGENT_DRAFT_DERIVED",
      evidence_ids: [evidenceId("a")],
      text: "<img src=x onerror=alert(1)>"
    }]
  };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.match(parsed.invalidBlocks[0].reason, /forbidden markup or script/);
});

test("raw ECharts options and JavaScript formatter functions are rejected", () => {
  const base = {
    type: "BarChart",
    block_id: "bad-chart",
    title: "Bad chart",
    data_authority: "CANONICAL_EVIDENCE",
    evidence_ids: [evidenceId("a")],
    category_label: "Evidence",
    value_label: "IC",
    bars: [{
      evidence_id: evidenceId("a"),
      category_selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" },
      value_selector: { kind: "FACT", label: "IC", normalization: "NUMBER" }
    }],
    sort: "INPUT",
    top_n: null
  };
  for (const executable of [{ option: { series: [] } }, { formatter: "function(v){return eval(v)}" }]) {
    const parsed = parseResearchViewSpec({ ...canonicalMetricSpec, blocks: [{ ...base, ...executable }] }, { sessionViewId: "session-a", evidence: sessionEvidence });
    assert.equal(parsed.status, "INVALID");
    assert.match(parsed.invalidBlocks[0].reason, /closed schema/);
  }
});

test("extra fields fail the closed envelope schema", () => {
  const parsed = parseResearchViewSpec({ ...canonicalMetricSpec, component_path: "./Arbitrary.tsx" }, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.match(parsed.error, /closed schema/);
});

test("closed envelope requires 1-64 bounded blocks", () => {
  for (const blocks of [[], Array.from({ length: 65 }, () => structuredClone(canonicalMetricSpec.blocks[0]))]) {
    const parsed = parseResearchViewSpec({ ...canonicalMetricSpec, blocks }, { sessionViewId: "session-a", evidence: sessionEvidence });
    assert.equal(parsed.status, "INVALID");
    assert.match(parsed.error, /1-64 blocks/);
  }
});

test("metric group rejects more than 32 selector metrics", () => {
  const metric = structuredClone(canonicalMetricSpec.blocks[0].metrics[0]);
  const spec = structuredClone(canonicalMetricSpec);
  spec.blocks[0].metrics = Array.from({ length: 33 }, () => structuredClone(metric));
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.match(parsed.invalidBlocks[0].reason, /1-32 metrics/);
});

test("Agent proposal cannot set Truth, Admission, or Validation", () => {
  const spec = {
    ...canonicalMetricSpec,
    blocks: [{
      type: "Callout",
      block_id: "authority-escalation",
      title: "Bad authority claim",
      data_authority: "AGENT_DRAFT_DERIVED",
      evidence_ids: [evidenceId("a")],
      tone: "INFO",
      text: "Attempted authority escalation.",
      canonicalTruthState: "FORMAL",
      canonicalAdmissionState: "FORMAL_ADMITTED",
      validationState: "PASSED"
    }]
  };
  const parsed = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.match(parsed.invalidBlocks[0].reason, /closed schema/);
});

test("multiple mixed blocks resolve deterministically in proposal order", () => {
  const spec = structuredClone(canonicalMetricSpec);
  spec.blocks.push({
    type: "Narrative",
    block_id: "narrative-after-metric",
    title: "Draft note",
    data_authority: "AGENT_DRAFT_DERIVED",
    evidence_ids: [evidenceId("a")],
    text: "The metric is cited, not recalculated."
  });
  const context = { sessionViewId: "session-a", evidence: sessionEvidence };
  const first = parseResearchViewSpec(spec, context);
  const second = parseResearchViewSpec(structuredClone(spec), context);
  assert.equal(first.status, "VALID");
  assert.deepEqual(second, first);
  assert.deepEqual(first.blocks.map((block) => block.type), ["MetricGroup", "Narrative"]);
});

test("ResearchViewSpec accepts only L1_DRAFT and denies L2/L3 escalation", () => {
  for (const permission of ["L2_EXECUTE", "L3_PUBLISH"]) {
    const parsed = parseResearchViewSpec({ ...canonicalMetricSpec, permission }, { sessionViewId: "session-a", evidence: sessionEvidence });
    assert.equal(parsed.status, "INVALID");
    assert.match(parsed.error, /requires L1_DRAFT/);
  }
});

test("closed chart builder emits deterministic ECharts data with no executable formatter", () => {
  const spec = {
    ...canonicalMetricSpec,
    blocks: [{
      type: "BarChart",
      block_id: "bar-safe",
      title: "Safe bar",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [evidenceId("a")],
      category_label: "Evidence",
      value_label: "IC",
      bars: [{
        evidence_id: evidenceId("a"),
        category_selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" },
        value_selector: { kind: "FACT", label: "IC", normalization: "NUMBER" }
      }],
      sort: "INPUT",
      top_n: null
    }]
  };
  const block = parseResearchViewSpec(spec, { sessionViewId: "session-a", evidence: sessionEvidence }).blocks[0];
  const option = buildClosedChartOption(block);
  assert.deepEqual(option.xAxis.data, ["Reward vector"]);
  assert.deepEqual(option.series[0].data, [0.047]);
  const visit = (value) => {
    assert.notEqual(typeof value, "function");
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object") Object.values(value).forEach(visit);
  };
  visit(option);
});

test("renderer registry is closed to the seven ResearchView block types", () => {
  assert.deepEqual(CLOSED_RESEARCH_RENDERER_KEYS, ["Narrative", "MetricGroup", "DataTable", "TimeSeriesChart", "BarChart", "EvidenceList", "Callout"]);
  assert.equal(getClosedResearchRenderer("MetricGroup").availability, "AVAILABLE");
  assert.throws(() => getClosedResearchRenderer("ArbitraryJSX"), /unsupported research renderer/);
});

test("deterministic fixture is regenerated from the active session evidence without raw canonical values", () => {
  const fixture = createGenerativeResearchViewFixture("session-b", sessionEvidence);
  assert.equal(fixture.session_view_id, "session-b");
  assert.ok(fixture.blocks.every((block) => block.evidence_ids.every((id) => sessionEvidence.some((item) => item.objectId === id))));
  const visit = (value) => {
    if (Array.isArray(value)) return value.forEach(visit);
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      assert.notEqual(key, "value");
      assert.notEqual(key, "option");
      assert.notEqual(key, "formatter");
      visit(child);
    }
  };
  visit(fixture);
});

test("invalid structured view returns an explicit state instead of throwing into Workspace", () => {
  assert.doesNotThrow(() => parseResearchViewSpec(null, { sessionViewId: "session-a", evidence: sessionEvidence }));
  const parsed = parseResearchViewSpec(null, { sessionViewId: "session-a", evidence: sessionEvidence });
  assert.equal(parsed.status, "INVALID");
  assert.equal(parsed.title, "Invalid structured research view");
  assert.match(parsed.error, /must be an object/);
});
