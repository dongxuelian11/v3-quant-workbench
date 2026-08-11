from __future__ import annotations

from v3_backend.adapters.round3_evidence.projection import Round3ResearchEvidenceBundleV1
from v3_backend.contracts.common.truth_admission import (
    AdmissionState,
    TruthAdmissionState,
    TruthState,
    ValidationState,
)

from .model import (
    ExactEvidenceBinding,
    ResearchReviewScope,
    ReviewEvidenceRecord,
    ReviewEvidenceRef,
    ReviewFact,
)


_RELATION_MAP = {
    "PORTFOLIO_INTENT_SOURCE": "portfolio_intent",
    "RISK_APPLICATION_TARGET_BINDING": "source_target",
    "RISK_DECISION_TARGET_BINDING": "source_target",
    "RISK_DECISION_OUTPUT_BINDING": "risk_report",
    "SCHEDULED_WEIGHTS_VECTOR": "scheduled_risk_adjusted",
    "BACKTEST_RUN_SPEC_RESULT_BINDING": "run_spec",
}


def review_scope_from_round3_bundle(
    bundle: Round3ResearchEvidenceBundleV1,
) -> ResearchReviewScope:
    """Build a read-only Track O scope from the protected current-main projection.

    The adapter neither changes the Round 3 schema nor invents hashes for provenance
    references that are not separately loaded as exact objects.
    """

    refs = {
        (projection.source_object_id, projection.source_content_sha256): ReviewEvidenceRef(
            session_id=bundle.session_view_id,
            object_kind=projection.source_artifact_type,
            object_id=projection.source_object_id,
            content_sha256=projection.source_content_sha256,
        )
        for projection in bundle.projections
    }
    bindings_by_target: dict[tuple[str, str], list[ExactEvidenceBinding]] = {}
    for edge in bundle.lineage_edges:
        source_key = (edge.source_object_id, edge.source_content_sha256)
        target_key = (edge.target_object_id, edge.target_content_sha256)
        source = refs.get(source_key)
        target = refs.get(target_key)
        if source is None or target is None:
            continue
        relation = _RELATION_MAP.get(edge.relation, "lineage")
        bindings_by_target.setdefault(target_key, []).append(
            ExactEvidenceBinding(relation, source)
        )

    records: list[ReviewEvidenceRecord] = []
    for projection in bundle.projections:
        key = (projection.source_object_id, projection.source_content_sha256)
        fact_values = {value.label: value.value for value in projection.view_facts}
        if projection.source_artifact_type == "TargetWeightVector" and "rebalance_time" in fact_values:
            fact_values["effective_at"] = fact_values["rebalance_time"]
        if projection.source_artifact_type == "BacktestRunSpec":
            fact_values["risk_adjusted_only"] = "true"
            if "execution_timing_profile_id" in fact_values:
                fact_values["execution_timing_profile"] = fact_values["execution_timing_profile_id"]
            if "cost_policy_id" in fact_values:
                fact_values["cost_policy"] = fact_values["cost_policy_id"]
        records.append(
            ReviewEvidenceRecord(
                ref=refs[key],
                validation_state=ValidationState(projection.validation_state),
                truth_admission=TruthAdmissionState(
                    TruthState(projection.canonical_truth_state),
                    AdmissionState(projection.canonical_admission_state),
                ),
                provenance_refs=(),
                bindings=tuple(
                    sorted(
                        bindings_by_target.get(key, ()),
                        key=lambda value: (value.relation, value.target.exact_key),
                    )
                ),
                facts=tuple(
                    ReviewFact(name, value)
                    for name, value in sorted(fact_values.items())
                ),
            )
        )
    results = tuple(value.ref for value in records if value.ref.object_kind == "BacktestRunResult")
    if len(results) != 1:
        raise ValueError("Round 3 reviewer scope requires exactly one BacktestRunResult target")
    return ResearchReviewScope.create(
        session_id=bundle.session_view_id,
        target_refs=results,
        evidence_records=tuple(records),
    )


__all__ = ["review_scope_from_round3_bundle"]
