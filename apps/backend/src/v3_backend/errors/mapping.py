
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .codes import ErrorCode
from .exceptions import InvalidArgumentError, V3ContractError


@dataclass(frozen=True)
class ErrorEnvelopeV1:
    code: ErrorCode
    message: str
    retryable: bool = False
    details: Mapping[str, Any] | None = None
    correlation_id: str | None = None
    operation_id: str | None = None
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not isinstance(self.code, ErrorCode):
            object.__setattr__(self, "code", ErrorCode(self.code))
        if self.schema_version != "1.0.0":
            raise ValueError("error envelope schema_version must be 1.0.0")
        if not self.message:
            raise ValueError("error message must not be empty")
        object.__setattr__(self, "details", dict(self.details or {}))

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "ErrorEnvelopeV1":
        allowed = {"schema_version", "code", "message", "retryable", "details", "correlation_id", "operation_id"}
        required = {"schema_version", "code", "message", "retryable", "details"}
        unknown = sorted(set(value) - allowed)
        missing = sorted(required - set(value))
        if unknown:
            raise ValueError("unknown error fields: " + ", ".join(unknown))
        if missing:
            raise ValueError("missing error fields: " + ", ".join(missing))
        return cls(
            schema_version=value["schema_version"],
            code=ErrorCode(value["code"]),
            message=value["message"],
            retryable=value["retryable"],
            details=value["details"],
            correlation_id=value.get("correlation_id"),
            operation_id=value.get("operation_id"),
        )

    def to_wire(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details or {}),
        }
        if self.correlation_id is not None:
            result["correlation_id"] = self.correlation_id
        if self.operation_id is not None:
            result["operation_id"] = self.operation_id
        return result


def map_exception(exc: Exception) -> ErrorEnvelopeV1:
    if isinstance(exc, V3ContractError):
        return ErrorEnvelopeV1(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
            correlation_id=exc.correlation_id,
            operation_id=exc.operation_id,
        )
    if isinstance(exc, (ValueError, TypeError)):
        invalid = InvalidArgumentError(str(exc) or "invalid argument")
        return map_exception(invalid)
    return ErrorEnvelopeV1(
        code=ErrorCode.INTERNAL_ERROR,
        message="internal error",
        retryable=False,
        details={},
    )
