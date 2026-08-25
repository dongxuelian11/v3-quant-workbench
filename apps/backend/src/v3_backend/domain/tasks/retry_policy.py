from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCategory(StrEnum):
    INTERNAL_ERROR = "INTERNAL_ERROR"
    TRANSIENT_IO = "TRANSIENT_IO"
    WORKER_LOST = "WORKER_LOST"
    PROVIDER_THROTTLED = "PROVIDER_THROTTLED"
    RETRYABLE_ADAPTER = "RETRYABLE_ADAPTER"
    WORKER_OOM = "WORKER_OOM"
    TRUTH_PIT_FAILURE = "TRUTH_PIT_FAILURE"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    UNSAFE_ARTIFACT = "UNSAFE_ARTIFACT"
    LEDGER_MISMATCH = "LEDGER_MISMATCH"
    DETERMINISTIC_INFEASIBLE = "DETERMINISTIC_INFEASIBLE"


RETRYABLE = frozenset(
    {
        ErrorCategory.TRANSIENT_IO,
        ErrorCategory.WORKER_LOST,
        ErrorCategory.PROVIDER_THROTTLED,
        ErrorCategory.RETRYABLE_ADAPTER,
        ErrorCategory.WORKER_OOM,
    }
)


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    delay_seconds: int | None
    reason: str


@dataclass(frozen=True)
class RetryPolicy:
    base_delay_seconds: int = 2
    max_delay_seconds: int = 300
    max_attempts: int = 4

    def decide(self, category: ErrorCategory, prior_attempt_count: int) -> RetryDecision:
        if category not in RETRYABLE:
            return RetryDecision(False, None, f"{category} is deterministic/non-retryable")
        if prior_attempt_count >= self.max_attempts:
            return RetryDecision(False, None, "maximum Attempt count reached")
        delay = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** max(0, prior_attempt_count - 1)))
        return RetryDecision(True, delay, "retry admitted")
