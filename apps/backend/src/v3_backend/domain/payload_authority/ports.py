"""Narrow dependency-inverted ports for the shared resolver foundation."""

from __future__ import annotations

from typing import Protocol

from .model import CanonicalPayloadBinding, PayloadResolutionRequest


class CanonicalPayloadBindingResolver(Protocol):
    def resolve(
        self, request: PayloadResolutionRequest
    ) -> CanonicalPayloadBinding | None: ...


class VerifiedArtifactByteReader(Protocol):
    def read_bytes(self, artifact_id: str, *, max_bytes: int) -> bytes: ...
