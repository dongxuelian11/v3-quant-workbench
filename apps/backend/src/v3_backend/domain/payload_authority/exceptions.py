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
