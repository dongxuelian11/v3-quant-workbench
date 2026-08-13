"""Canonical request-to-verified-bytes resolution orchestration."""

from __future__ import annotations

import hashlib

from v3_backend.domain.artifacts.exceptions import IntegrityMismatch, InvalidArtifactIdentity
from v3_backend.domain.artifacts.identity import (
    artifact_id_for_bytes,
    sha256_from_artifact_id,
)

from .exceptions import (
    PayloadArtifactIdMismatch,
    PayloadArtifactUnavailable,
    PayloadBindingUnavailable,
    PayloadContentMismatch,
    PayloadContextMismatch,
    PayloadOwnerMismatch,
    PayloadReadBoundExceeded,
    PayloadRoleMismatch,
    PayloadSizeMismatch,
)
from .model import (
    RESOLVER_CONTRACT_VERSION,
    CanonicalPayloadBinding,
    PayloadResolutionReceipt,
    PayloadResolutionRequest,
    PayloadResolutionResult,
    VerifiedPayload,
)
from .ports import CanonicalPayloadBindingResolver, VerifiedArtifactByteReader


class CanonicalPayloadResolver:
    """The only shared formal path from untrusted intent to verified bytes.

    Neither a caller-constructed binding, ``VerifiedPayload``, nor receipt is accepted
    as input. Each call starts with a request and crosses both injected boundaries.
    """

    contract_version = RESOLVER_CONTRACT_VERSION

    def __init__(
        self,
        *,
        binding_resolver: CanonicalPayloadBindingResolver,
        byte_reader: VerifiedArtifactByteReader,
    ) -> None:
        self._binding_resolver = binding_resolver
        self._byte_reader = byte_reader

    def resolve(self, request: PayloadResolutionRequest) -> PayloadResolutionResult:
        if not isinstance(request, PayloadResolutionRequest):
            raise TypeError("formal resolution requires PayloadResolutionRequest")

        binding = self._binding_resolver.resolve(request)
        if binding is None:
            raise PayloadBindingUnavailable("canonical owner returned no payload binding")
        if not isinstance(binding, CanonicalPayloadBinding):
            raise TypeError("binding resolver returned a non-canonical binding value")

        self._verify_request_binding(request, binding)

        try:
            payload = self._byte_reader.read_bytes(
                binding.artifact_id,
                max_bytes=request.max_bytes,
            )
        except IntegrityMismatch as exc:
            if "read bound" in str(exc) or "exceeds read bound" in str(exc):
                raise PayloadReadBoundExceeded(str(exc)) from exc
            raise PayloadContentMismatch("artifact reader rejected byte integrity") from exc
        except FileNotFoundError as exc:
            raise PayloadArtifactUnavailable(
                f"artifact is unavailable: {binding.artifact_id}"
            ) from exc

        if not isinstance(payload, bytes):
            raise PayloadContentMismatch("artifact reader must return bytes")
        actual_size = len(payload)
        if actual_size > request.max_bytes:
            raise PayloadReadBoundExceeded(
                f"actual payload size {actual_size} exceeds max_bytes {request.max_bytes}"
            )

        # Defense in depth: the P1 boundary re-hashes the exact returned bytes even
        # when the reused Artifact Store has already performed its own integrity check.
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        actual_artifact_id = artifact_id_for_bytes(payload)
        if actual_sha256 != binding.expected_sha256:
            raise PayloadContentMismatch(
                "actual payload SHA-256 does not match the canonical owner binding"
            )
        if actual_artifact_id != binding.artifact_id:
            raise PayloadArtifactIdMismatch(
                "actual byte identity does not match the bound artifact ID"
            )
        if actual_size != binding.expected_byte_size:
            raise PayloadSizeMismatch(
                "actual payload byte size does not match the canonical owner binding"
            )

        request_identity = request.request_identity
        binding_identity = binding.binding_identity
        verified_payload = VerifiedPayload(
            request_identity=request_identity,
            binding_identity=binding_identity,
            artifact_id=binding.artifact_id,
            actual_sha256=actual_sha256,
            actual_byte_size=actual_size,
            schema_fingerprint=binding.schema_fingerprint,
            semantic_fingerprint=binding.semantic_fingerprint,
            context_identity=binding.context_identity,
            payload=payload,
        )
        receipt = PayloadResolutionReceipt(
            request_identity=request_identity,
            binding_identity=binding_identity,
            artifact_id=binding.artifact_id,
            actual_sha256=actual_sha256,
            actual_byte_size=actual_size,
            schema_fingerprint=binding.schema_fingerprint,
            semantic_fingerprint=binding.semantic_fingerprint,
            context_identity=binding.context_identity,
            resolver_contract_version=self.contract_version,
        )
        return PayloadResolutionResult(verified_payload=verified_payload, receipt=receipt)

    @staticmethod
    def _verify_request_binding(
        request: PayloadResolutionRequest,
        binding: CanonicalPayloadBinding,
    ) -> None:
        requested_owner = (
            request.owner_namespace,
            request.owner_id,
            request.owner_version,
        )
        bound_owner = (
            binding.owner_namespace,
            binding.owner_id,
            binding.owner_version,
        )
        if requested_owner != bound_owner:
            raise PayloadOwnerMismatch("canonical binding owner does not match request owner")
        if request.payload_role != binding.payload_role:
            raise PayloadRoleMismatch("canonical binding role does not match request role")
        if request.context_identity != binding.context_identity:
            raise PayloadContextMismatch(
                "canonical binding context does not match request context"
            )
        if binding.expected_byte_size > request.max_bytes:
            raise PayloadReadBoundExceeded(
                "bound payload byte size exceeds the caller's explicit read bound"
            )
        try:
            artifact_sha256 = sha256_from_artifact_id(binding.artifact_id)
        except InvalidArtifactIdentity as exc:
            raise PayloadArtifactIdMismatch("bound artifact ID is not canonical") from exc
        if artifact_sha256 != binding.expected_sha256:
            raise PayloadArtifactIdMismatch(
                "bound artifact ID and expected SHA-256 identify different bytes"
            )
