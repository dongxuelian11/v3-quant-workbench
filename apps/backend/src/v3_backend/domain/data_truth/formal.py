"""Canonical Snapshot and Universe identities used by A1 formal payload services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol

from v3_backend.contracts.common.truth_admission import TruthAdmissionState
from v3_backend.domain.artifacts.identity import sha256_from_artifact_id, validate_sha256
from v3_backend.provenance.canonical_hash import canonical_sha256


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty without edge whitespace")


def _aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _time(value: datetime) -> str:
    _aware(value, "datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CanonicalSnapshotVersion:
    snapshot_id: str
    source_data_truth_id: str
    as_of: date
    knowledge_cutoff: datetime
    calendar_version_id: str
    payload_artifact_id: str
    payload_sha256: str
    payload_byte_size: int
    schema_fingerprint: str
    truth_admission: TruthAdmissionState

    def __post_init__(self) -> None:
        for field in ("snapshot_id", "source_data_truth_id", "calendar_version_id", "schema_fingerprint"):
            _text(getattr(self, field), field)
        _aware(self.knowledge_cutoff, "knowledge_cutoff")
        validate_sha256(self.payload_sha256)
        if sha256_from_artifact_id(self.payload_artifact_id) != self.payload_sha256:
            raise ValueError("Snapshot Artifact identity must match payload_sha256")
        if not isinstance(self.payload_byte_size, int) or isinstance(self.payload_byte_size, bool) or self.payload_byte_size < 0:
            raise ValueError("payload_byte_size must be a non-negative integer")
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("truth_admission must be typed")

    def to_context_wire(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "source_data_truth_id": self.source_data_truth_id,
            "as_of": self.as_of.isoformat(),
            "knowledge_cutoff": _time(self.knowledge_cutoff),
            "calendar_version_id": self.calendar_version_id,
            "snapshot_payload_artifact_id": self.payload_artifact_id,
            "snapshot_schema_fingerprint": self.schema_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class CanonicalUniverseVersion:
    universe_version_id: str
    snapshot_id: str
    as_of: date
    knowledge_cutoff: datetime
    membership_identity: str
    instrument_ids: tuple[str, ...]
    truth_admission: TruthAdmissionState

    def __post_init__(self) -> None:
        for field in ("universe_version_id", "snapshot_id", "membership_identity"):
            _text(getattr(self, field), field)
        _aware(self.knowledge_cutoff, "knowledge_cutoff")
        if not self.instrument_ids or tuple(sorted(self.instrument_ids)) != self.instrument_ids:
            raise ValueError("instrument_ids must be non-empty and canonically sorted")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("instrument_ids must be unique")
        for value in self.instrument_ids:
            _text(value, "instrument_id")
        expected = "unv_sha256_" + canonical_sha256(
            {
                "snapshot_id": self.snapshot_id,
                "as_of": self.as_of.isoformat(),
                "knowledge_cutoff": _time(self.knowledge_cutoff),
                "instrument_ids": list(self.instrument_ids),
            }
        )
        if self.membership_identity != expected:
            raise ValueError("membership_identity must bind exact historical membership and context")
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("truth_admission must be typed")

    @classmethod
    def create(
        cls,
        *,
        universe_version_id: str,
        snapshot_id: str,
        as_of: date,
        knowledge_cutoff: datetime,
        instrument_ids: tuple[str, ...],
        truth_admission: TruthAdmissionState,
    ) -> "CanonicalUniverseVersion":
        ordered = tuple(sorted(instrument_ids))
        membership_identity = "unv_sha256_" + canonical_sha256(
            {
                "snapshot_id": snapshot_id,
                "as_of": as_of.isoformat(),
                "knowledge_cutoff": _time(knowledge_cutoff),
                "instrument_ids": list(ordered),
            }
        )
        return cls(universe_version_id, snapshot_id, as_of, knowledge_cutoff, membership_identity, ordered, truth_admission)

    def to_context_wire(self) -> dict[str, object]:
        return {
            "universe_version_id": self.universe_version_id,
            "snapshot_id": self.snapshot_id,
            "as_of": self.as_of.isoformat(),
            "knowledge_cutoff": _time(self.knowledge_cutoff),
            "membership_identity": self.membership_identity,
            "instrument_ids": list(self.instrument_ids),
        }


class CanonicalSnapshotRepository(Protocol):
    def get_snapshot(self, snapshot_id: str) -> CanonicalSnapshotVersion | None: ...


class CanonicalUniverseRepository(Protocol):
    def get_universe(self, universe_version_id: str) -> CanonicalUniverseVersion | None: ...


def require_resolved_context(
    *,
    snapshots: CanonicalSnapshotRepository,
    universes: CanonicalUniverseRepository,
    snapshot_id: str,
    universe_version_id: str,
) -> tuple[CanonicalSnapshotVersion, CanonicalUniverseVersion]:
    snapshot = snapshots.get_snapshot(snapshot_id)
    universe = universes.get_universe(universe_version_id)
    if snapshot is None:
        raise ValueError("formal path requires a canonical Snapshot owner resolution")
    if universe is None:
        raise ValueError("formal path requires a canonical Universe owner resolution")
    if universe.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Universe is bound to a different Snapshot")
    if universe.as_of != snapshot.as_of or universe.knowledge_cutoff != snapshot.knowledge_cutoff:
        raise ValueError("Universe and Snapshot as-of/knowledge context differ")
    return snapshot, universe


__all__ = [
    "CanonicalSnapshotRepository",
    "CanonicalSnapshotVersion",
    "CanonicalUniverseRepository",
    "CanonicalUniverseVersion",
    "require_resolved_context",
]
