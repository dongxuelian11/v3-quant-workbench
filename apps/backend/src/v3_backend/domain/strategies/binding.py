from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
    UpstreamRequirement,
    meet_pair,
    propagate_downstream_ceiling,
)
from v3_backend.domain.datasets import DatasetVersion
from v3_backend.domain.factors import FactorEvaluation, FeatureMaterialization
from v3_backend.provenance.canonical_hash import canonical_sha256

from .ir import StrategyDefinitionVersion


class StrategyBindingError(ValueError):
    """Raised when an evaluation binding is not exact or internally consistent."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NON_EXACT = {"latest", "current", "unresolved", "auto", "default"}


class ExternalReferenceResolution(StrEnum):
    """Resolution evidence available to Track F for an external owner reference."""

    UNRESOLVED_CALLER_ASSERTED = "UNRESOLVED_CALLER_ASSERTED"


def _cap_unresolved_truth(
    value: TruthAdmissionState, name: str
) -> TruthAdmissionState:
    if not isinstance(value, TruthAdmissionState):
        raise TypeError(f"{name} truth_admission must be TruthAdmissionState")
    return meet_pair(value, PRE_ALPHA_CEILING)


def _require_exact_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StrategyBindingError(f"{name} must be non-empty without edge whitespace")
    lowered = value.lower()
    if lowered in _NON_EXACT or lowered.startswith("latest:"):
        raise StrategyBindingError(f"{name} must be exact; aliases are forbidden")


def _require_sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise StrategyBindingError(f"{name} must be a lowercase full SHA-256")


def _require_artifact(value: str, name: str, content_sha256: str | None = None) -> None:
    if not isinstance(value, str) or not value.startswith("art_sha256_"):
        raise StrategyBindingError(f"{name} must be a content-addressed Artifact")
    suffix = value.removeprefix("art_sha256_")
    _require_sha256(suffix, f"{name} suffix")
    if content_sha256 is not None and suffix != content_sha256:
        raise StrategyBindingError(f"{name} must match its exact content SHA-256")


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StrategyBindingError(f"{name} must be timezone-aware")


def _wire_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class EvaluationPeriod:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_aware(self.start, "evaluation period start")
        _require_aware(self.end, "evaluation period end")
        if self.end < self.start:
            raise StrategyBindingError("evaluation period end cannot precede start")

    def to_wire(self) -> dict[str, str]:
        return {"start": _wire_time(self.start), "end": _wire_time(self.end)}


@dataclass(frozen=True, slots=True)
class ExactSnapshotReference:
    """Exact research binding data without a canonical Snapshot receipt."""

    snapshot_id: str
    content_sha256: str
    truth_admission: TruthAdmissionState
    resolution: ExternalReferenceResolution = field(
        init=False, default=ExternalReferenceResolution.UNRESOLVED_CALLER_ASSERTED
    )

    def __post_init__(self) -> None:
        _require_exact_text(self.snapshot_id, "snapshot_id")
        _require_sha256(self.content_sha256, "snapshot content_sha256")
        object.__setattr__(
            self,
            "truth_admission",
            _cap_unresolved_truth(self.truth_admission, "snapshot"),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "reference_kind": "SNAPSHOT_RESEARCH_EVALUATION_REFERENCE",
            "resolution": self.resolution.value,
            "snapshot_id": self.snapshot_id,
            "content_sha256": self.content_sha256,
            "truth_admission": self.truth_admission.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class ExactUniverseReference:
    """Exact research membership binding without a canonical Universe receipt."""

    universe_version_id: str
    definition_sha256: str
    membership_artifact_id: str
    membership_sha256: str
    instrument_ids: tuple[str, ...]
    truth_admission: TruthAdmissionState
    resolution: ExternalReferenceResolution = field(
        init=False, default=ExternalReferenceResolution.UNRESOLVED_CALLER_ASSERTED
    )

    def __post_init__(self) -> None:
        _require_exact_text(self.universe_version_id, "universe_version_id")
        _require_sha256(self.definition_sha256, "universe definition_sha256")
        _require_sha256(self.membership_sha256, "universe membership_sha256")
        _require_artifact(
            self.membership_artifact_id,
            "membership_artifact_id",
            self.membership_sha256,
        )
        ordered = tuple(sorted(self.instrument_ids))
        if not ordered or len(ordered) != len(set(ordered)):
            raise StrategyBindingError("universe instrument IDs must be non-empty and unique")
        for instrument_id in ordered:
            _require_exact_text(instrument_id, "instrument_id")
        object.__setattr__(
            self,
            "truth_admission",
            _cap_unresolved_truth(self.truth_admission, "universe"),
        )
        object.__setattr__(self, "instrument_ids", ordered)

    def to_wire(self) -> dict[str, object]:
        return {
            "reference_kind": "UNIVERSE_RESEARCH_EVALUATION_REFERENCE",
            "resolution": self.resolution.value,
            "universe_version_id": self.universe_version_id,
            "definition_sha256": self.definition_sha256,
            "membership_artifact_id": self.membership_artifact_id,
            "membership_sha256": self.membership_sha256,
            "instrument_ids": list(self.instrument_ids),
            "instrument_ids_sha256": canonical_sha256(list(self.instrument_ids)),
            "truth_admission": self.truth_admission.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class ExactCalendarReference:
    """Exact deterministic calendar binding without a canonical Calendar receipt."""

    calendar_version_id: str
    content_sha256: str
    timezone_name: str
    truth_admission: TruthAdmissionState
    resolution: ExternalReferenceResolution = field(
        init=False, default=ExternalReferenceResolution.UNRESOLVED_CALLER_ASSERTED
    )

    def __post_init__(self) -> None:
        _require_exact_text(self.calendar_version_id, "calendar_version_id")
        _require_sha256(self.content_sha256, "calendar content_sha256")
        _require_exact_text(self.timezone_name, "timezone_name")
        if "/" not in self.timezone_name and self.timezone_name != "UTC":
            raise StrategyBindingError("timezone_name must be an explicit IANA name or UTC")
        object.__setattr__(
            self,
            "truth_admission",
            _cap_unresolved_truth(self.truth_admission, "calendar"),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "reference_kind": "CALENDAR_RESEARCH_EVALUATION_REFERENCE",
            "resolution": self.resolution.value,
            "calendar_version_id": self.calendar_version_id,
            "content_sha256": self.content_sha256,
            "timezone_name": self.timezone_name,
            "truth_admission": self.truth_admission.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class GenericAdmittedArtifactReference:
    """Unresolved typed extension point; it does not prove an upstream owner receipt."""

    artifact_type: str
    source_id: str
    artifact_id: str
    content_sha256: str
    truth_admission: TruthAdmissionState
    resolution: ExternalReferenceResolution = field(
        init=False, default=ExternalReferenceResolution.UNRESOLVED_CALLER_ASSERTED
    )

    def __post_init__(self) -> None:
        _require_exact_text(self.artifact_type, "artifact_type")
        _require_exact_text(self.source_id, "source_id")
        _require_sha256(self.content_sha256, "artifact content_sha256")
        _require_artifact(self.artifact_id, "artifact_id", self.content_sha256)
        object.__setattr__(
            self,
            "truth_admission",
            _cap_unresolved_truth(self.truth_admission, "artifact"),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "source_id": self.source_id,
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "truth_admission": self.truth_admission.to_wire(),
            "resolution": self.resolution.value,
            "ownership": "UNRESOLVED_EXTERNAL_REFERENCE",
        }


@dataclass(frozen=True, slots=True)
class CanonicalOwnerArtifactReference:
    """Untrusted intent naming an artifact that formal execution must re-resolve.

    This value deliberately carries no truth/admission claim.  It becomes usable
    only when an injected canonical owner repository resolves the exact immutable
    publication and P1 verifies the published bytes.
    """

    artifact_type: str
    owner_namespace: str
    owner_id: str
    owner_version: str
    payload_role: str
    artifact_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "artifact_type",
            "owner_namespace",
            "owner_id",
            "owner_version",
            "payload_role",
        ):
            _require_exact_text(getattr(self, name), name)
        _require_sha256(self.content_sha256, "artifact content_sha256")
        _require_artifact(self.artifact_id, "artifact_id", self.content_sha256)

    def to_wire(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "owner_namespace": self.owner_namespace,
            "owner_id": self.owner_id,
            "owner_version": self.owner_version,
            "payload_role": self.payload_role,
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "resolution": "CANONICAL_OWNER_REQUIRED",
            "ownership": "UNTRUSTED_REFERENCE_INTENT",
        }


@dataclass(frozen=True, slots=True)
class BoundInputReference:
    binding_key: str
    artifact_kind: str
    source_id: str
    artifact_id: str
    content_sha256: str
    truth_admission: TruthAdmissionState

    def __post_init__(self) -> None:
        _require_exact_text(self.binding_key, "binding_key")
        _require_exact_text(self.artifact_kind, "artifact_kind")
        _require_exact_text(self.source_id, "source_id")
        _require_sha256(self.content_sha256, "input content_sha256")
        _require_artifact(self.artifact_id, "input artifact_id", self.content_sha256)
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("input truth_admission must be TruthAdmissionState")

    @classmethod
    def from_feature_materialization(
        cls, binding_key: str, materialization: FeatureMaterialization
    ) -> BoundInputReference:
        return cls(
            binding_key=binding_key,
            artifact_kind="FEATURE_MATERIALIZATION",
            source_id=materialization.feature_materialization_id,
            artifact_id=materialization.output_artifact_id,
            content_sha256=materialization.output_sha256,
            truth_admission=materialization.truth_admission,
        )

    @classmethod
    def from_generic(
        cls, binding_key: str, reference: GenericAdmittedArtifactReference
    ) -> BoundInputReference:
        return cls(
            binding_key=binding_key,
            artifact_kind=reference.artifact_type,
            source_id=reference.source_id,
            artifact_id=reference.artifact_id,
            content_sha256=reference.content_sha256,
            truth_admission=reference.truth_admission,
        )

    @classmethod
    def from_canonical_owner(
        cls, binding_key: str, reference: CanonicalOwnerArtifactReference
    ) -> BoundInputReference:
        return cls(
            binding_key=binding_key,
            artifact_kind=reference.artifact_type,
            source_id=reference.owner_id,
            artifact_id=reference.artifact_id,
            content_sha256=reference.content_sha256,
            truth_admission=PRE_ALPHA_CEILING,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "binding_key": self.binding_key,
            "artifact_kind": self.artifact_kind,
            "source_id": self.source_id,
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "truth_admission": self.truth_admission.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class StrategyEvaluationBindingVersion:
    strategy_evaluation_binding_version_id: str
    strategy_definition_version_id: str
    dataset_version_id: str
    factor_evaluation_ids: tuple[str, ...]
    feature_materialization_ids: tuple[str, ...]
    snapshot: ExactSnapshotReference
    universe: ExactUniverseReference
    period: EvaluationPeriod
    knowledge_cutoff: datetime
    calendar: ExactCalendarReference
    compiler_version: str
    runtime_profile_id: str
    environment_fingerprint: str
    input_references: tuple[BoundInputReference, ...]
    generic_artifact_references: tuple[GenericAdmittedArtifactReference, ...]
    canonical_owner_references: tuple[CanonicalOwnerArtifactReference, ...]
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        definition: StrategyDefinitionVersion,
        dataset: DatasetVersion,
        factor_evaluations: tuple[FactorEvaluation, ...],
        feature_materializations: tuple[FeatureMaterialization, ...],
        snapshot: ExactSnapshotReference,
        universe: ExactUniverseReference,
        period: EvaluationPeriod,
        knowledge_cutoff: datetime,
        calendar: ExactCalendarReference,
        compiler_version: str,
        runtime_profile_id: str,
        environment_fingerprint: str,
        input_references: tuple[BoundInputReference, ...],
        generic_artifact_references: tuple[GenericAdmittedArtifactReference, ...] = (),
        canonical_owner_references: tuple[CanonicalOwnerArtifactReference, ...] = (),
    ) -> StrategyEvaluationBindingVersion:
        _require_aware(knowledge_cutoff, "knowledge_cutoff")
        for name, value in (
            ("compiler_version", compiler_version),
            ("runtime_profile_id", runtime_profile_id),
            ("environment_fingerprint", environment_fingerprint),
        ):
            _require_exact_text(value, name)
        if compiler_version != definition.compiler_version:
            raise StrategyBindingError("binding compiler must match StrategyDefinitionVersion")
        if runtime_profile_id != definition.runtime_profile_id:
            raise StrategyBindingError("binding runtime must match StrategyDefinitionVersion")
        if environment_fingerprint != dataset.binding.environment_fingerprint:
            raise StrategyBindingError("binding environment must match DatasetVersion")
        if knowledge_cutoff != dataset.binding.knowledge_cutoff:
            raise StrategyBindingError("binding knowledge cutoff must match DatasetVersion")
        if snapshot.snapshot_id != dataset.binding.snapshot_id:
            raise StrategyBindingError("exact Snapshot reference must match DatasetVersion")
        if universe.universe_version_id != dataset.binding.universe_version_id:
            raise StrategyBindingError("exact Universe reference must match DatasetVersion")
        if calendar.calendar_version_id != dataset.binding.calendar_version_id:
            raise StrategyBindingError("exact Calendar reference must match DatasetVersion")

        evaluation_ids = tuple(sorted(value.factor_evaluation_id for value in factor_evaluations))
        if not evaluation_ids or evaluation_ids != dataset.factor_evaluation_ids:
            raise StrategyBindingError(
                "factor evaluations must exactly match DatasetVersion membership"
            )
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise StrategyBindingError("factor evaluations must be unique")
        materialization_by_id = {
            value.feature_materialization_id: value for value in feature_materializations
        }
        if len(materialization_by_id) != len(feature_materializations):
            raise StrategyBindingError("feature materializations must be unique")
        expected_materialization_ids = tuple(
            sorted(value.feature_materialization_id for value in factor_evaluations)
        )
        if tuple(sorted(materialization_by_id)) != expected_materialization_ids:
            raise StrategyBindingError(
                "feature materializations must exactly match FactorEvaluation bindings"
            )

        slot_specs = {
            value["binding_key"]: value
            for value in definition.canonical_ir["required_bindings"]  # type: ignore[index]
        }
        inputs_by_key = {value.binding_key: value for value in input_references}
        if len(inputs_by_key) != len(input_references):
            raise StrategyBindingError("bound input keys must be unique")
        if set(inputs_by_key) != set(slot_specs):
            raise StrategyBindingError(
                "every required Strategy IR binding must resolve exactly once"
            )
        generic_by_source = {
            value.source_id: value for value in generic_artifact_references
        }
        if len(generic_by_source) != len(generic_artifact_references):
            raise StrategyBindingError("generic admitted artifact source IDs must be unique")
        canonical_by_owner = {
            value.owner_id: value for value in canonical_owner_references
        }
        if len(canonical_by_owner) != len(canonical_owner_references):
            raise StrategyBindingError("canonical owner reference IDs must be unique")
        if set(canonical_by_owner).intersection(generic_by_source):
            raise StrategyBindingError(
                "one Strategy source cannot be both canonical-owner intent and unresolved caller assertion"
            )
        allowed_inputs: dict[
            tuple[str, str, str], tuple[str, TruthAdmissionState]
        ] = {}
        for materialization in feature_materializations:
            allowed_inputs[
                (
                    "FEATURE_MATERIALIZATION",
                    materialization.feature_materialization_id,
                    materialization.output_artifact_id,
                )
            ] = (materialization.output_sha256, materialization.truth_admission)
        for reference in generic_artifact_references:
            allowed_inputs[
                (reference.artifact_type, reference.source_id, reference.artifact_id)
            ] = (reference.content_sha256, reference.truth_admission)
        for reference in canonical_owner_references:
            allowed_inputs[
                (reference.artifact_type, reference.owner_id, reference.artifact_id)
            ] = (reference.content_sha256, PRE_ALPHA_CEILING)
        for key, bound_input in inputs_by_key.items():
            if slot_specs[key]["artifact_kind"] != bound_input.artifact_kind:
                raise StrategyBindingError(
                    f"binding {key} artifact kind does not match Strategy IR"
                )
            source_key = (
                bound_input.artifact_kind,
                bound_input.source_id,
                bound_input.artifact_id,
            )
            try:
                expected_sha, expected_truth = allowed_inputs[source_key]
            except KeyError as error:
                raise StrategyBindingError(
                    f"binding {key} is not backed by an exact admitted input reference"
                ) from error
            if (
                bound_input.content_sha256 != expected_sha
                or (
                    bound_input.source_id not in canonical_by_owner
                    and bound_input.truth_admission != expected_truth
                )
            ):
                raise StrategyBindingError(
                    f"binding {key} content/truth does not match its canonical source"
                )

        requirements: dict[str, TruthAdmissionState] = {}

        def add_requirement(source_id: str, state: TruthAdmissionState) -> None:
            observed = requirements.get(source_id)
            if observed is not None and observed != state:
                raise StrategyBindingError(
                    f"conflicting truth states for upstream {source_id}"
                )
            requirements[source_id] = state

        add_requirement(
            definition.strategy_definition_version_id, definition.truth_admission
        )
        add_requirement(dataset.dataset_version_id, dataset.truth_admission)
        for evaluation in factor_evaluations:
            add_requirement(evaluation.factor_evaluation_id, evaluation.truth_admission)
        for materialization in feature_materializations:
            add_requirement(
                materialization.feature_materialization_id,
                materialization.truth_admission,
            )
        add_requirement(snapshot.snapshot_id, snapshot.truth_admission)
        add_requirement(universe.universe_version_id, universe.truth_admission)
        add_requirement(calendar.calendar_version_id, calendar.truth_admission)
        for reference in generic_artifact_references:
            add_requirement(reference.source_id, reference.truth_admission)
        truth_admission = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            tuple(
                UpstreamRequirement(source_id, requirements[source_id])
                for source_id in sorted(requirements)
            ),
        )
        payload = {
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "dataset_version_id": dataset.dataset_version_id,
            "factor_evaluation_ids": list(evaluation_ids),
            "feature_materialization_ids": list(expected_materialization_ids),
            "snapshot": snapshot.to_wire(),
            "universe": universe.to_wire(),
            "period": period.to_wire(),
            "knowledge_cutoff": _wire_time(knowledge_cutoff),
            "calendar": calendar.to_wire(),
            "compiler_version": compiler_version,
            "runtime_profile_id": runtime_profile_id,
            "environment_fingerprint": environment_fingerprint,
            "input_references": [
                inputs_by_key[key].to_wire() for key in sorted(inputs_by_key)
            ],
            "generic_artifact_references": [
                generic_by_source[key].to_wire() for key in sorted(generic_by_source)
            ],
            "truth_admission": truth_admission.to_wire(),
        }
        if canonical_by_owner:
            payload["canonical_owner_references"] = [
                canonical_by_owner[key].to_wire() for key in sorted(canonical_by_owner)
            ]
        return cls(
            strategy_evaluation_binding_version_id="sebv_sha256_"
            + canonical_sha256(payload),
            strategy_definition_version_id=definition.strategy_definition_version_id,
            dataset_version_id=dataset.dataset_version_id,
            factor_evaluation_ids=evaluation_ids,
            feature_materialization_ids=expected_materialization_ids,
            snapshot=snapshot,
            universe=universe,
            period=period,
            knowledge_cutoff=knowledge_cutoff,
            calendar=calendar,
            compiler_version=compiler_version,
            runtime_profile_id=runtime_profile_id,
            environment_fingerprint=environment_fingerprint,
            input_references=tuple(inputs_by_key[key] for key in sorted(inputs_by_key)),
            generic_artifact_references=tuple(
                generic_by_source[key] for key in sorted(generic_by_source)
            ),
            canonical_owner_references=tuple(
                canonical_by_owner[key] for key in sorted(canonical_by_owner)
            ),
            truth_admission=truth_admission,
        )

    def to_wire(self) -> dict[str, object]:
        wire = {
            "strategy_evaluation_binding_version_id": self.strategy_evaluation_binding_version_id,
            "strategy_definition_version_id": self.strategy_definition_version_id,
            "dataset_version_id": self.dataset_version_id,
            "factor_evaluation_ids": list(self.factor_evaluation_ids),
            "feature_materialization_ids": list(self.feature_materialization_ids),
            "snapshot": self.snapshot.to_wire(),
            "universe": self.universe.to_wire(),
            "period": self.period.to_wire(),
            "knowledge_cutoff": _wire_time(self.knowledge_cutoff),
            "calendar": self.calendar.to_wire(),
            "compiler_version": self.compiler_version,
            "runtime_profile_id": self.runtime_profile_id,
            "environment_fingerprint": self.environment_fingerprint,
            "input_references": [value.to_wire() for value in self.input_references],
            "generic_artifact_references": [
                value.to_wire() for value in self.generic_artifact_references
            ],
            "truth_admission": self.truth_admission.to_wire(),
        }
        if self.canonical_owner_references:
            wire["canonical_owner_references"] = [
                value.to_wire() for value in self.canonical_owner_references
            ]
        return wire


__all__ = [
    "BoundInputReference",
    "CanonicalOwnerArtifactReference",
    "EvaluationPeriod",
    "ExactCalendarReference",
    "ExactSnapshotReference",
    "ExactUniverseReference",
    "ExternalReferenceResolution",
    "GenericAdmittedArtifactReference",
    "StrategyBindingError",
    "StrategyEvaluationBindingVersion",
]
