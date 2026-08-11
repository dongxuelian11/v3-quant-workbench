from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    TruthAdmissionState,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

from .binding import StrategyEvaluationBindingVersion
from .ir import StrategyDefinitionVersion, normalize_decimal_string


class StrategyArtifactError(ValueError):
    pass


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StrategyArtifactError(f"{name} must be non-empty without edge whitespace")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StrategyArtifactError(f"{name} must be timezone-aware")


def _wire_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ordered_unique(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    ordered = tuple(sorted(values))
    if len(ordered) != len(set(ordered)):
        raise StrategyArtifactError(f"{name} must be unique")
    for value in ordered:
        _require_text(value, name)
    return ordered


def _require_definition_binding(
    definition: StrategyDefinitionVersion,
    binding: StrategyEvaluationBindingVersion,
    artifact_name: str,
) -> None:
    if binding.strategy_definition_version_id != definition.strategy_definition_version_id:
        raise StrategyArtifactError(f"{artifact_name} definition/binding mismatch")


class SignalDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class InputArtifactEvidence:
    binding_key: str
    artifact_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.binding_key, "binding_key")
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.content_sha256, "content_sha256")

    def to_wire(self) -> dict[str, str]:
        return {
            "binding_key": self.binding_key,
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
        }


def _exact_input_evidence(
    binding: StrategyEvaluationBindingVersion,
    input_artifacts: tuple[InputArtifactEvidence, ...],
    artifact_name: str,
) -> tuple[InputArtifactEvidence, ...]:
    observed = {value.binding_key: value for value in input_artifacts}
    if len(observed) != len(input_artifacts):
        raise StrategyArtifactError(
            f"{artifact_name} input evidence must exactly match binding.input_references; duplicate keys are forbidden"
        )
    expected = {value.binding_key: value for value in binding.input_references}
    if set(observed) != set(expected):
        raise StrategyArtifactError(
            f"{artifact_name} input evidence must exactly match binding.input_references"
        )
    for binding_key, reference in expected.items():
        evidence = observed[binding_key]
        if (
            evidence.artifact_id != reference.artifact_id
            or evidence.content_sha256 != reference.content_sha256
        ):
            raise StrategyArtifactError(
                f"{artifact_name} input evidence must exactly match binding.input_references"
            )
    return tuple(observed[key] for key in sorted(observed))


@dataclass(frozen=True, slots=True)
class SignalRow:
    instrument_id: str
    decision_time: datetime
    signal_kind: str
    value: str
    direction: SignalDirection
    source_node_path: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.instrument_id, "instrument_id")
        _require_aware(self.decision_time, "decision_time")
        _require_text(self.signal_kind, "signal_kind")
        object.__setattr__(self, "value", normalize_decimal_string(self.value, "signal value"))
        if not isinstance(self.direction, SignalDirection):
            raise TypeError("direction must be SignalDirection")
        if not self.source_node_path:
            raise StrategyArtifactError("signal source node path is required")
        for node_id in self.source_node_path:
            _require_text(node_id, "source node ID")

    def to_wire(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "decision_time": _wire_time(self.decision_time),
            "signal_kind": self.signal_kind,
            "value": self.value,
            "direction": self.direction.value,
            "source_node_path": list(self.source_node_path),
        }


@dataclass(frozen=True, slots=True)
class SignalArtifact:
    signal_artifact_id: str
    strategy_definition_version_id: str
    strategy_evaluation_binding_version_id: str
    input_artifacts: tuple[InputArtifactEvidence, ...]
    decision_time: datetime
    rows: tuple[SignalRow, ...]
    missing_instrument_ids: tuple[str, ...]
    truth_admission: TruthAdmissionState
    compiler_version: str
    runtime_profile_id: str
    provenance_sha256: str

    @classmethod
    def create(
        cls,
        *,
        definition: StrategyDefinitionVersion,
        binding: StrategyEvaluationBindingVersion,
        input_artifacts: tuple[InputArtifactEvidence, ...],
        decision_time: datetime,
        rows: tuple[SignalRow, ...],
        missing_instrument_ids: tuple[str, ...],
    ) -> SignalArtifact:
        _require_aware(decision_time, "decision_time")
        _require_definition_binding(definition, binding, "SignalArtifact")
        ordered_inputs = _exact_input_evidence(
            binding, input_artifacts, "SignalArtifact"
        )
        ordered_rows = tuple(sorted(rows, key=lambda value: value.instrument_id))
        if len({value.instrument_id for value in ordered_rows}) != len(ordered_rows):
            raise StrategyArtifactError("SignalArtifact rows must be unique by instrument")
        missing = _ordered_unique(missing_instrument_ids, "missing instrument IDs")
        if set(missing).intersection(value.instrument_id for value in ordered_rows):
            raise StrategyArtifactError("signal instrument cannot be both present and missing")
        universe = set(binding.universe.instrument_ids)
        if any(value.instrument_id not in universe for value in ordered_rows) or not set(missing).issubset(universe):
            raise StrategyArtifactError("SignalArtifact instrument is outside bound universe")
        truth = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            (
                UpstreamRequirement(
                    definition.strategy_definition_version_id,
                    definition.truth_admission,
                ),
                UpstreamRequirement(
                    binding.strategy_evaluation_binding_version_id,
                    binding.truth_admission,
                ),
            ),
        )
        provenance = {
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "strategy_evaluation_binding_version_id": binding.strategy_evaluation_binding_version_id,
            "input_artifacts": [value.to_wire() for value in ordered_inputs],
            "compiler_version": definition.compiler_version,
            "runtime_profile_id": definition.runtime_profile_id,
            "universe_version_id": binding.universe.universe_version_id,
            "membership_sha256": binding.universe.membership_sha256,
        }
        provenance_sha256 = canonical_sha256(provenance)
        payload = {
            **provenance,
            "decision_time": _wire_time(decision_time),
            "rows": [value.to_wire() for value in ordered_rows],
            "missing_instrument_ids": list(missing),
            "truth_admission": truth.to_wire(),
            "provenance_sha256": provenance_sha256,
        }
        return cls(
            signal_artifact_id="sig_sha256_" + canonical_sha256(payload),
            strategy_definition_version_id=definition.strategy_definition_version_id,
            strategy_evaluation_binding_version_id=binding.strategy_evaluation_binding_version_id,
            input_artifacts=ordered_inputs,
            decision_time=decision_time,
            rows=ordered_rows,
            missing_instrument_ids=missing,
            truth_admission=truth,
            compiler_version=definition.compiler_version,
            runtime_profile_id=definition.runtime_profile_id,
            provenance_sha256=provenance_sha256,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "artifact_type": "SignalArtifact",
            "signal_artifact_id": self.signal_artifact_id,
            "strategy_definition_version_id": self.strategy_definition_version_id,
            "strategy_evaluation_binding_version_id": self.strategy_evaluation_binding_version_id,
            "input_artifacts": [value.to_wire() for value in self.input_artifacts],
            "decision_time": _wire_time(self.decision_time),
            "rows": [value.to_wire() for value in self.rows],
            "missing_instrument_ids": list(self.missing_instrument_ids),
            "truth_admission": self.truth_admission.to_wire(),
            "compiler_version": self.compiler_version,
            "runtime_profile_id": self.runtime_profile_id,
            "provenance_sha256": self.provenance_sha256,
        }


def _require_canonical_signal_source(
    signal: SignalArtifact,
    definition: StrategyDefinitionVersion,
    binding: StrategyEvaluationBindingVersion,
) -> tuple[InputArtifactEvidence, ...]:
    if signal.rows != tuple(sorted(signal.rows, key=lambda value: value.instrument_id)):
        raise StrategyArtifactError(
            "PortfolioIntent SignalArtifact rows are not canonical"
        )
    if signal.missing_instrument_ids != tuple(sorted(signal.missing_instrument_ids)):
        raise StrategyArtifactError(
            "PortfolioIntent SignalArtifact missing instruments are not canonical"
        )
    ordered_inputs = _exact_input_evidence(
        binding, signal.input_artifacts, "PortfolioIntent SignalArtifact"
    )
    if signal.input_artifacts != ordered_inputs:
        raise StrategyArtifactError(
            "PortfolioIntent SignalArtifact input evidence is not canonical"
        )
    if (
        signal.compiler_version != definition.compiler_version
        or signal.runtime_profile_id != definition.runtime_profile_id
    ):
        raise StrategyArtifactError(
            "PortfolioIntent SignalArtifact runtime provenance mismatch"
        )
    expected_truth = propagate_downstream_ceiling(
        FORMAL_ADMITTED_CEILING,
        (
            UpstreamRequirement(
                definition.strategy_definition_version_id,
                definition.truth_admission,
            ),
            UpstreamRequirement(
                binding.strategy_evaluation_binding_version_id,
                binding.truth_admission,
            ),
        ),
    )
    if signal.truth_admission != expected_truth:
        raise StrategyArtifactError(
            "PortfolioIntent SignalArtifact truth provenance mismatch"
        )
    provenance = {
        "strategy_definition_version_id": definition.strategy_definition_version_id,
        "strategy_evaluation_binding_version_id": binding.strategy_evaluation_binding_version_id,
        "input_artifacts": [value.to_wire() for value in ordered_inputs],
        "compiler_version": definition.compiler_version,
        "runtime_profile_id": definition.runtime_profile_id,
        "universe_version_id": binding.universe.universe_version_id,
        "membership_sha256": binding.universe.membership_sha256,
    }
    expected_provenance = canonical_sha256(provenance)
    payload = {
        **provenance,
        "decision_time": _wire_time(signal.decision_time),
        "rows": [value.to_wire() for value in signal.rows],
        "missing_instrument_ids": list(signal.missing_instrument_ids),
        "truth_admission": signal.truth_admission.to_wire(),
        "provenance_sha256": expected_provenance,
    }
    if (
        signal.provenance_sha256 != expected_provenance
        or signal.signal_artifact_id != "sig_sha256_" + canonical_sha256(payload)
    ):
        raise StrategyArtifactError(
            "PortfolioIntent SignalArtifact is not a canonical exact source object"
        )
    return ordered_inputs


@dataclass(frozen=True, slots=True)
class SelectionEntry:
    instrument_id: str
    rank: int
    score: str
    reason: str
    source_node_path: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.instrument_id, "instrument_id")
        if self.rank < 1:
            raise StrategyArtifactError("selection rank starts at one")
        object.__setattr__(self, "score", normalize_decimal_string(self.score, "selection score"))
        _require_text(self.reason, "selection reason")
        if not self.source_node_path:
            raise StrategyArtifactError("selection source node path is required")

    def to_wire(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "rank": self.rank,
            "score": self.score,
            "reason": self.reason,
            "source_node_path": list(self.source_node_path),
        }


@dataclass(frozen=True, slots=True)
class SelectionArtifact:
    selection_artifact_id: str
    strategy_definition_version_id: str
    strategy_evaluation_binding_version_id: str
    universe_version_id: str
    membership_artifact_id: str
    membership_sha256: str
    input_artifacts: tuple[InputArtifactEvidence, ...]
    entries: tuple[SelectionEntry, ...]
    excluded_instrument_ids: tuple[str, ...]
    truth_admission: TruthAdmissionState
    provenance_sha256: str

    @classmethod
    def create(
        cls,
        *,
        definition: StrategyDefinitionVersion,
        binding: StrategyEvaluationBindingVersion,
        entries: tuple[SelectionEntry, ...],
        excluded_instrument_ids: tuple[str, ...],
        input_artifacts: tuple[InputArtifactEvidence, ...],
    ) -> SelectionArtifact:
        _require_definition_binding(definition, binding, "SelectionArtifact")
        ordered_inputs = _exact_input_evidence(
            binding, input_artifacts, "SelectionArtifact"
        )
        ordered_entries = tuple(sorted(entries, key=lambda value: value.rank))
        if tuple(value.rank for value in ordered_entries) != tuple(range(1, len(entries) + 1)):
            raise StrategyArtifactError("SelectionArtifact ranks must be contiguous")
        selected_ids = tuple(value.instrument_id for value in ordered_entries)
        if len(selected_ids) != len(set(selected_ids)):
            raise StrategyArtifactError("SelectionArtifact instruments must be unique")
        universe = set(binding.universe.instrument_ids)
        if not set(selected_ids).issubset(universe):
            raise StrategyArtifactError("selected instrument is outside bound universe")
        excluded = _ordered_unique(excluded_instrument_ids, "excluded instrument IDs")
        if not set(excluded).issubset(universe) or set(excluded).intersection(selected_ids):
            raise StrategyArtifactError("selection exclusion boundary is inconsistent")
        if set(selected_ids).union(excluded) != universe:
            raise StrategyArtifactError(
                "SelectionArtifact must cover the exact bound universe membership"
            )
        truth = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            (
                UpstreamRequirement(
                    definition.strategy_definition_version_id,
                    definition.truth_admission,
                ),
                UpstreamRequirement(
                    binding.strategy_evaluation_binding_version_id,
                    binding.truth_admission,
                ),
            ),
        )
        provenance = {
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "strategy_evaluation_binding_version_id": binding.strategy_evaluation_binding_version_id,
            "input_artifacts": [value.to_wire() for value in ordered_inputs],
            "universe_version_id": binding.universe.universe_version_id,
            "membership_artifact_id": binding.universe.membership_artifact_id,
            "membership_sha256": binding.universe.membership_sha256,
        }
        provenance_sha256 = canonical_sha256(provenance)
        payload = {
            **provenance,
            "entries": [value.to_wire() for value in ordered_entries],
            "excluded_instrument_ids": list(excluded),
            "truth_admission": truth.to_wire(),
            "provenance_sha256": provenance_sha256,
        }
        return cls(
            selection_artifact_id="sel_sha256_" + canonical_sha256(payload),
            strategy_definition_version_id=definition.strategy_definition_version_id,
            strategy_evaluation_binding_version_id=binding.strategy_evaluation_binding_version_id,
            universe_version_id=binding.universe.universe_version_id,
            membership_artifact_id=binding.universe.membership_artifact_id,
            membership_sha256=binding.universe.membership_sha256,
            input_artifacts=ordered_inputs,
            entries=ordered_entries,
            excluded_instrument_ids=excluded,
            truth_admission=truth,
            provenance_sha256=provenance_sha256,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "artifact_type": "SelectionArtifact",
            "selection_artifact_id": self.selection_artifact_id,
            "strategy_definition_version_id": self.strategy_definition_version_id,
            "strategy_evaluation_binding_version_id": self.strategy_evaluation_binding_version_id,
            "universe_version_id": self.universe_version_id,
            "membership_artifact_id": self.membership_artifact_id,
            "membership_sha256": self.membership_sha256,
            "input_artifacts": [value.to_wire() for value in self.input_artifacts],
            "entries": [value.to_wire() for value in self.entries],
            "excluded_instrument_ids": list(self.excluded_instrument_ids),
            "truth_admission": self.truth_admission.to_wire(),
            "provenance_sha256": self.provenance_sha256,
        }


def _require_canonical_selection_source(
    selection: SelectionArtifact,
    definition: StrategyDefinitionVersion,
    binding: StrategyEvaluationBindingVersion,
) -> tuple[InputArtifactEvidence, ...]:
    if selection.entries != tuple(sorted(selection.entries, key=lambda value: value.rank)):
        raise StrategyArtifactError(
            "PortfolioIntent SelectionArtifact entries are not canonical"
        )
    if selection.excluded_instrument_ids != tuple(
        sorted(selection.excluded_instrument_ids)
    ):
        raise StrategyArtifactError(
            "PortfolioIntent SelectionArtifact exclusions are not canonical"
        )
    ordered_inputs = _exact_input_evidence(
        binding, selection.input_artifacts, "PortfolioIntent SelectionArtifact"
    )
    if selection.input_artifacts != ordered_inputs:
        raise StrategyArtifactError(
            "PortfolioIntent SelectionArtifact input evidence is not canonical"
        )
    expected_truth = propagate_downstream_ceiling(
        FORMAL_ADMITTED_CEILING,
        (
            UpstreamRequirement(
                definition.strategy_definition_version_id,
                definition.truth_admission,
            ),
            UpstreamRequirement(
                binding.strategy_evaluation_binding_version_id,
                binding.truth_admission,
            ),
        ),
    )
    if selection.truth_admission != expected_truth:
        raise StrategyArtifactError(
            "PortfolioIntent SelectionArtifact truth provenance mismatch"
        )
    provenance = {
        "strategy_definition_version_id": definition.strategy_definition_version_id,
        "strategy_evaluation_binding_version_id": binding.strategy_evaluation_binding_version_id,
        "input_artifacts": [value.to_wire() for value in ordered_inputs],
        "universe_version_id": binding.universe.universe_version_id,
        "membership_artifact_id": binding.universe.membership_artifact_id,
        "membership_sha256": binding.universe.membership_sha256,
    }
    expected_provenance = canonical_sha256(provenance)
    payload = {
        **provenance,
        "entries": [value.to_wire() for value in selection.entries],
        "excluded_instrument_ids": list(selection.excluded_instrument_ids),
        "truth_admission": selection.truth_admission.to_wire(),
        "provenance_sha256": expected_provenance,
    }
    if (
        selection.provenance_sha256 != expected_provenance
        or selection.selection_artifact_id
        != "sel_sha256_" + canonical_sha256(payload)
    ):
        raise StrategyArtifactError(
            "PortfolioIntent SelectionArtifact is not a canonical exact source object"
        )
    return ordered_inputs


@dataclass(frozen=True, slots=True)
class PortfolioIntentItem:
    instrument_id: str
    desired_exposure: str
    source_score: str
    source_node_path: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.instrument_id, "instrument_id")
        object.__setattr__(
            self,
            "desired_exposure",
            normalize_decimal_string(self.desired_exposure, "desired_exposure"),
        )
        object.__setattr__(
            self, "source_score", normalize_decimal_string(self.source_score, "source_score")
        )
        if not self.source_node_path:
            raise StrategyArtifactError("PortfolioIntent item source path is required")

    def to_wire(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "desired_exposure": self.desired_exposure,
            "source_score": self.source_score,
            "source_node_path": list(self.source_node_path),
        }


@dataclass(frozen=True, slots=True)
class PortfolioIntent:
    portfolio_intent_id: str
    strategy_definition_version_id: str
    strategy_evaluation_binding_version_id: str
    source_signal_artifact_id: str | None
    source_selection_artifact_id: str
    source_signal_provenance_sha256: str | None
    source_selection_provenance_sha256: str
    input_artifacts: tuple[InputArtifactEvidence, ...]
    exposure_mode: str
    cash_policy: str
    rebalance_intent: str
    items: tuple[PortfolioIntentItem, ...]
    constraints: Mapping[str, object]
    truth_admission: TruthAdmissionState
    provenance_sha256: str

    def __post_init__(self) -> None:
        if not self.portfolio_intent_id.startswith("pint_sha256_"):
            raise StrategyArtifactError("PortfolioIntent requires canonical Track F identity")
        forbidden = {
            "target_weight_vector",
            "targetweightvector",
            "orders",
            "order",
            "fills",
            "fill",
            "execution",
        }
        if {str(key).lower() for key in self.constraints}.intersection(forbidden):
            raise StrategyArtifactError(
                "PortfolioIntent cannot carry TargetWeightVector, order, fill, or execution fields"
            )
        object.__setattr__(self, "constraints", MappingProxyType(dict(self.constraints)))

    @classmethod
    def create(
        cls,
        *,
        definition: StrategyDefinitionVersion,
        binding: StrategyEvaluationBindingVersion,
        selection_artifact: SelectionArtifact,
        signal_artifact: SignalArtifact | None,
        exposure_mode: str,
        cash_policy: str,
        rebalance_intent: str,
        items: tuple[PortfolioIntentItem, ...],
        constraints: Mapping[str, object],
    ) -> PortfolioIntent:
        _require_definition_binding(definition, binding, "PortfolioIntent")
        if (
            selection_artifact.strategy_definition_version_id
            != definition.strategy_definition_version_id
        ):
            raise StrategyArtifactError(
                "PortfolioIntent SelectionArtifact definition mismatch"
            )
        if (
            selection_artifact.strategy_evaluation_binding_version_id
            != binding.strategy_evaluation_binding_version_id
        ):
            raise StrategyArtifactError(
                "PortfolioIntent SelectionArtifact evaluation binding mismatch"
            )
        if (
            selection_artifact.universe_version_id
            != binding.universe.universe_version_id
            or selection_artifact.membership_artifact_id
            != binding.universe.membership_artifact_id
            or selection_artifact.membership_sha256
            != binding.universe.membership_sha256
        ):
            raise StrategyArtifactError(
                "PortfolioIntent SelectionArtifact universe membership mismatch"
            )
        ordered_inputs = _require_canonical_selection_source(
            selection_artifact,
            definition,
            binding,
        )
        if signal_artifact is not None:
            if (
                signal_artifact.strategy_definition_version_id
                != definition.strategy_definition_version_id
            ):
                raise StrategyArtifactError(
                    "PortfolioIntent SignalArtifact definition mismatch"
                )
            if (
                signal_artifact.strategy_evaluation_binding_version_id
                != binding.strategy_evaluation_binding_version_id
            ):
                raise StrategyArtifactError(
                    "PortfolioIntent SignalArtifact evaluation binding mismatch"
                )
            signal_inputs = _require_canonical_signal_source(
                signal_artifact,
                definition,
                binding,
            )
            if signal_inputs != ordered_inputs:
                raise StrategyArtifactError(
                    "PortfolioIntent source artifacts must share exact input evidence"
                )
        source_selection_artifact_id = selection_artifact.selection_artifact_id
        source_signal_artifact_id = (
            None if signal_artifact is None else signal_artifact.signal_artifact_id
        )
        source_selection_provenance_sha256 = selection_artifact.provenance_sha256
        source_signal_provenance_sha256 = (
            None if signal_artifact is None else signal_artifact.provenance_sha256
        )
        for name, value in (
            ("source_selection_artifact_id", source_selection_artifact_id),
            ("exposure_mode", exposure_mode),
            ("cash_policy", cash_policy),
            ("rebalance_intent", rebalance_intent),
        ):
            _require_text(value, name)
        if source_signal_artifact_id is not None:
            _require_text(source_signal_artifact_id, "source_signal_artifact_id")
        forbidden = {
            "target_weight_vector",
            "targetweightvector",
            "orders",
            "order",
            "fills",
            "fill",
            "execution",
        }
        normalized_constraints = dict(constraints)
        if {str(key).lower() for key in normalized_constraints}.intersection(forbidden):
            raise StrategyArtifactError(
                "PortfolioIntent cannot carry TargetWeightVector, order, fill, or execution fields"
            )
        ordered_items = tuple(sorted(items, key=lambda value: value.instrument_id))
        item_ids = tuple(value.instrument_id for value in ordered_items)
        if len(item_ids) != len(set(item_ids)):
            raise StrategyArtifactError("PortfolioIntent instruments must be unique")
        if not set(item_ids).issubset(binding.universe.instrument_ids):
            raise StrategyArtifactError("PortfolioIntent instrument is outside bound universe")
        selected_ids = {value.instrument_id for value in selection_artifact.entries}
        if set(item_ids) != selected_ids:
            raise StrategyArtifactError(
                "PortfolioIntent items must exactly match source SelectionArtifact"
            )
        truth_requirements = [
            UpstreamRequirement(
                definition.strategy_definition_version_id,
                definition.truth_admission,
            ),
            UpstreamRequirement(
                binding.strategy_evaluation_binding_version_id,
                binding.truth_admission,
            ),
            UpstreamRequirement(
                selection_artifact.selection_artifact_id,
                selection_artifact.truth_admission,
            ),
        ]
        if signal_artifact is not None:
            truth_requirements.append(
                UpstreamRequirement(
                    signal_artifact.signal_artifact_id,
                    signal_artifact.truth_admission,
                )
            )
        truth = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            tuple(truth_requirements),
        )
        provenance = {
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "strategy_evaluation_binding_version_id": binding.strategy_evaluation_binding_version_id,
            "source_signal_artifact_id": source_signal_artifact_id,
            "source_selection_artifact_id": source_selection_artifact_id,
            "source_signal_provenance_sha256": source_signal_provenance_sha256,
            "source_selection_provenance_sha256": source_selection_provenance_sha256,
            "input_artifacts": [value.to_wire() for value in ordered_inputs],
            "publisher_boundary": "PORTFOLIO_SERVICE_IS_SOLE_TARGET_WEIGHT_VECTOR_PUBLISHER",
        }
        provenance_sha256 = canonical_sha256(provenance)
        payload = {
            **provenance,
            "exposure_mode": exposure_mode,
            "cash_policy": cash_policy,
            "rebalance_intent": rebalance_intent,
            "items": [value.to_wire() for value in ordered_items],
            "constraints": normalized_constraints,
            "truth_admission": truth.to_wire(),
            "provenance_sha256": provenance_sha256,
        }
        return cls(
            portfolio_intent_id="pint_sha256_" + canonical_sha256(payload),
            strategy_definition_version_id=definition.strategy_definition_version_id,
            strategy_evaluation_binding_version_id=binding.strategy_evaluation_binding_version_id,
            source_signal_artifact_id=source_signal_artifact_id,
            source_selection_artifact_id=source_selection_artifact_id,
            source_signal_provenance_sha256=source_signal_provenance_sha256,
            source_selection_provenance_sha256=source_selection_provenance_sha256,
            input_artifacts=ordered_inputs,
            exposure_mode=exposure_mode,
            cash_policy=cash_policy,
            rebalance_intent=rebalance_intent,
            items=ordered_items,
            constraints=MappingProxyType(normalized_constraints),
            truth_admission=truth,
            provenance_sha256=provenance_sha256,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "artifact_type": "PortfolioIntent",
            "portfolio_intent_id": self.portfolio_intent_id,
            "strategy_definition_version_id": self.strategy_definition_version_id,
            "strategy_evaluation_binding_version_id": self.strategy_evaluation_binding_version_id,
            "source_signal_artifact_id": self.source_signal_artifact_id,
            "source_selection_artifact_id": self.source_selection_artifact_id,
            "source_signal_provenance_sha256": self.source_signal_provenance_sha256,
            "source_selection_provenance_sha256": self.source_selection_provenance_sha256,
            "input_artifacts": [value.to_wire() for value in self.input_artifacts],
            "exposure_mode": self.exposure_mode,
            "cash_policy": self.cash_policy,
            "rebalance_intent": self.rebalance_intent,
            "items": [value.to_wire() for value in self.items],
            "constraints": dict(self.constraints),
            "truth_admission": self.truth_admission.to_wire(),
            "provenance_sha256": self.provenance_sha256,
            "publisher_boundary": "PORTFOLIO_SERVICE_IS_SOLE_TARGET_WEIGHT_VECTOR_PUBLISHER",
        }


__all__ = [
    "InputArtifactEvidence",
    "PortfolioIntent",
    "PortfolioIntentItem",
    "SelectionArtifact",
    "SelectionEntry",
    "SignalArtifact",
    "SignalDirection",
    "SignalRow",
    "StrategyArtifactError",
]
