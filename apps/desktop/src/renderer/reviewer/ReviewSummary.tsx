import React from "react";
import type { ReviewerReportView } from "./model";

export function ReviewSummary({ report }: { report: ReviewerReportView }) {
  return <section className="review-summary" aria-label="评审覆盖摘要">
    <div className="review-overall"><small>总体评审 · 不代表准入</small><b data-review-status={report.overallStatus}>{report.overallStatus}</b><code>{report.reportId ?? "BACKEND_REPORT_NOT_LOADED"}</code></div>
    <div className="review-counts">
      {(["PASS", "FINDING", "NOT_RUN", "NOT_APPLICABLE", "BLOCKED"] as const).map((name) => <div key={name} data-review-outcome={name}><span>{name}</span><strong>{report.coverage[name]}</strong></div>)}
    </div>
  </section>;
}
