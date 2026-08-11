"""Read-only source-provider boundary for Round 3 evidence bundles."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from .projection import Round3ResearchEvidenceBundleV1


class Round3EvidenceProvider(Protocol):
    """Provider only; never a canonical storage or identity authority."""

    def get_bundle(self, session_view_id: str) -> Round3ResearchEvidenceBundleV1 | None: ...


class EmptyRound3EvidenceProvider:
    """Production fail-closed provider until official H/I/J discovery exists."""

    reason_code = "NO_CANONICAL_EVIDENCE_AVAILABLE"

    def get_bundle(self, session_view_id: str) -> None:
        if not session_view_id or session_view_id != session_view_id.strip():
            raise ValueError("session_view_id must be a non-empty exact string")
        return None


class InMemoryRound3EvidenceProvider:
    """Explicit test/development provider over already canonical bundles."""

    def __init__(self, bundles: Mapping[str, Round3ResearchEvidenceBundleV1]) -> None:
        observed = dict(bundles)
        for session_view_id, bundle in observed.items():
            if session_view_id != bundle.session_view_id:
                raise ValueError("provider key must exactly match bundle session binding")
        self._bundles = MappingProxyType(observed)

    def get_bundle(self, session_view_id: str) -> Round3ResearchEvidenceBundleV1 | None:
        return self._bundles.get(session_view_id)


__all__ = [
    "EmptyRound3EvidenceProvider",
    "InMemoryRound3EvidenceProvider",
    "Round3EvidenceProvider",
]
