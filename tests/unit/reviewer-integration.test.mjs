import test from "node:test";
import assert from "node:assert/strict";

import {
  REVIEWER_AGENT_CAPABILITIES,
  REVIEWER_FORBIDDEN_ACTIONS,
  REVIEWER_RULE_SET,
  deriveReviewerReportView,
  summarizeReviewCoverage
} from "../../apps/desktop/src/renderer/reviewer/model.ts";
import {
  agentStatements,
  evidenceViews,
  researchSessions
} from "../../apps/desktop/src/renderer/agentWorkspaceFixture.ts";

test("Reviewer ruleset exposes the exact backend content-addressed identity", () => {
  assert.equal(REVIEWER_RULE_SET.version, "v3.reviewer-integration/1");
  assert.match(REVIEWER_RULE_SET.id, /^rrs_sha256_[0-9a-f]{64}$/);
});

test("Reviewer summary counts all closed Layer A outcomes", () => {
  const session = researchSessions[0];
  const report = deriveReviewerReportView(session, evidenceViews, agentStatements);
  assert.equal(report.coverage.checkedRules, 15);
  assert.equal(
    report.coverage.PASS + report.coverage.FINDING + report.coverage.NOT_RUN + report.coverage.NOT_APPLICABLE + report.coverage.BLOCKED,
    report.coverage.checkedRules
  );
  assert.deepEqual(report.coverage, summarizeReviewCoverage(report.checks));
  assert.ok(report.checks.every((item) => item.layer === "LAYER_A_DETERMINISTIC"));
});

test("validation_state NOT_RUN remains NOT_RUN and prevents a clear status", () => {
  const session = researchSessions.find((item) => item.evidenceIds.some((objectId) => evidenceViews.find((evidence) => evidence.objectId === objectId)?.validationState === "NOT_RUN"));
  assert.ok(session);
  const report = deriveReviewerReportView(session, evidenceViews, agentStatements);
  assert.equal(report.checks.find((item) => item.ruleId === "O-003").outcome, "NOT_RUN");
  assert.notEqual(report.overallStatus, "CLEAR_WITHIN_CHECKED_SCOPE");
});

test("Reviewer findings link only exact evidence in the active session", () => {
  const session = researchSessions[0];
  const report = deriveReviewerReportView(session, evidenceViews, agentStatements);
  const sessionIds = new Set(session.evidenceIds);
  for (const finding of report.findings) {
    assert.ok(finding.evidenceObjectIds.length > 0);
    assert.ok(finding.evidenceObjectIds.every((objectId) => sessionIds.has(objectId)));
    assert.ok(finding.evidenceObjectIds.every((objectId) => evidenceViews.some((evidence) => evidence.objectId === objectId)));
  }
});

test("Reviewer Agent is visually and contractually restricted to L0/L1", () => {
  assert.deepEqual(REVIEWER_AGENT_CAPABILITIES.map((item) => item.permission), ["L0_READ", "L1_DRAFT"]);
  assert.deepEqual(REVIEWER_FORBIDDEN_ACTIONS, ["FORMAL_ADMISSION", "PUBLISH", "WAIVE_FINDING", "MUTATE_CANONICAL_EVIDENCE", "PROMOTE_NOT_RUN", "PROMOTE_FINDING"]);
  const session = researchSessions.find((item) => agentStatements.some((statement) => statement.sessionViewId === item.sessionViewId && statement.role === "REVIEWER"));
  assert.ok(session);
  const report = deriveReviewerReportView(session, evidenceViews, agentStatements);
  assert.ok(report.agentDrafts.every((item) => item.layer === "LAYER_B_REVIEWER_AGENT" && item.permission === "L1_DRAFT" && item.authorityStatus === "NON_CANONICAL"));
  assert.ok(!report.agentDrafts.some((item) => "outcome" in item || "admission" in item || "publish" in item || "waive" in item));
});
