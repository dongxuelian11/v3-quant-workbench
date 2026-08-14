from __future__ import annotations

from typing import NoReturn

from v3_backend.control_plane.resource_governor import ResourceGovernor
from v3_backend.domain.alpha_mining import (
    AlphaMiningContractError,
    AlphaMiningEngine,
    AlphaMiningJobSpec,
)


class AlphaMiningUserJobService:
    """Production seam that fails closed until shared user authority exists."""

    def __init__(
        self,
        *,
        engine: AlphaMiningEngine,
        resources: ResourceGovernor,
    ) -> None:
        self.engine = engine
        self.resources = resources

    def start_user_job(
        self,
        *,
        authorization: object,
        job: AlphaMiningJobSpec,
    ) -> NoReturn:
        # Neither the request object nor these injected runtime mechanisms are
        # user-action authority. Current main has no accepted shared authority
        # that can authorize this production transition, so stop before using
        # the JobSpec, ResourceGovernor, engine, or any downstream lineage path.
        del authorization, job
        raise AlphaMiningContractError(
            "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE",
            "shared canonical user-action authority is unavailable; "
            "production Alpha Mining user-start is NOT_AVAILABLE / NOT_RUN",
        )


__all__ = ["AlphaMiningUserJobService"]
