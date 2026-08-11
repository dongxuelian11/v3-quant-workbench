"""Truth-preserving read-only projections over canonical Round 3 owner objects.

This module is a VIEW / TRANSPORT adapter. It is not canonical financial
authority and never creates portfolio, risk, backtest, truth, or admission IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from v3_backend.contracts.common.truth_admission import TruthAdmissionState
from v3_backend.domain.backtest_runtime import BacktestRunResult, BacktestRunSpec
from v3_backend.domain.portfolio_construction import PortfolioConstructionResult
from v3_backend.domain.risk_runtime import RiskDecisionReport, RiskRuntimeResult
from v3_backend.domain.strategies import PortfolioIntent
from v3_backend.domain.weights import RiskAdjustedWeightVector, TargetWeightVector
from v3_backend.provenance.canonical_hash import canonical_sha256


PROJECTION_SCHEMA_VERSION = "v3.round3_canonical_evidence_projection/1.0.0"
BUNDLE_SCHEMA_VERSION = "v3.round3_research_evidence_bundle/1.1.0"
EVIDENCE_KINDS = (
    "PortfolioIntent",
    "TargetWeightVector",
    "RiskAdjustedWeightVector",
    "RiskDecisionReport",
    "BacktestRunSpec",
    "BacktestRunResult",
)
_KIND_ORDER = {kind: index for index, kind in enumerate(EVIDENCE_KINDS)}
_EDGE_RELATION_ORDER = {
    "PORTFOLIO_INTENT_SOURCE": 0,
    "RISK_APPLICATION_TARGET_BINDING": 1,
    "RISK_DECISION_TARGET_BINDING": 2,
    "RISK_DECISION_OUTPUT_BINDING": 3,
    "SCHEDULED_WEIGHTS_VECTOR": 4,
    "BACKTEST_RUN_SPEC_RESULT_BINDING": 5,
}


class EvidenceSourceMode(StrEnum):
    LIVE_READ_ONLY = "LIVE_READ_ONLY"
    DEVELOPMENT_INTEGRATION_FIXTURE = "DEVELOPMENT_INTEGRATION_FIXTURE"


class EvidenceLineageBindingError(ValueError):
    """Canonical source objects do not form one exact H -> I -> J chain."""


@dataclass(frozen=True, slots=True)
class Round3RebalanceEvidence:
    """Canonical upstream owner outputs for one scheduled risk vector."""

    portfolio_intent: PortfolioIntent
    portfolio_result: PortfolioConstructionResult
    risk_result: RiskRuntimeResult


@dataclass(frozen=True, slots=True)
class ViewFactV1:
    label: str
    value: str

    def to_wire(self) -> dict[str, str]:
        return {"label": self.label, "value": self.value}


@dataclass(frozen=True, slots=True)
class LineageEdgeV1:
    source_object_id: str
    source_content_sha256: str
    target_object_id: str
    target_content_sha256: str
    relation: str
    binding_object_id: str | None = None

    def to_wire(self) -> dict[str, str | None]:
        return {
            "source_object_id": self.source_object_id,
            "source_content_sha256": self.source_content_sha256,
            "target_object_id": self.target_object_id,
            "target_content_sha256": self.target_content_sha256,
            "relation": self.relation,
            "binding_object_id": self.binding_object_id,
        }


@dataclass(frozen=True, slots=True)
class ScheduleBindingV1:
    schedule_index: int
    effective_at: datetime
    risk_adjusted_weight_vector_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        if self.schedule_index < 0:
            raise ValueError("schedule_index must be non-negative")
        if self.effective_at.tzinfo is None:
            raise ValueError("schedule binding effective_at must be timezone-aware")
        if _canonical_digest_from_id(
            self.risk_adjusted_weight_vector_id, "rawv_sha256_"
        ) != self.content_sha256:
            raise EvidenceLineageBindingError("schedule binding ID/hash mismatch")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schedule_index": self.schedule_index,
            "effective_at": self.effective_at.isoformat(),
            "risk_adjusted_weight_vector_id": self.risk_adjusted_weight_vector_id,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class CanonicalEvidenceProjectionV1:
    source_artifact_type: str
    source_object_id: str
    source_content_sha256: str
    canonical_truth_state: str
    canonical_admission_state: str
    validation_state: str
    provenance_refs: tuple[str, ...]
    lineage_refs: tuple[str, ...]
    view_facts: tuple[ViewFactV1, ...]
    renderer_key: str
    renderer_payload: dict[str, Any]

    @property
    def projection_schema_version(self) -> str:
        return PROJECTION_SCHEMA_VERSION

    def to_wire(self) -> dict[str, Any]:
        return {
            "projection_schema_version": self.projection_schema_version,
            "source_artifact_type": self.source_artifact_type,
            "source_object_id": self.source_object_id,
            "source_content_sha256": self.source_content_sha256,
            "canonical_truth_state": self.canonical_truth_state,
            "canonical_admission_state": self.canonical_admission_state,
            "validation_state": self.validation_state,
            "provenance_refs": list(self.provenance_refs),
            "lineage_refs": list(self.lineage_refs),
            "view_facts": [value.to_wire() for value in self.view_facts],
            "renderer_key": self.renderer_key,
            "renderer_payload": self.renderer_payload,
        }


@dataclass(frozen=True, slots=True)
class Round3ResearchEvidenceBundleV1:
    session_view_id: str
    source_mode: EvidenceSourceMode
    projections: tuple[CanonicalEvidenceProjectionV1, ...]
    schedule_bindings: tuple[ScheduleBindingV1, ...]
    lineage_edges: tuple[LineageEdgeV1, ...]

    @property
    def bundle_schema_version(self) -> str:
        return BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.session_view_id or self.session_view_id != self.session_view_id.strip():
            raise ValueError("session_view_id must be a non-empty exact string")
        if not self.schedule_bindings:
            raise ValueError(
                "Round 3 bundle requires at least one scheduled RiskAdjusted vector"
            )
        observed_keys: dict[tuple[str, str], str] = {}
        for projection in self.projections:
            if projection.source_artifact_type not in _KIND_ORDER:
                raise ValueError(
                    "Round 3 projection kind is outside the closed vocabulary"
                )
            key = (projection.source_artifact_type, projection.source_object_id)
            prior_hash = observed_keys.get(key)
            if prior_hash is not None:
                if prior_hash != projection.source_content_sha256:
                    raise EvidenceLineageBindingError(
                        "same canonical kind/ID carries different hashes"
                    )
                raise EvidenceLineageBindingError("duplicate canonical projection")
            observed_keys[key] = projection.source_content_sha256
        ordered = tuple(
            sorted(
                self.projections,
                key=lambda value: (
                    _KIND_ORDER[value.source_artifact_type],
                    value.source_object_id,
                ),
            )
        )
        if self.projections != ordered:
            raise ValueError(
                "Round 3 projections must use deterministic kind/canonical-ID order"
            )
        by_kind = {
            kind: tuple(
                value
                for value in self.projections
                if value.source_artifact_type == kind
            )
            for kind in EVIDENCE_KINDS
        }
        if (
            len(by_kind["BacktestRunSpec"]) != 1
            or len(by_kind["BacktestRunResult"]) != 1
        ):
            raise ValueError("Round 3 bundle requires exactly one RunSpec and Result")
        adjusted = by_kind["RiskAdjustedWeightVector"]
        if not adjusted:
            raise ValueError("Round 3 bundle requires scheduled RiskAdjusted evidence")
        if tuple(value.schedule_index for value in self.schedule_bindings) != tuple(
            range(len(self.schedule_bindings))
        ):
            raise ValueError("schedule bindings must use contiguous canonical indices")
        if tuple(value.effective_at for value in self.schedule_bindings) != tuple(
            sorted(value.effective_at for value in self.schedule_bindings)
        ):
            raise ValueError(
                "schedule bindings must preserve canonical effective_at order"
            )
        adjusted_keys = {
            (value.source_object_id, value.source_content_sha256)
            for value in adjusted
        }
        schedule_keys = {
            (value.risk_adjusted_weight_vector_id, value.content_sha256)
            for value in self.schedule_bindings
        }
        if len(schedule_keys) != len(self.schedule_bindings):
            raise EvidenceLineageBindingError(
                "duplicate scheduled RiskAdjusted binding"
            )
        if schedule_keys != adjusted_keys:
            raise EvidenceLineageBindingError(
                "schedule coverage must exactly equal projected RiskAdjusted evidence"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "bundle_schema_version": self.bundle_schema_version,
            "session_view_id": self.session_view_id,
            "source_mode": self.source_mode.value,
            "projections": [value.to_wire() for value in self.projections],
            "schedule_bindings": [
                value.to_wire() for value in self.schedule_bindings
            ],
            "lineage_edges": [value.to_wire() for value in self.lineage_edges],
        }


def _canonical_digest_from_id(object_id: str, prefix: str) -> str:
    if not isinstance(object_id, str) or not object_id.startswith(prefix):
        raise EvidenceLineageBindingError(f"canonical identity requires prefix {prefix}")
    digest = object_id.removeprefix(prefix)
    if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
        raise EvidenceLineageBindingError("canonical identity must carry a lowercase SHA-256")
    return digest


def _assert_wire_identity(
    wire: dict[str, Any],
    *,
    object_id_key: str,
    prefix: str,
    excluded: tuple[str, ...] = (),
) -> tuple[str, str]:
    object_id = wire.get(object_id_key)
    content_sha256 = wire.get("content_sha256")
    if not isinstance(object_id, str) or not isinstance(content_sha256, str):
        raise EvidenceLineageBindingError("canonical wire identity/hash is missing")
    if _canonical_digest_from_id(object_id, prefix) != content_sha256:
        raise EvidenceLineageBindingError("canonical source object ID/hash mismatch")
    payload = {
        key: value
        for key, value in wire.items()
        if key not in {"artifact_type", object_id_key, "content_sha256", *excluded}
    }
    if canonical_sha256(payload) != content_sha256:
        raise EvidenceLineageBindingError("canonical source wire content hash mismatch")
    return object_id, content_sha256


def _intent_identity(intent: PortfolioIntent) -> tuple[str, str, dict[str, Any]]:
    wire = intent.to_wire()
    object_id = wire.get("portfolio_intent_id")
    if not isinstance(object_id, str):
        raise EvidenceLineageBindingError("PortfolioIntent identity is missing")
    digest = _canonical_digest_from_id(object_id, "pint_sha256_")
    payload = {
        key: value
        for key, value in wire.items()
        if key not in {"artifact_type", "portfolio_intent_id"}
    }
    if canonical_sha256(payload) != digest:
        raise EvidenceLineageBindingError("PortfolioIntent canonical wire hash mismatch")
    return object_id, digest, wire


def _truth(state: TruthAdmissionState) -> tuple[str, str]:
    wire = state.to_wire()
    return wire["canonical_truth_state"], wire["canonical_admission_state"]


def _text(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _facts(values: tuple[tuple[str, Any], ...]) -> tuple[ViewFactV1, ...]:
    return tuple(ViewFactV1(label, _text(value)) for label, value in values)


def _refs(*groups: Any) -> tuple[str, ...]:
    values: set[str] = set()
    for group in groups:
        if group is None:
            continue
        if isinstance(group, str):
            values.add(group)
            continue
        for value in group:
            if value is not None:
                values.add(str(value))
    return tuple(sorted(values))


def _projection(
    *,
    kind: str,
    object_id: str,
    content_sha256: str,
    truth: TruthAdmissionState,
    provenance_refs: tuple[str, ...],
    lineage_refs: tuple[str, ...],
    facts: tuple[ViewFactV1, ...],
    renderer_key: str,
    renderer_payload: dict[str, Any],
) -> CanonicalEvidenceProjectionV1:
    canonical_truth_state, canonical_admission_state = _truth(truth)
    return CanonicalEvidenceProjectionV1(
        source_artifact_type=kind,
        source_object_id=object_id,
        source_content_sha256=content_sha256,
        canonical_truth_state=canonical_truth_state,
        canonical_admission_state=canonical_admission_state,
        validation_state="NOT_RUN",
        provenance_refs=provenance_refs,
        lineage_refs=lineage_refs,
        view_facts=facts,
        renderer_key=renderer_key,
        renderer_payload=renderer_payload,
    )


def _build_single_rebalance_bundle(
    *,
    session_view_id: str,
    source_mode: EvidenceSourceMode,
    portfolio_intent: PortfolioIntent,
    portfolio_result: PortfolioConstructionResult,
    risk_result: RiskRuntimeResult,
    backtest_run_spec: BacktestRunSpec,
    backtest_run_result: BacktestRunResult,
) -> Round3ResearchEvidenceBundleV1:
    """Validate and project one exact canonical Portfolio -> Risk -> Backtest chain."""

    if not isinstance(portfolio_intent, PortfolioIntent):
        raise TypeError("portfolio_intent must be the canonical PortfolioIntent object")
    if not isinstance(portfolio_result, PortfolioConstructionResult):
        raise TypeError("portfolio_result must be PortfolioConstructionResult")
    if not isinstance(risk_result, RiskRuntimeResult):
        raise TypeError("risk_result must be RiskRuntimeResult")
    if not isinstance(backtest_run_spec, BacktestRunSpec):
        raise TypeError("backtest_run_spec must be BacktestRunSpec")
    if not isinstance(backtest_run_result, BacktestRunResult):
        raise TypeError("backtest_run_result must be BacktestRunResult")
    if not isinstance(source_mode, EvidenceSourceMode):
        raise TypeError("source_mode must be EvidenceSourceMode")

    target = portfolio_result.target
    adjusted = risk_result.adjusted_weights
    report = risk_result.decision_report
    receipt = risk_result.application_receipt
    if not isinstance(target, TargetWeightVector):
        raise TypeError("portfolio_result.target must be TargetWeightVector")
    if not isinstance(adjusted, RiskAdjustedWeightVector):
        raise TypeError("risk_result.adjusted_weights must be RiskAdjustedWeightVector")
    if not isinstance(report, RiskDecisionReport):
        raise TypeError("risk_result.decision_report must be RiskDecisionReport")

    target.assert_canonical()
    adjusted.assert_canonical()
    report.assert_canonical()
    receipt.assert_canonical()

    intent_id, intent_hash, intent_wire = _intent_identity(portfolio_intent)
    target_wire = target.to_wire()
    target_id, target_hash = _assert_wire_identity(
        target_wire, object_id_key="target_weight_vector_id", prefix="twv_sha256_"
    )
    adjusted_wire = adjusted.to_wire()
    adjusted_id, adjusted_hash = _assert_wire_identity(
        adjusted_wire,
        object_id_key="risk_adjusted_weight_vector_id",
        prefix="rawv_sha256_",
    )
    report_wire = report.to_wire()
    report_id, report_hash = _assert_wire_identity(
        report_wire,
        object_id_key="risk_decision_report_id",
        prefix="rdr_sha256_",
    )
    spec_wire = backtest_run_spec.to_wire()
    spec_id, spec_hash = _assert_wire_identity(
        spec_wire, object_id_key="run_spec_id", prefix="btrs_sha256_"
    )
    result_wire = backtest_run_result.to_wire()
    result_id, result_hash = _assert_wire_identity(
        {"schema_version": backtest_run_result.schema_version, **result_wire},
        object_id_key="result_id",
        prefix="btrr_sha256_",
    )

    if target.source.portfolio_intent_id != intent_id:
        raise EvidenceLineageBindingError(
            "TargetWeightVector source PortfolioIntent ID mismatch"
        )
    if target.source.portfolio_intent_content_sha256 != intent_hash:
        raise EvidenceLineageBindingError(
            "TargetWeightVector source PortfolioIntent hash mismatch"
        )
    if (
        adjusted.source_target.target_weight_vector_id != target_id
        or adjusted.source_target.content_sha256 != target_hash
    ):
        raise EvidenceLineageBindingError(
            "RiskAdjustedWeightVector source Target binding mismatch"
        )
    if (
        receipt.source_target_weight_vector_id != target_id
        or receipt.source_target_content_sha256 != target_hash
    ):
        raise EvidenceLineageBindingError(
            "RiskApplicationReceipt source Target ID/hash mismatch"
        )
    if adjusted.risk_application != receipt:
        raise EvidenceLineageBindingError(
            "RiskAdjustedWeightVector does not bind the supplied RiskApplicationReceipt"
        )
    if (
        report.source_target_weight_vector_id != target_id
        or report.source_target_content_sha256 != target_hash
    ):
        raise EvidenceLineageBindingError(
            "RiskDecisionReport source Target ID/hash mismatch"
        )
    matching_schedule = tuple(
        scheduled
        for scheduled in backtest_run_spec.schedule
        if scheduled.vector.risk_adjusted_weight_vector_id == adjusted_id
        and scheduled.vector.content_sha256 == adjusted_hash
    )
    if len(matching_schedule) != 1:
        raise EvidenceLineageBindingError(
            "each RiskAdjusted evidence chain must bind exactly one RunSpec schedule entry"
        )
    if backtest_run_result.run_spec_id != spec_id:
        raise EvidenceLineageBindingError(
            "BacktestRunResult run_spec_id does not match BacktestRunSpec"
        )

    intent_provenance = _refs(
        (value.artifact_id for value in portfolio_intent.input_artifacts),
        portfolio_intent.source_signal_artifact_id,
        portfolio_intent.source_selection_artifact_id,
        portfolio_intent.provenance_sha256,
    )
    target_provenance = _refs(value.source_id for value in target.evidence_refs)
    risk_provenance = _refs(
        receipt.risk_application_receipt_id,
        receipt.risk_policy_set.source_id,
        (value.source_id for value in receipt.supporting_refs),
    )
    report_provenance = _refs(
        report.risk_policy_set_version_id,
        (value.risk_stage_report_id for value in report.stages),
    )
    spec_provenance = _refs(value.source_id for value in backtest_run_spec.exact_references)

    intent_projection = _projection(
        kind="PortfolioIntent",
        object_id=intent_id,
        content_sha256=intent_hash,
        truth=portfolio_intent.truth_admission,
        provenance_refs=intent_provenance,
        lineage_refs=(),
        facts=_facts(
            (
                ("portfolio_intent_id", intent_id),
                ("strategy_definition_version_id", portfolio_intent.strategy_definition_version_id),
                ("strategy_evaluation_binding_version_id", portfolio_intent.strategy_evaluation_binding_version_id),
                ("source_signal_artifact_id", portfolio_intent.source_signal_artifact_id),
                ("source_selection_artifact_id", portfolio_intent.source_selection_artifact_id),
                ("exposure_mode", portfolio_intent.exposure_mode),
                ("cash_policy", portfolio_intent.cash_policy),
                ("rebalance_intent", portfolio_intent.rebalance_intent),
                ("item_count", len(portfolio_intent.items)),
            )
        ),
        renderer_key="details",
        renderer_payload={
            "renderer": "details",
            "entries": [
                {"label": "portfolio_intent_id", "value": intent_id},
                {"label": "source_selection_artifact_id", "value": portfolio_intent.source_selection_artifact_id},
                {"label": "exposure_mode", "value": portfolio_intent.exposure_mode},
                {"label": "cash_policy", "value": portfolio_intent.cash_policy},
            ],
        },
    )
    target_projection = _projection(
        kind="TargetWeightVector",
        object_id=target_id,
        content_sha256=target_hash,
        truth=target.truth_admission,
        provenance_refs=target_provenance,
        lineage_refs=(intent_id,),
        facts=_facts(
            (
                ("target_weight_vector_id", target_id),
                ("content_sha256", target_hash),
                ("source_portfolio_intent_id", intent_id),
                ("construction_spec_ref", target.construction_spec.source_id),
                ("as_of", target.as_of),
                ("decision_time", target.decision_time),
                ("rebalance_time", target.rebalance_time),
                ("valid_until", target.valid_until),
                ("cash_weight", target.cash_weight),
                ("weight_row_count", len(target.rows)),
            )
        ),
        renderer_key="table",
        renderer_payload={
            "renderer": "table",
            "columns": ["Instrument", "Target weight"],
            "rows": [[value.instrument_id, value.target_weight] for value in target.rows],
        },
    )
    adjusted_projection = _projection(
        kind="RiskAdjustedWeightVector",
        object_id=adjusted_id,
        content_sha256=adjusted_hash,
        truth=adjusted.truth_admission,
        provenance_refs=risk_provenance,
        lineage_refs=(target_id, receipt.risk_application_receipt_id, report_id),
        facts=_facts(
            (
                ("risk_adjusted_weight_vector_id", adjusted_id),
                ("content_sha256", adjusted_hash),
                ("source_target_weight_vector_id", target_id),
                ("risk_application_receipt_id", receipt.risk_application_receipt_id),
                ("risk_policy_set_id", receipt.risk_policy_set.source_id),
                ("decision", receipt.decision.value),
                ("stage_evidence_count", len(receipt.stages)),
                ("cash_weight", adjusted.cash_weight),
                ("adjusted_row_count", len(adjusted.rows)),
            )
        ),
        renderer_key="table",
        renderer_payload={
            "renderer": "table",
            "columns": ["Instrument", "Risk-adjusted weight"],
            "rows": [[value.instrument_id, value.target_weight] for value in adjusted.rows],
        },
    )
    report_projection = _projection(
        kind="RiskDecisionReport",
        object_id=report_id,
        content_sha256=report_hash,
        truth=report.truth_admission,
        provenance_refs=report_provenance,
        lineage_refs=(target_id, adjusted_id),
        facts=_facts(
            (
                ("risk_decision_report_id", report_id),
                ("source_target_weight_vector_id", target_id),
                ("risk_policy_set_version_id", report.risk_policy_set_version_id),
                ("decision", report.decision.value),
                ("stage_count", len(report.stages)),
                ("rejection_reason", report.rejection_reason),
                ("final_cash_weight", report.final_cash_weight),
            )
        ),
        renderer_key="details",
        renderer_payload={
            "renderer": "details",
            "entries": [
                {"label": "decision", "value": report.decision.value},
                {"label": "risk_policy_set_version_id", "value": report.risk_policy_set_version_id},
                {"label": "source_target_weight_vector_id", "value": target_id},
                {"label": "stage_count", "value": str(len(report.stages))},
            ],
        },
    )
    schedule_ids = [
        value.vector.risk_adjusted_weight_vector_id
        for value in backtest_run_spec.schedule
    ]
    schedule_fact_values = tuple(
        item
        for index, scheduled in enumerate(backtest_run_spec.schedule)
        for item in (
            (f"schedule[{index}].effective_at", scheduled.effective_at),
            (
                f"schedule[{index}].risk_adjusted_weight_vector_id",
                scheduled.vector.risk_adjusted_weight_vector_id,
            ),
            (f"schedule[{index}].content_sha256", scheduled.vector.content_sha256),
        )
    )
    spec_projection = _projection(
        kind="BacktestRunSpec",
        object_id=spec_id,
        content_sha256=spec_hash,
        truth=backtest_run_spec.truth_admission,
        provenance_refs=spec_provenance,
        lineage_refs=tuple(schedule_ids),
        facts=_facts(
            (
                ("run_spec_id", spec_id),
                ("content_sha256", spec_hash),
                ("rule_profile_id", backtest_run_spec.rule_profile.profile_id),
                ("cost_policy_id", backtest_run_spec.cost_policy.policy_id),
                ("execution_timing_profile_id", backtest_run_spec.execution_timing_profile.profile_id),
                ("engine_version", backtest_run_spec.engine_version),
            )
            + schedule_fact_values
        ),
        renderer_key="details",
        renderer_payload={
            "renderer": "details",
            "entries": [
                {"label": "run_spec_id", "value": spec_id},
                {"label": "rule_profile_id", "value": backtest_run_spec.rule_profile.profile_id},
                {"label": "cost_policy_id", "value": backtest_run_spec.cost_policy.policy_id},
                {"label": "execution_timing_profile_id", "value": backtest_run_spec.execution_timing_profile.profile_id},
                {"label": "engine_version", "value": backtest_run_spec.engine_version},
            ]
            + [
                {"label": label, "value": _text(value)}
                for label, value in schedule_fact_values
            ],
        },
    )
    fee_total = sum((value.costs.total for value in backtest_run_result.fills), Decimal(0))
    cash_summary = (
        "entries=0"
        if not backtest_run_result.cash_ledger
        else f"entries={len(backtest_run_result.cash_ledger)};ending_balance={backtest_run_result.cash_ledger[-1].balance_after}"
    )
    fee_summary = f"fills={len(backtest_run_result.fills)};total_cost={fee_total}"
    result_projection = _projection(
        kind="BacktestRunResult",
        object_id=result_id,
        content_sha256=result_hash,
        truth=backtest_run_result.truth_admission,
        provenance_refs=_refs(spec_id),
        lineage_refs=(spec_id,),
        facts=_facts(
            (
                ("result_id", result_id),
                ("content_sha256", result_hash),
                ("run_spec_id", spec_id),
                ("nav_row_count", len(backtest_run_result.nav)),
                ("fill_count", len(backtest_run_result.fills)),
                ("diagnostic_count", len(backtest_run_result.diagnostics)),
                ("cash_ledger_summary", cash_summary),
                ("fee_ledger_summary", fee_summary),
            )
        ),
        renderer_key="backtest-result",
        renderer_payload={
            "renderer": "backtest-result",
            "resultId": result_id,
            "runSpecId": spec_id,
            "nav": {
                "columns": ["Session date", "NAV"],
                "rows": [[value.session_date.isoformat(), value.nav] for value in backtest_run_result.nav],
            },
            "fillCount": len(backtest_run_result.fills),
            "diagnosticCount": len(backtest_run_result.diagnostics),
            "cashLedgerSummary": cash_summary,
            "feeLedgerSummary": fee_summary,
        },
    )

    edges = (
        LineageEdgeV1(intent_id, intent_hash, target_id, target_hash, "PORTFOLIO_INTENT_SOURCE"),
        LineageEdgeV1(target_id, target_hash, adjusted_id, adjusted_hash, "RISK_APPLICATION_TARGET_BINDING", receipt.risk_application_receipt_id),
        LineageEdgeV1(target_id, target_hash, report_id, report_hash, "RISK_DECISION_TARGET_BINDING", receipt.risk_application_receipt_id),
        LineageEdgeV1(report_id, report_hash, adjusted_id, adjusted_hash, "RISK_DECISION_OUTPUT_BINDING", receipt.risk_application_receipt_id),
        LineageEdgeV1(adjusted_id, adjusted_hash, spec_id, spec_hash, "SCHEDULED_WEIGHTS_VECTOR"),
        LineageEdgeV1(spec_id, spec_hash, result_id, result_hash, "BACKTEST_RUN_SPEC_RESULT_BINDING"),
    )
    return Round3ResearchEvidenceBundleV1(
        session_view_id=session_view_id,
        source_mode=source_mode,
        projections=(
            intent_projection,
            target_projection,
            adjusted_projection,
            report_projection,
            spec_projection,
            result_projection,
        ),
        schedule_bindings=(
            ScheduleBindingV1(
                0,
                matching_schedule[0].effective_at,
                adjusted_id,
                adjusted_hash,
            ),
        ),
        lineage_edges=edges,
    )


def build_round3_evidence_bundle(
    *,
    session_view_id: str,
    source_mode: EvidenceSourceMode,
    rebalance_evidence: tuple[Round3RebalanceEvidence, ...],
    backtest_run_spec: BacktestRunSpec,
    backtest_run_result: BacktestRunResult,
) -> Round3ResearchEvidenceBundleV1:
    """Project the complete exact upstream graph for one canonical RunSpec."""

    if not rebalance_evidence:
        raise EvidenceLineageBindingError(
            "at least one canonical rebalance evidence chain is required"
        )
    if any(
        not isinstance(value, Round3RebalanceEvidence)
        for value in rebalance_evidence
    ):
        raise TypeError(
            "rebalance_evidence must contain Round3RebalanceEvidence values"
        )

    partials = tuple(
        _build_single_rebalance_bundle(
            session_view_id=session_view_id,
            source_mode=source_mode,
            portfolio_intent=value.portfolio_intent,
            portfolio_result=value.portfolio_result,
            risk_result=value.risk_result,
            backtest_run_spec=backtest_run_spec,
            backtest_run_result=backtest_run_result,
        )
        for value in rebalance_evidence
    )

    projection_by_key: dict[
        tuple[str, str], CanonicalEvidenceProjectionV1
    ] = {}
    for partial in partials:
        for projection in partial.projections:
            key = (projection.source_artifact_type, projection.source_object_id)
            prior = projection_by_key.get(key)
            if prior is not None and prior.source_content_sha256 != projection.source_content_sha256:
                raise EvidenceLineageBindingError(
                    "same canonical kind/ID carries different hashes"
                )
            if prior is not None and prior != projection:
                raise EvidenceLineageBindingError(
                    "same canonical projection identity carries different view content"
                )
            projection_by_key[key] = projection

    projections = tuple(
        sorted(
            projection_by_key.values(),
            key=lambda value: (
                _KIND_ORDER[value.source_artifact_type],
                value.source_object_id,
            ),
        )
    )
    adjusted_by_id = {
        value.source_object_id: value
        for value in projections
        if value.source_artifact_type == "RiskAdjustedWeightVector"
    }
    schedule_bindings: list[ScheduleBindingV1] = []
    scheduled_ids: set[str] = set()
    for index, scheduled in enumerate(backtest_run_spec.schedule):
        adjusted_id = scheduled.vector.risk_adjusted_weight_vector_id
        projection = adjusted_by_id.get(adjusted_id)
        if (
            projection is None
            or projection.source_content_sha256 != scheduled.vector.content_sha256
        ):
            raise EvidenceLineageBindingError(
                "BacktestRunSpec schedule is missing exact RiskAdjusted evidence"
            )
        if adjusted_id in scheduled_ids:
            raise EvidenceLineageBindingError(
                "BacktestRunSpec schedule repeats one RiskAdjusted evidence identity"
            )
        scheduled_ids.add(adjusted_id)
        schedule_bindings.append(
            ScheduleBindingV1(
                index,
                scheduled.effective_at,
                adjusted_id,
                scheduled.vector.content_sha256,
            )
        )
    orphan_ids = set(adjusted_by_id) - scheduled_ids
    if orphan_ids:
        raise EvidenceLineageBindingError(
            "orphan RiskAdjusted evidence is outside the exact RunSpec schedule: "
            + ",".join(sorted(orphan_ids))
        )

    edge_by_key: dict[
        tuple[str, str, str, str, str, str | None], LineageEdgeV1
    ] = {}
    for partial in partials:
        for edge in partial.lineage_edges:
            key = (
                edge.relation,
                edge.source_object_id,
                edge.source_content_sha256,
                edge.target_object_id,
                edge.target_content_sha256,
                edge.binding_object_id,
            )
            edge_by_key[key] = edge
    edges = tuple(
        sorted(
            edge_by_key.values(),
            key=lambda value: (
                _EDGE_RELATION_ORDER[value.relation],
                value.source_object_id,
                value.target_object_id,
                value.binding_object_id or "",
            ),
        )
    )
    return Round3ResearchEvidenceBundleV1(
        session_view_id=session_view_id,
        source_mode=source_mode,
        projections=projections,
        schedule_bindings=tuple(schedule_bindings),
        lineage_edges=edges,
    )


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "CanonicalEvidenceProjectionV1",
    "EVIDENCE_KINDS",
    "EvidenceLineageBindingError",
    "EvidenceSourceMode",
    "LineageEdgeV1",
    "PROJECTION_SCHEMA_VERSION",
    "Round3RebalanceEvidence",
    "Round3ResearchEvidenceBundleV1",
    "ScheduleBindingV1",
    "ViewFactV1",
    "build_round3_evidence_bundle",
]
