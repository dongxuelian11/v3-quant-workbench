from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from v3_backend.contracts.common.truth_admission import (
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
    UpstreamRequirement,
    meet_pair,
    propagate_downstream_ceiling,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

from .evaluator import EvaluationResult
from .ir import FactorDefinitionVersion


def _require_text(value: str, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty without edge whitespace")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _wire_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _upstreams_wire(
    values: tuple[UpstreamRequirement, ...],
) -> list[dict[str, object]]:
    return [
        {"source_id": value.source_id, "state": value.state.to_wire()}
        for value in sorted(values, key=lambda item: item.source_id)
    ]


class CoreUpstreamAuthority(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    UNIVERSE = "UNIVERSE"


@dataclass(frozen=True, slots=True)
class UnresolvedIdUpstreamTruthBinding:
    """Identity-bound V0 boundary for an upstream without a canonical receipt."""

    authority: CoreUpstreamAuthority
    source_id: str
    truth_ceiling: TruthAdmissionState

    def __post_init__(self) -> None:
        if not isinstance(self.authority, CoreUpstreamAuthority):
            raise TypeError("authority must be CoreUpstreamAuthority")
        _require_text(self.source_id, "source_id")
        object.__setattr__(
            self,
            "truth_ceiling",
            meet_pair(self.truth_ceiling, PRE_ALPHA_CEILING),
        )

    @classmethod
    def snapshot(
        cls, snapshot_id: str, proposed_ceiling: TruthAdmissionState
    ) -> UnresolvedIdUpstreamTruthBinding:
        return cls(CoreUpstreamAuthority.SNAPSHOT, snapshot_id, proposed_ceiling)

    @classmethod
    def universe(
        cls, universe_version_id: str, proposed_ceiling: TruthAdmissionState
    ) -> UnresolvedIdUpstreamTruthBinding:
        return cls(CoreUpstreamAuthority.UNIVERSE, universe_version_id, proposed_ceiling)

    def to_requirement(self) -> UpstreamRequirement:
        return UpstreamRequirement(self.source_id, self.truth_ceiling)

    def to_wire(self) -> dict[str, object]:
        return {
            "authority": self.authority.value,
            "source_id": self.source_id,
            "resolution": "UNRESOLVED_RAW_ID",
            "truth_ceiling": self.truth_ceiling.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class FactorEvaluationContext:
    snapshot_id: str
    universe_version_id: str
    snapshot_truth_binding: UnresolvedIdUpstreamTruthBinding
    universe_truth_binding: UnresolvedIdUpstreamTruthBinding
    knowledge_cutoff: datetime
    calendar_version_id: str
    schema_version_id: str
    environment_fingerprint: str
    evaluator_version: str

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "universe_version_id",
            "calendar_version_id",
            "schema_version_id",
            "environment_fingerprint",
            "evaluator_version",
        ):
            _require_text(getattr(self, name), name)
        _require_aware(self.knowledge_cutoff, "knowledge_cutoff")
        if self.snapshot_id == self.universe_version_id:
            raise ValueError("Snapshot and Universe upstream identities must be distinct")
        self._require_core_binding(
            self.snapshot_truth_binding,
            CoreUpstreamAuthority.SNAPSHOT,
            self.snapshot_id,
        )
        self._require_core_binding(
            self.universe_truth_binding,
            CoreUpstreamAuthority.UNIVERSE,
            self.universe_version_id,
        )

    @staticmethod
    def _require_core_binding(
        binding: UnresolvedIdUpstreamTruthBinding,
        authority: CoreUpstreamAuthority,
        expected_source_id: str,
    ) -> None:
        if not isinstance(binding, UnresolvedIdUpstreamTruthBinding):
            raise TypeError("core upstream truth binding must be typed")
        if binding.authority is not authority:
            raise ValueError(f"{authority.value} truth binding has the wrong authority type")
        if binding.source_id != expected_source_id:
            raise ValueError(
                f"{authority.value} truth binding must match the exact bound identity"
            )

    @property
    def upstream_requirements(self) -> tuple[UpstreamRequirement, ...]:
        return (
            self.snapshot_truth_binding.to_requirement(),
            self.universe_truth_binding.to_requirement(),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "universe_version_id": self.universe_version_id,
            "snapshot_truth_binding": self.snapshot_truth_binding.to_wire(),
            "universe_truth_binding": self.universe_truth_binding.to_wire(),
            "knowledge_cutoff": _wire_time(self.knowledge_cutoff),
            "calendar_version_id": self.calendar_version_id,
            "schema_version_id": self.schema_version_id,
            "environment_fingerprint": self.environment_fingerprint,
            "evaluator_version": self.evaluator_version,
            "core_upstream_requirements": _upstreams_wire(self.upstream_requirements),
        }


@dataclass(frozen=True, slots=True)
class FeatureMaterialization:
    feature_materialization_id: str
    factor_definition_version_id: str
    context: FactorEvaluationContext
    output_artifact_id: str
    output_sha256: str
    provenance_artifact_id: str
    row_count: int
    missing_count: int
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        definition: FactorDefinitionVersion,
        result: EvaluationResult,
        context: FactorEvaluationContext,
        provenance_artifact_id: str,
        proposed_state: TruthAdmissionState,
    ) -> FeatureMaterialization:
        if result.evaluator_version != context.evaluator_version:
            raise ValueError("evaluation result/context evaluator version mismatch")
        if not provenance_artifact_id.startswith("art_sha256_"):
            raise ValueError("FeatureMaterialization requires a provenance Artifact")
        output_sha256 = canonical_sha256({"values": list(result.values)})
        output_artifact_id = "art_sha256_" + output_sha256
        truth_admission = propagate_downstream_ceiling(
            proposed_state, context.upstream_requirements
        )
        payload = {
            "factor_definition_version_id": definition.factor_definition_version_id,
            "context": context.to_wire(),
            "output_artifact_id": output_artifact_id,
            "output_sha256": output_sha256,
            "provenance_artifact_id": provenance_artifact_id,
            "row_count": len(result.values),
            "missing_count": sum(value is None for value in result.values),
            "truth_admission": truth_admission.to_wire(),
        }
        return cls(
            feature_materialization_id="fmat_sha256_" + canonical_sha256(payload),
            factor_definition_version_id=definition.factor_definition_version_id,
            context=context,
            output_artifact_id=output_artifact_id,
            output_sha256=output_sha256,
            provenance_artifact_id=provenance_artifact_id,
            row_count=len(result.values),
            missing_count=sum(value is None for value in result.values),
            truth_admission=truth_admission,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "feature_materialization_id": self.feature_materialization_id,
            "factor_definition_version_id": self.factor_definition_version_id,
            "context": self.context.to_wire(),
            "output_artifact_id": self.output_artifact_id,
            "output_sha256": self.output_sha256,
            "provenance_artifact_id": self.provenance_artifact_id,
            "row_count": self.row_count,
            "missing_count": self.missing_count,
            "truth_admission": self.truth_admission.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class FactorEvaluation:
    factor_evaluation_id: str
    factor_definition_version_id: str
    feature_materialization_id: str
    context: FactorEvaluationContext
    evaluation_provenance_artifact_id: str
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        definition: FactorDefinitionVersion,
        materialization: FeatureMaterialization,
        evaluation_provenance_artifact_id: str,
        proposed_state: TruthAdmissionState,
    ) -> FactorEvaluation:
        if (
            materialization.factor_definition_version_id
            != definition.factor_definition_version_id
        ):
            raise ValueError("materialization must bind the exact FactorDefinitionVersion")
        if not evaluation_provenance_artifact_id.startswith("art_sha256_"):
            raise ValueError("FactorEvaluation requires a provenance Artifact")
        upstreams = (
            *materialization.context.upstream_requirements,
            UpstreamRequirement(
                materialization.feature_materialization_id,
                materialization.truth_admission,
            ),
        )
        truth_admission = propagate_downstream_ceiling(proposed_state, upstreams)
        payload = {
            "factor_definition_version_id": definition.factor_definition_version_id,
            "feature_materialization_id": materialization.feature_materialization_id,
            "context": materialization.context.to_wire(),
            "evaluation_provenance_artifact_id": evaluation_provenance_artifact_id,
            "truth_admission": truth_admission.to_wire(),
        }
        return cls(
            factor_evaluation_id="fev_sha256_" + canonical_sha256(payload),
            factor_definition_version_id=definition.factor_definition_version_id,
            feature_materialization_id=materialization.feature_materialization_id,
            context=materialization.context,
            evaluation_provenance_artifact_id=evaluation_provenance_artifact_id,
            truth_admission=truth_admission,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "factor_evaluation_id": self.factor_evaluation_id,
            "factor_definition_version_id": self.factor_definition_version_id,
            "feature_materialization_id": self.feature_materialization_id,
            "context": self.context.to_wire(),
            "evaluation_provenance_artifact_id": self.evaluation_provenance_artifact_id,
            "truth_admission": self.truth_admission.to_wire(),
        }


__all__ = [
    "CoreUpstreamAuthority",
    "FactorEvaluation",
    "FactorEvaluationContext",
    "FeatureMaterialization",
    "UnresolvedIdUpstreamTruthBinding",
]
