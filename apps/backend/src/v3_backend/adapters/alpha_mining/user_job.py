from __future__ import annotations

from typing import Protocol

from v3_backend.control_plane.resource_governor import ResourceGovernor
from v3_backend.domain.alpha_mining import (
    AlphaMiningContractError,
    AlphaMiningEngine,
    AlphaMiningJobSpec,
    AlphaMiningRunRecord,
    AlphaMiningUserAuthorization,
)


class AlphaMiningUserAuthorizationPort(Protocol):
    """Existing Control Plane persistence must resolve the exact USER request."""

    def assert_explicit_user_authorized(
        self,
        authorization: AlphaMiningUserAuthorization,
        job: AlphaMiningJobSpec,
    ) -> None: ...


class AlphaMiningUserJobService:
    """S-owned registration seam; authorization and resources stay Control Plane-owned."""

    def __init__(
        self,
        *,
        engine: AlphaMiningEngine,
        resources: ResourceGovernor,
        authorization_port: AlphaMiningUserAuthorizationPort,
    ) -> None:
        self.engine = engine
        self.resources = resources
        self.authorization_port = authorization_port

    def start_user_job(
        self,
        *,
        authorization: AlphaMiningUserAuthorization,
        job: AlphaMiningJobSpec,
    ) -> AlphaMiningRunRecord:
        if not isinstance(authorization, AlphaMiningUserAuthorization):
            raise AlphaMiningContractError(
                "ALPHA_MINING_USER_AUTHORIZATION_REQUIRED",
                "Agent drafts and unresolved receipts cannot start jobs",
            )
        if authorization.alpha_mining_job_spec_id != job.alpha_mining_job_spec_id:
            raise AlphaMiningContractError(
                "ALPHA_MINING_AUTHORIZATION_BINDING_MISMATCH",
                job.alpha_mining_job_spec_id,
            )
        self.authorization_port.assert_explicit_user_authorized(authorization, job)
        lease_id = (
            f"alpha-mining:{authorization.task_id}:{authorization.run_id}:"
            f"{authorization.attempt_id}"
        )
        grant = self.resources.admit(lease_id, job.operation_profile)
        observation = (
            "RESOURCE_GOVERNOR_ADMITTED:"
            f"class={grant.resource_class};cpu={grant.cpu_slots};"
            f"memory={grant.memory_hard_limit_bytes};scratch={grant.scratch_budget_bytes};"
            f"wallclock={grant.wall_clock_seconds};gpu={grant.gpu_device or 'NONE'}"
        )
        try:
            return self.engine.run(job, resource_observation=observation)
        finally:
            self.resources.release(lease_id)


__all__ = ["AlphaMiningUserAuthorizationPort", "AlphaMiningUserJobService"]
