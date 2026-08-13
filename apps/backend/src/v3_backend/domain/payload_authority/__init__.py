"""Shared canonical payload authority foundation."""

from .exceptions import (
    PayloadArtifactIdMismatch,
    PayloadArtifactUnavailable,
    PayloadBindingUnavailable,
    PayloadContentMismatch,
    PayloadContextMismatch,
    PayloadOwnerMismatch,
    PayloadReadBoundExceeded,
    PayloadResolutionError,
    PayloadRoleMismatch,
    PayloadSizeMismatch,
)
from .model import (
    BINDING_CONTRACT_VERSION,
    REQUEST_CONTRACT_VERSION,
    RESOLVER_CONTRACT_VERSION,
    CanonicalPayloadBinding,
    PayloadResolutionReceipt,
    PayloadResolutionRequest,
    PayloadResolutionResult,
    VerifiedPayload,
)
from .ports import CanonicalPayloadBindingResolver, VerifiedArtifactByteReader
from .service import CanonicalPayloadResolver

__all__ = (
    "BINDING_CONTRACT_VERSION",
    "REQUEST_CONTRACT_VERSION",
    "RESOLVER_CONTRACT_VERSION",
    "CanonicalPayloadBinding",
    "CanonicalPayloadBindingResolver",
    "CanonicalPayloadResolver",
    "PayloadArtifactIdMismatch",
    "PayloadArtifactUnavailable",
    "PayloadBindingUnavailable",
    "PayloadContentMismatch",
    "PayloadContextMismatch",
    "PayloadOwnerMismatch",
    "PayloadReadBoundExceeded",
    "PayloadResolutionError",
    "PayloadResolutionReceipt",
    "PayloadResolutionRequest",
    "PayloadResolutionResult",
    "PayloadRoleMismatch",
    "PayloadSizeMismatch",
    "VerifiedArtifactByteReader",
    "VerifiedPayload",
)
