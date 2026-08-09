
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .codes import ErrorCode


class V3ContractError(Exception):
    code = ErrorCode.INTERNAL_ERROR
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        if not isinstance(message, str) or not message:
            raise ValueError("error message must not be empty")
        self.message = message
        self.details = dict(details or {})
        self.correlation_id = correlation_id
        self.operation_id = operation_id
        super().__init__(message)

class ArtifactNotPublishedError(V3ContractError):
    code = ErrorCode.ARTIFACT_NOT_PUBLISHED
    retryable = False

class CapabilityUnavailableError(V3ContractError):
    code = ErrorCode.CAPABILITY_UNAVAILABLE
    retryable = False

class ConflictError(V3ContractError):
    code = ErrorCode.CONFLICT
    retryable = False

class IdempotencyConflictError(V3ContractError):
    code = ErrorCode.IDEMPOTENCY_CONFLICT
    retryable = False

class InfeasibleError(V3ContractError):
    code = ErrorCode.INFEASIBLE
    retryable = False

class InternalErrorError(V3ContractError):
    code = ErrorCode.INTERNAL_ERROR
    retryable = True

class InvalidArgumentError(V3ContractError):
    code = ErrorCode.INVALID_ARGUMENT
    retryable = False

class LedgerUnreconciledError(V3ContractError):
    code = ErrorCode.LEDGER_UNRECONCILED
    retryable = False

class NotFoundError(V3ContractError):
    code = ErrorCode.NOT_FOUND
    retryable = False

class PitUnprovableError(V3ContractError):
    code = ErrorCode.PIT_UNPROVABLE
    retryable = False

class ResidualValidationFailedError(V3ContractError):
    code = ErrorCode.RESIDUAL_VALIDATION_FAILED
    retryable = False

class ResourceRejectedError(V3ContractError):
    code = ErrorCode.RESOURCE_REJECTED
    retryable = True

class SolverFailedError(V3ContractError):
    code = ErrorCode.SOLVER_FAILED
    retryable = True

class TruthPreconditionFailedError(V3ContractError):
    code = ErrorCode.TRUTH_PRECONDITION_FAILED
    retryable = False

class UnboundedError(V3ContractError):
    code = ErrorCode.UNBOUNDED
    retryable = False

class VersionMismatchError(V3ContractError):
    code = ErrorCode.VERSION_MISMATCH
    retryable = False
