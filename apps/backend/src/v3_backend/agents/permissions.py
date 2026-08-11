from __future__ import annotations

from .contracts import PermissionDecision, PermissionLevel


class PermissionDenied(RuntimeError):
    """The V3 Control Plane denied an Agent capability request."""


_ALLOWED_REASONS = {
    PermissionLevel.L0_READ: "V0_L0_READ_ALLOWED",
    PermissionLevel.L1_DRAFT: "V0_L1_DRAFT_ALLOWED",
}


def decide_permission(requested: object) -> PermissionDecision:
    if isinstance(requested, PermissionLevel):
        normalized = requested
        requested_text = requested.value
    elif isinstance(requested, str):
        requested_text = requested if requested else "<EMPTY>"
        try:
            normalized = PermissionLevel(requested)
        except ValueError:
            normalized = None
    else:
        requested_text = f"<{type(requested).__name__}>"
        normalized = None

    if normalized in _ALLOWED_REASONS:
        return PermissionDecision(
            requested=requested_text,
            normalized=normalized,
            allowed=True,
            reason=_ALLOWED_REASONS[normalized],
        )
    if normalized is PermissionLevel.L2_EXECUTE:
        reason = "V0_L2_EXECUTE_DENIED"
    elif normalized is PermissionLevel.L3_PUBLISH:
        reason = "V0_L3_PUBLISH_DENIED"
    else:
        reason = "UNKNOWN_PERMISSION_FAIL_CLOSED"
    return PermissionDecision(
        requested=requested_text,
        normalized=normalized,
        allowed=False,
        reason=reason,
    )


def require_permission(requested: object, required: PermissionLevel) -> PermissionDecision:
    decision = decide_permission(requested)
    if not decision.allowed:
        raise PermissionDenied(decision.reason)
    if required is PermissionLevel.L0_READ:
        return decision
    if required is PermissionLevel.L1_DRAFT and decision.normalized is PermissionLevel.L1_DRAFT:
        return decision
    raise PermissionDenied(f"{required.value}_REQUIRED")
