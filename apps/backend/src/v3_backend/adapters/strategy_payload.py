"""Strategy-owner adapter from exact input bindings to the shared P1 contract."""

from __future__ import annotations

from dataclasses import dataclass

from v3_backend.domain.payload_authority import (
    CanonicalPayloadBinding,
    PayloadResolutionRequest,
)
from v3_backend.domain.strategies.binding import StrategyEvaluationBindingVersion


class StrategyPayloadBindingError(ValueError):
    """The Strategy owner cannot establish the requested canonical binding."""


@dataclass(frozen=True, slots=True)
class StrategyPayloadOwnerRecord:
    """Canonical owner metadata registered at the trusted Strategy adapter boundary."""

    binding_key: str
    owner_namespace: str
    owner_id: str
    owner_version: str
    payload_role: str
    artifact_id: str
    expected_sha256: str
    expected_byte_size: int
    context_identity: str
    binding_version: str
    schema_fingerprint: str
    semantic_fingerprint: str | None = None
    provenance_reference_id: str | None = None

    def request_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.owner_namespace,
            self.owner_id,
            self.owner_version,
            self.payload_role,
            self.context_identity,
        )


class StrategyPayloadBindingResolver:
    """Resolve only owner records that exactly back one Strategy binding input."""

    def __init__(
        self,
        *,
        binding: StrategyEvaluationBindingVersion,
        records: tuple[StrategyPayloadOwnerRecord, ...],
    ) -> None:
        if not isinstance(binding, StrategyEvaluationBindingVersion):
            raise TypeError("binding must be StrategyEvaluationBindingVersion")
        references = {value.binding_key: value for value in binding.input_references}
        by_request: dict[
            tuple[str, str, str, str, str], StrategyPayloadOwnerRecord
        ] = {}
        observed_keys: set[str] = set()
        for record in records:
            if not isinstance(record, StrategyPayloadOwnerRecord):
                raise TypeError("records must contain StrategyPayloadOwnerRecord values")
            try:
                reference = references[record.binding_key]
            except KeyError as exc:
                raise StrategyPayloadBindingError(
                    f"owner record has unknown binding key: {record.binding_key}"
                ) from exc
            if record.binding_key in observed_keys:
                raise StrategyPayloadBindingError("owner record binding keys must be unique")
            if (
                record.artifact_id != reference.artifact_id
                or record.expected_sha256 != reference.content_sha256
                or record.owner_id != reference.source_id
            ):
                raise StrategyPayloadBindingError(
                    f"owner record {record.binding_key} does not back the exact Strategy input reference"
                )
            key = record.request_key()
            if key in by_request:
                raise StrategyPayloadBindingError(
                    "owner records must have unique P1 request identities"
                )
            by_request[key] = record
            observed_keys.add(record.binding_key)
        if observed_keys != set(references):
            raise StrategyPayloadBindingError(
                "owner records must exactly cover Strategy binding inputs"
            )
        self._records = by_request

    def resolve(
        self, request: PayloadResolutionRequest
    ) -> CanonicalPayloadBinding | None:
        if not isinstance(request, PayloadResolutionRequest):
            raise TypeError("Strategy payload resolution requires PayloadResolutionRequest")
        record = self._records.get(
            (
                request.owner_namespace,
                request.owner_id,
                request.owner_version,
                request.payload_role,
                request.context_identity,
            )
        )
        if record is None:
            return None
        return CanonicalPayloadBinding(
            owner_namespace=record.owner_namespace,
            owner_id=record.owner_id,
            owner_version=record.owner_version,
            payload_role=record.payload_role,
            artifact_id=record.artifact_id,
            expected_sha256=record.expected_sha256,
            expected_byte_size=record.expected_byte_size,
            context_identity=record.context_identity,
            binding_version=record.binding_version,
            schema_fingerprint=record.schema_fingerprint,
            semantic_fingerprint=record.semantic_fingerprint,
            provenance_reference_id=record.provenance_reference_id,
        )


__all__ = (
    "StrategyPayloadBindingError",
    "StrategyPayloadBindingResolver",
    "StrategyPayloadOwnerRecord",
)
