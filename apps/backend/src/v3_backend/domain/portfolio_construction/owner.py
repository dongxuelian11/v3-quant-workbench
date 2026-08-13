"""Trusted Portfolio construction boundary for canonical TargetWeight publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from v3_backend.domain.strategies import (
    PortfolioIntent,
    StrategyDefinitionVersion,
    StrategyEvaluationBindingVersion,
)
from v3_backend.domain.weights import RuntimeIdentity

from .model import (
    OptimizerCandidate,
    PortfolioConstructionResult,
    PortfolioConstructionSpecVersion,
)
from .runtime import DeterministicPortfolioConstruction


TARGET_WEIGHT_OWNER_NAMESPACE = "v3.portfolio.target-weight-vector"
TARGET_WEIGHT_PAYLOAD_ROLE = "TARGET_WEIGHT_VECTOR"
TARGET_WEIGHT_SERIALIZATION_VERSION = "v3.target-weight-vector.canonical-json/1.0.0"


class TargetWeightOwnerAuthorityError(RuntimeError):
    """The trusted Portfolio owner rejected a context or publication transition."""


@dataclass(frozen=True, slots=True)
class TargetWeightOwnerPublication:
    target_weight_vector_id: str
    content_sha256: str
    project_id: str
    project_context_revision_id: str
    context_identity: str
    artifact_id: str
    artifact_sha256: str
    byte_size: int
    schema_version: str
    serialization_version: str
    canonical_truth_state: str
    canonical_admission_state: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class CanonicalTargetWeightResult:
    construction: PortfolioConstructionResult
    publication: TargetWeightOwnerPublication


class TrustedTargetWeightOwnerPort(Protocol):
    def _publish_constructed_target(
        self,
        construction: PortfolioConstructionResult,
        *,
        project_id: str,
        project_context_revision_id: str,
        published_at: datetime,
    ) -> TargetWeightOwnerPublication:
        """Internal sink invoked only after the trusted engine produced the result."""


class CanonicalPortfolioOwnerService:
    """The sole supported TargetWeight mint-and-publish path.

    No method accepts a prebuilt ``TargetWeightVector`` or caller-supplied numeric
    vector. The canonical object is produced by the existing deterministic Portfolio
    engine and immediately handed to the internal publication port.
    """

    service_version = "v3.canonical-portfolio-owner-service/1.0.0"

    def __init__(
        self,
        owner: TrustedTargetWeightOwnerPort,
        *,
        construction: DeterministicPortfolioConstruction | None = None,
    ) -> None:
        self._owner = owner
        self._construction = construction or DeterministicPortfolioConstruction()

    def construct_and_publish(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        intent: PortfolioIntent,
        definition: StrategyDefinitionVersion,
        binding: StrategyEvaluationBindingVersion,
        construction_spec: PortfolioConstructionSpecVersion,
        runtime_identity: RuntimeIdentity,
        base_currency: str,
        as_of: datetime,
        decision_time: datetime,
        rebalance_time: datetime,
        valid_until: datetime,
        published_at: datetime,
        optimizer_candidate: OptimizerCandidate | None = None,
    ) -> CanonicalTargetWeightResult:
        if not isinstance(published_at, datetime) or published_at.tzinfo is None:
            raise TargetWeightOwnerAuthorityError("published_at must be timezone-aware")
        result = self._construction.construct(
            intent=intent,
            definition=definition,
            binding=binding,
            construction_spec=construction_spec,
            runtime_identity=runtime_identity,
            base_currency=base_currency,
            as_of=as_of,
            decision_time=decision_time,
            rebalance_time=rebalance_time,
            valid_until=valid_until,
            optimizer_candidate=optimizer_candidate,
        )
        publication = self._owner._publish_constructed_target(
            result,
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            published_at=published_at,
        )
        return CanonicalTargetWeightResult(result, publication)


__all__ = [
    "CanonicalPortfolioOwnerService",
    "CanonicalTargetWeightResult",
    "TARGET_WEIGHT_OWNER_NAMESPACE",
    "TARGET_WEIGHT_PAYLOAD_ROLE",
    "TARGET_WEIGHT_SERIALIZATION_VERSION",
    "TargetWeightOwnerAuthorityError",
    "TargetWeightOwnerPublication",
    "TrustedTargetWeightOwnerPort",
]
