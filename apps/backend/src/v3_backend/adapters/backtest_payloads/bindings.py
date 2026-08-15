"""Thin owner-specific binding resolver; P1 retains all shared byte authority."""

from __future__ import annotations

from typing import Protocol

from v3_backend.domain.backtest_runtime.formal import (
    CALENDAR_ROLE,
    CORPORATE_ACTION_ROLE,
    MARKET_ROLE,
    SNAPSHOT_ROLE,
    UNIVERSE_ROLE,
    WEIGHT_ROLE,
)
from v3_backend.domain.payload_authority import (
    CanonicalPayloadBinding,
    PayloadResolutionRequest,
)


_OWNER_POLICY = {
    SNAPSHOT_ROLE: "DATA_TRUTH",
    MARKET_ROLE: "DATA_TRUTH",
    CALENDAR_ROLE: "DATA_TRUTH",
    CORPORATE_ACTION_ROLE: "DATA_TRUTH",
    UNIVERSE_ROLE: "UNIVERSE",
    WEIGHT_ROLE: "RISK",
}


class BacktestPayloadOwnerBindingRepository(Protocol):
    """Read-only projection over Data Truth, Universe, and Risk owner records."""

    def resolve_backtest_payload_binding(
        self, request: PayloadResolutionRequest
    ) -> CanonicalPayloadBinding | None: ...


class BacktestCanonicalPayloadBindingResolver:
    """Allows only the closed A3 role-to-owner map before consulting an owner port."""

    def __init__(self, repository: BacktestPayloadOwnerBindingRepository) -> None:
        self._repository = repository

    def resolve(
        self, request: PayloadResolutionRequest
    ) -> CanonicalPayloadBinding | None:
        if not isinstance(request, PayloadResolutionRequest):
            raise TypeError("A3 binding resolution requires PayloadResolutionRequest")
        expected_owner = _OWNER_POLICY.get(request.payload_role)
        if expected_owner is None or request.owner_namespace != expected_owner:
            return None
        return self._repository.resolve_backtest_payload_binding(request)


__all__ = [
    "BacktestCanonicalPayloadBindingResolver",
    "BacktestPayloadOwnerBindingRepository",
]
