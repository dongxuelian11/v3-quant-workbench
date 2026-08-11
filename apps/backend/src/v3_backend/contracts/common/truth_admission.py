from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from .capability_state import CapabilityTruthState, OperationalTruthState


class TruthAdmissionError(ValueError):
    """Base error for canonical truth/admission contract violations."""


class InvalidTruthAdmissionState(TruthAdmissionError):
    """Raised when a typed state or claim violates the canonical lattice."""


class UnsupportedTruthAdmissionState(TypeError):
    """Raised when callers attempt implicit coercion from an unsupported type."""


class TruthState(str, Enum):
    UNKNOWN = "UNKNOWN"
    NOT_FORMAL = "NOT_FORMAL"
    FORMAL = "FORMAL"


class AdmissionState(str, Enum):
    UNKNOWN = "UNKNOWN"
    PRE_ALPHA = "PRE_ALPHA"
    FORMAL_ADMITTED = "FORMAL_ADMITTED"


class OrderRelation(str, Enum):
    LESS = "LESS"
    EQUAL = "EQUAL"
    GREATER = "GREATER"
    INCOMPARABLE = "INCOMPARABLE"


class PublicationState(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"


class ValidationState(str, Enum):
    NOT_RUN = "NOT_RUN"
    FAILED = "FAILED"
    PASSED = "PASSED"


class CanonicalClaimKind(str, Enum):
    PROPOSAL = "PROPOSAL"
    ADMITTED_CANONICAL_TRUTH = "ADMITTED_CANONICAL_TRUTH"


class LegacyTruthVocabulary(str, Enum):
    CAPABILITY = "CAPABILITY"
    OPERATIONAL = "OPERATIONAL"


class LegacyTruthCompatibilityReason(str, Enum):
    CAPABILITY_FORMAL_IS_NOT_CANONICAL_TRUTH = (
        "CAPABILITY_FORMAL_IS_NOT_CANONICAL_TRUTH"
    )
    CAPABILITY_DEMO_FAILS_CLOSED = "CAPABILITY_DEMO_FAILS_CLOSED"
    CAPABILITY_UNAVAILABLE_FAILS_CLOSED = "CAPABILITY_UNAVAILABLE_FAILS_CLOSED"
    OPERATIONAL_FORMAL_IS_NOT_CANONICAL_TRUTH = (
        "OPERATIONAL_FORMAL_IS_NOT_CANONICAL_TRUTH"
    )
    OPERATIONAL_DEMO_FAILS_CLOSED = "OPERATIONAL_DEMO_FAILS_CLOSED"
    OPERATIONAL_UNAVAILABLE_FAILS_CLOSED = "OPERATIONAL_UNAVAILABLE_FAILS_CLOSED"
    OPERATIONAL_DEGRADED_FAILS_CLOSED = "OPERATIONAL_DEGRADED_FAILS_CLOSED"


_ADMISSIONS_ALLOWED_BY_TRUTH: Mapping[TruthState, frozenset[AdmissionState]] = MappingProxyType(
    {
        TruthState.UNKNOWN: frozenset({AdmissionState.UNKNOWN}),
        TruthState.NOT_FORMAL: frozenset(
            {AdmissionState.UNKNOWN, AdmissionState.PRE_ALPHA}
        ),
        TruthState.FORMAL: frozenset(AdmissionState),
    }
)


@dataclass(frozen=True)
class TruthAdmissionState:
    truth: TruthState
    admission: AdmissionState

    def __post_init__(self) -> None:
        if not isinstance(self.truth, TruthState):
            raise UnsupportedTruthAdmissionState(
                "truth must be a TruthState; implicit string coercion is forbidden"
            )
        if not isinstance(self.admission, AdmissionState):
            raise UnsupportedTruthAdmissionState(
                "admission must be an AdmissionState; implicit string coercion is forbidden"
            )
        if self.admission not in _ADMISSIONS_ALLOWED_BY_TRUTH[self.truth]:
            raise InvalidTruthAdmissionState(
                f"admission {self.admission.value} exceeds truth {self.truth.value}"
            )

    @classmethod
    def from_wire(cls, payload: object) -> TruthAdmissionState:
        if not isinstance(payload, Mapping):
            raise InvalidTruthAdmissionState("truth/admission wire value must be an object")
        expected = {"canonical_truth_state", "canonical_admission_state"}
        if set(payload) != expected:
            raise InvalidTruthAdmissionState(
                f"truth/admission wire keys must be exactly {sorted(expected)}"
            )
        truth_value = payload["canonical_truth_state"]
        admission_value = payload["canonical_admission_state"]
        if not isinstance(truth_value, str) or not isinstance(admission_value, str):
            raise InvalidTruthAdmissionState("truth/admission wire states must be strings")
        try:
            truth = TruthState(truth_value)
            admission = AdmissionState(admission_value)
        except ValueError as error:
            raise InvalidTruthAdmissionState("unknown truth/admission wire state") from error
        return cls(truth=truth, admission=admission)

    def to_wire(self) -> dict[str, str]:
        return {
            "canonical_truth_state": self.truth.value,
            "canonical_admission_state": self.admission.value,
        }


UNKNOWN_CEILING = TruthAdmissionState(TruthState.UNKNOWN, AdmissionState.UNKNOWN)
NOT_FORMAL_CEILING = TruthAdmissionState(
    TruthState.NOT_FORMAL, AdmissionState.UNKNOWN
)
PRE_ALPHA_CEILING = TruthAdmissionState(
    TruthState.NOT_FORMAL, AdmissionState.PRE_ALPHA
)
FORMAL_ADMITTED_CEILING = TruthAdmissionState(
    TruthState.FORMAL, AdmissionState.FORMAL_ADMITTED
)


@dataclass(frozen=True)
class LegacyTruthCompatibilityDecision:
    source_vocabulary: LegacyTruthVocabulary
    source_state: CapabilityTruthState | OperationalTruthState
    canonical_ceiling: TruthAdmissionState
    reason: LegacyTruthCompatibilityReason

    def __post_init__(self) -> None:
        if not isinstance(self.source_vocabulary, LegacyTruthVocabulary):
            raise UnsupportedTruthAdmissionState(
                "source_vocabulary must be LegacyTruthVocabulary"
            )
        if self.source_vocabulary is LegacyTruthVocabulary.CAPABILITY:
            if type(self.source_state) is not CapabilityTruthState:
                raise UnsupportedTruthAdmissionState(
                    "CAPABILITY compatibility requires exact CapabilityTruthState"
                )
        elif type(self.source_state) is not OperationalTruthState:
            raise UnsupportedTruthAdmissionState(
                "OPERATIONAL compatibility requires exact OperationalTruthState"
            )
        if not isinstance(self.canonical_ceiling, TruthAdmissionState):
            raise UnsupportedTruthAdmissionState(
                "canonical_ceiling must be TruthAdmissionState"
            )
        if not isinstance(self.reason, LegacyTruthCompatibilityReason):
            raise UnsupportedTruthAdmissionState(
                "reason must be LegacyTruthCompatibilityReason"
            )


_CAPABILITY_COMPATIBILITY: Mapping[
    CapabilityTruthState,
    tuple[TruthAdmissionState, LegacyTruthCompatibilityReason],
] = MappingProxyType(
    {
        CapabilityTruthState.FORMAL: (
            NOT_FORMAL_CEILING,
            LegacyTruthCompatibilityReason.CAPABILITY_FORMAL_IS_NOT_CANONICAL_TRUTH,
        ),
        CapabilityTruthState.DEMO: (
            UNKNOWN_CEILING,
            LegacyTruthCompatibilityReason.CAPABILITY_DEMO_FAILS_CLOSED,
        ),
        CapabilityTruthState.UNAVAILABLE: (
            UNKNOWN_CEILING,
            LegacyTruthCompatibilityReason.CAPABILITY_UNAVAILABLE_FAILS_CLOSED,
        ),
    }
)
_OPERATIONAL_COMPATIBILITY: Mapping[
    OperationalTruthState,
    tuple[TruthAdmissionState, LegacyTruthCompatibilityReason],
] = MappingProxyType(
    {
        OperationalTruthState.FORMAL: (
            NOT_FORMAL_CEILING,
            LegacyTruthCompatibilityReason.OPERATIONAL_FORMAL_IS_NOT_CANONICAL_TRUTH,
        ),
        OperationalTruthState.DEMO: (
            UNKNOWN_CEILING,
            LegacyTruthCompatibilityReason.OPERATIONAL_DEMO_FAILS_CLOSED,
        ),
        OperationalTruthState.UNAVAILABLE: (
            UNKNOWN_CEILING,
            LegacyTruthCompatibilityReason.OPERATIONAL_UNAVAILABLE_FAILS_CLOSED,
        ),
        OperationalTruthState.DEGRADED: (
            UNKNOWN_CEILING,
            LegacyTruthCompatibilityReason.OPERATIONAL_DEGRADED_FAILS_CLOSED,
        ),
    }
)


_TRUTH_UPPER_BOUNDS: Mapping[TruthState, frozenset[TruthState]] = MappingProxyType(
    {
        TruthState.UNKNOWN: frozenset(TruthState),
        TruthState.NOT_FORMAL: frozenset(
            {TruthState.NOT_FORMAL, TruthState.FORMAL}
        ),
        TruthState.FORMAL: frozenset({TruthState.FORMAL}),
    }
)
_ADMISSION_UPPER_BOUNDS: Mapping[AdmissionState, frozenset[AdmissionState]] = (
    MappingProxyType(
        {
            AdmissionState.UNKNOWN: frozenset(AdmissionState),
            AdmissionState.PRE_ALPHA: frozenset(
                {AdmissionState.PRE_ALPHA, AdmissionState.FORMAL_ADMITTED}
            ),
            AdmissionState.FORMAL_ADMITTED: frozenset(
                {AdmissionState.FORMAL_ADMITTED}
            ),
        }
    )
)


_TRUTH_MEET: Mapping[frozenset[TruthState], TruthState] = MappingProxyType(
    {
        frozenset({TruthState.UNKNOWN}): TruthState.UNKNOWN,
        frozenset({TruthState.NOT_FORMAL}): TruthState.NOT_FORMAL,
        frozenset({TruthState.FORMAL}): TruthState.FORMAL,
        frozenset({TruthState.UNKNOWN, TruthState.NOT_FORMAL}): TruthState.UNKNOWN,
        frozenset({TruthState.UNKNOWN, TruthState.FORMAL}): TruthState.UNKNOWN,
        frozenset({TruthState.NOT_FORMAL, TruthState.FORMAL}): TruthState.NOT_FORMAL,
    }
)
_ADMISSION_MEET: Mapping[frozenset[AdmissionState], AdmissionState] = MappingProxyType(
    {
        frozenset({AdmissionState.UNKNOWN}): AdmissionState.UNKNOWN,
        frozenset({AdmissionState.PRE_ALPHA}): AdmissionState.PRE_ALPHA,
        frozenset({AdmissionState.FORMAL_ADMITTED}): AdmissionState.FORMAL_ADMITTED,
        frozenset({AdmissionState.UNKNOWN, AdmissionState.PRE_ALPHA}): AdmissionState.UNKNOWN,
        frozenset(
            {AdmissionState.UNKNOWN, AdmissionState.FORMAL_ADMITTED}
        ): AdmissionState.UNKNOWN,
        frozenset(
            {AdmissionState.PRE_ALPHA, AdmissionState.FORMAL_ADMITTED}
        ): AdmissionState.PRE_ALPHA,
    }
)


def _require_state(value: object, name: str) -> TruthAdmissionState:
    if not isinstance(value, TruthAdmissionState):
        raise UnsupportedTruthAdmissionState(
            f"{name} must be TruthAdmissionState; implicit coercion is forbidden"
        )
    return value


def is_at_most(left: TruthAdmissionState, right: TruthAdmissionState) -> bool:
    left = _require_state(left, "left")
    right = _require_state(right, "right")
    return (
        right.truth in _TRUTH_UPPER_BOUNDS[left.truth]
        and right.admission in _ADMISSION_UPPER_BOUNDS[left.admission]
    )


def compare_states(
    left: TruthAdmissionState, right: TruthAdmissionState
) -> OrderRelation:
    left = _require_state(left, "left")
    right = _require_state(right, "right")
    left_to_right = is_at_most(left, right)
    right_to_left = is_at_most(right, left)
    if left_to_right and right_to_left:
        return OrderRelation.EQUAL
    if left_to_right:
        return OrderRelation.LESS
    if right_to_left:
        return OrderRelation.GREATER
    return OrderRelation.INCOMPARABLE


def meet_pair(
    left: TruthAdmissionState, right: TruthAdmissionState
) -> TruthAdmissionState:
    left = _require_state(left, "left")
    right = _require_state(right, "right")
    return TruthAdmissionState(
        truth=_TRUTH_MEET[frozenset({left.truth, right.truth})],
        admission=_ADMISSION_MEET[frozenset({left.admission, right.admission})],
    )


def reconcile_capability_truth_ceiling(
    source_state: CapabilityTruthState,
    canonical_upstream_ceiling: TruthAdmissionState,
) -> LegacyTruthCompatibilityDecision:
    if type(source_state) is not CapabilityTruthState:
        raise UnsupportedTruthAdmissionState(
            "source_state must be exact CapabilityTruthState; strings and other truth enums are forbidden"
        )
    canonical_upstream_ceiling = _require_state(
        canonical_upstream_ceiling, "canonical_upstream_ceiling"
    )
    source_ceiling, reason = _CAPABILITY_COMPATIBILITY[source_state]
    return LegacyTruthCompatibilityDecision(
        source_vocabulary=LegacyTruthVocabulary.CAPABILITY,
        source_state=source_state,
        canonical_ceiling=meet_pair(source_ceiling, canonical_upstream_ceiling),
        reason=reason,
    )


def reconcile_operational_truth_ceiling(
    source_state: OperationalTruthState,
    canonical_upstream_ceiling: TruthAdmissionState,
) -> LegacyTruthCompatibilityDecision:
    if type(source_state) is not OperationalTruthState:
        raise UnsupportedTruthAdmissionState(
            "source_state must be exact OperationalTruthState; strings and other truth enums are forbidden"
        )
    canonical_upstream_ceiling = _require_state(
        canonical_upstream_ceiling, "canonical_upstream_ceiling"
    )
    source_ceiling, reason = _OPERATIONAL_COMPATIBILITY[source_state]
    return LegacyTruthCompatibilityDecision(
        source_vocabulary=LegacyTruthVocabulary.OPERATIONAL,
        source_state=source_state,
        canonical_ceiling=meet_pair(source_ceiling, canonical_upstream_ceiling),
        reason=reason,
    )


def meet_all(states: Iterable[TruthAdmissionState]) -> TruthAdmissionState:
    observed = tuple(states)
    if not observed:
        raise InvalidTruthAdmissionState("meet requires at least one upstream state")
    result = _require_state(observed[0], "states[0]")
    for index, state in enumerate(observed[1:], start=1):
        result = meet_pair(result, _require_state(state, f"states[{index}]"))
    return result


@dataclass(frozen=True)
class UpstreamRequirement:
    source_id: str
    state: TruthAdmissionState

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise InvalidTruthAdmissionState("upstream source_id must be non-empty")
        if self.source_id != self.source_id.strip():
            raise InvalidTruthAdmissionState("upstream source_id must not contain edge whitespace")
        _require_state(self.state, "upstream state")


@dataclass(frozen=True)
class UpstreamRequirementAggregate:
    requirements: tuple[UpstreamRequirement, ...]
    ceiling: TruthAdmissionState


def aggregate_upstream_requirements(
    requirements: Iterable[UpstreamRequirement],
) -> UpstreamRequirementAggregate:
    observed = tuple(requirements)
    if not observed:
        raise InvalidTruthAdmissionState("at least one required upstream is required")
    if any(not isinstance(item, UpstreamRequirement) for item in observed):
        raise UnsupportedTruthAdmissionState(
            "requirements must contain only UpstreamRequirement values"
        )
    ordered = tuple(sorted(observed, key=lambda item: item.source_id))
    source_ids = tuple(item.source_id for item in ordered)
    if len(source_ids) != len(set(source_ids)):
        raise InvalidTruthAdmissionState("required upstream source_id values must be unique")
    return UpstreamRequirementAggregate(
        requirements=ordered,
        ceiling=meet_all(item.state for item in ordered),
    )


def propagate_downstream_ceiling(
    proposed_state: TruthAdmissionState,
    required_upstreams: Iterable[UpstreamRequirement],
) -> TruthAdmissionState:
    proposed_state = _require_state(proposed_state, "proposed_state")
    aggregate = aggregate_upstream_requirements(required_upstreams)
    return meet_pair(proposed_state, aggregate.ceiling)


@dataclass(frozen=True)
class TruthAdmissionClaim:
    state: TruthAdmissionState
    publication: PublicationState
    validation: ValidationState
    kind: CanonicalClaimKind

    def __post_init__(self) -> None:
        _require_state(self.state, "claim state")
        if not isinstance(self.publication, PublicationState):
            raise UnsupportedTruthAdmissionState("publication must be PublicationState")
        if not isinstance(self.validation, ValidationState):
            raise UnsupportedTruthAdmissionState("validation must be ValidationState")
        if not isinstance(self.kind, CanonicalClaimKind):
            raise UnsupportedTruthAdmissionState("kind must be CanonicalClaimKind")
        if self.kind is CanonicalClaimKind.ADMITTED_CANONICAL_TRUTH:
            if self.state != FORMAL_ADMITTED_CEILING:
                raise InvalidTruthAdmissionState(
                    "admitted canonical truth requires the formal-admitted state"
                )
            if self.publication is not PublicationState.PUBLISHED:
                raise InvalidTruthAdmissionState(
                    "admitted canonical truth requires explicit publication"
                )
            if self.validation is not ValidationState.PASSED:
                raise InvalidTruthAdmissionState(
                    "admitted canonical truth requires explicit validation PASS"
                )
