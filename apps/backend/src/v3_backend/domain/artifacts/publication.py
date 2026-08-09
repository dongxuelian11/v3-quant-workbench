"""Frozen PUBLISH unit-of-work boundary owned by WS-B implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import ArtifactDescriptor, ArtifactReference


@dataclass(frozen=True, slots=True)
class ArtifactPublication:
    descriptor: ArtifactDescriptor
    active_references: tuple[ArtifactReference, ...]

    def __post_init__(self) -> None:
        if not self.active_references:
            raise ValueError("formal publication requires at least one active ArtifactReference")
        for reference in self.active_references:
            if reference.state != "ACTIVE":
                raise ValueError("publication accepts active references only")
            if reference.artifact_id != self.descriptor.artifact_id:
                raise ValueError("reference and descriptor artifact identities differ")


class PublishUnitOfWorkPort(Protocol):
    """One Catalog transaction; WS-C defines the port but owns no repository."""

    def publish(self, publication: ArtifactPublication) -> None:
        """Atomically persist an immutable descriptor and all active references."""


def publish_to_catalog(port: PublishUnitOfWorkPort, publication: ArtifactPublication) -> None:
    """Deliberately thin coordination boundary: no second registry is created."""

    port.publish(publication)
