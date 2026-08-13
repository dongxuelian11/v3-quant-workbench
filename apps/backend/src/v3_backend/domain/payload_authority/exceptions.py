"""Fail-closed failures for canonical payload resolution."""

from __future__ import annotations

from typing import ClassVar


class PayloadResolutionError(RuntimeError):
    """Base error carrying a stable machine-readable failure code."""

    code: ClassVar[str] = "PAYLOAD_RESOLUTION_FAILED"

    def to_wire(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class PayloadBindingUnavailable(PayloadResolutionError):
    code = "PAYLOAD_BINDING_UNAVAILABLE"


class PayloadContractVersionUnsupported(PayloadResolutionError):
    code = "PAYLOAD_CONTRACT_VERSION_UNSUPPORTED"

    def __init__(
        self,
        *,
        contract_kind: str,
        observed_version: str,
        supported_version: str,
    ) -> None:
        self.contract_kind = contract_kind
        self.observed_version = observed_version
        self.supported_version = supported_version
        super().__init__(
            f"unsupported {contract_kind} contract version: "
            f"observed {observed_version!r}, supported {supported_version!r}"
        )

    def to_wire(self) -> dict[str, str]:
        return {
            **super().to_wire(),
            "contract_kind": self.contract_kind,
            "observed_version": self.observed_version,
            "supported_version": self.supported_version,
        }


class PayloadOwnerMismatch(PayloadResolutionError):
    code = "PAYLOAD_OWNER_MISMATCH"


class PayloadRoleMismatch(PayloadResolutionError):
    code = "PAYLOAD_ROLE_MISMATCH"


class PayloadContextMismatch(PayloadResolutionError):
    code = "PAYLOAD_CONTEXT_MISMATCH"


class PayloadArtifactIdMismatch(PayloadResolutionError):
    code = "PAYLOAD_ARTIFACT_ID_MISMATCH"


class PayloadContentMismatch(PayloadResolutionError):
    code = "PAYLOAD_CONTENT_MISMATCH"


class PayloadSizeMismatch(PayloadResolutionError):
    code = "PAYLOAD_SIZE_MISMATCH"


class PayloadReadBoundExceeded(PayloadResolutionError):
    code = "PAYLOAD_READ_BOUND_EXCEEDED"


class PayloadArtifactUnavailable(PayloadResolutionError):
    code = "PAYLOAD_ARTIFACT_UNAVAILABLE"
