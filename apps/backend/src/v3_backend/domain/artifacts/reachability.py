"""Artifact reachability closure and confirmed garbage-collection semantics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Protocol

from .exceptions import GarbageCollectionSafetyError
from .identity import (
    artifact_id_for_bytes,
    sha256_from_artifact_id,
    storage_key_for_artifact_id,
)
from .lifecycle import exact_artifact_ids_hash
from .model import ArtifactDescriptor, ArtifactReference
from v3_backend.provenance.canonical_hash import canonical_json_bytes


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ReachabilityGraph:
    def __init__(
        self,
        roots: tuple[str, ...],
        references: tuple[ArtifactReference, ...],
        dependencies: tuple[tuple[str, str], ...] = (),
    ) -> None:
        if any(not root for root in roots):
            raise ValueError("reachability roots must not be empty")
        self.roots = frozenset(roots)
        edges: dict[str, set[str]] = {}
        for reference in references:
            if reference.state == "ACTIVE":
                edges.setdefault(reference.owner_id, set()).add(reference.artifact_id)
        for source, target in dependencies:
            if not source or not target:
                raise ValueError("dependency endpoints must not be empty")
            edges.setdefault(source, set()).add(target)
        self._edges = {source: frozenset(targets) for source, targets in edges.items()}

    def closure(self) -> frozenset[str]:
        visited: set[str] = set()
        pending = list(self.roots)
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            pending.extend(self._edges.get(node, ()))
        return frozenset(visited)

    def reachable_artifacts(self) -> frozenset[str]:
        return frozenset(node for node in self.closure() if node.startswith("art_sha256_"))

    def fingerprint(self) -> str:
        payload = {
            "roots": sorted(self.roots),
            "edges": [[source, target] for source in sorted(self._edges) for target in sorted(self._edges[source])],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class GarbageCollectionItem:
    artifact_id: str
    byte_size: int
    published_at: datetime
    storage_key: str

    def __post_init__(self) -> None:
        sha256_from_artifact_id(self.artifact_id)
        if (
            not isinstance(self.byte_size, int)
            or isinstance(self.byte_size, bool)
            or self.byte_size < 0
        ):
            raise ValueError("GC byte_size must be a non-negative integer")
        _iso(self.published_at)
        if self.storage_key != storage_key_for_artifact_id(self.artifact_id):
            raise ValueError("GC storage key must be a canonical relative key")


@dataclass(frozen=True, slots=True)
class GarbageCollectionPlan:
    created_at: datetime
    grace_period_seconds: int
    reachability_fingerprint: str
    items: tuple[GarbageCollectionItem, ...]
    open_promotion_intent_ids: tuple[str, ...] = ()
    phase: str = "QUARANTINE"

    def __post_init__(self) -> None:
        _iso(self.created_at)
        if (
            not isinstance(self.grace_period_seconds, int)
            or isinstance(self.grace_period_seconds, bool)
            or self.grace_period_seconds < 0
        ):
            raise ValueError("grace period must be a non-negative integer")
        if self.phase not in {"QUARANTINE", "PURGE"}:
            raise ValueError("GC plan phase must be QUARANTINE or PURGE")
        if tuple(sorted(self.items, key=lambda item: item.artifact_id)) != self.items:
            raise ValueError("GC items must be sorted by artifact ID")
        if len({item.artifact_id for item in self.items}) != len(self.items):
            raise ValueError("GC plan cannot contain duplicate artifacts")
        if tuple(sorted(self.open_promotion_intent_ids)) != self.open_promotion_intent_ids:
            raise ValueError("open promotion intent IDs must be sorted")
        if len(set(self.open_promotion_intent_ids)) != len(self.open_promotion_intent_ids):
            raise ValueError("open promotion intent IDs must be unique")

    @property
    def exact_byte_size(self) -> int:
        return sum(item.byte_size for item in self.items)

    @property
    def exact_artifact_ids(self) -> tuple[str, ...]:
        return tuple(item.artifact_id for item in self.items)

    @property
    def exact_artifact_ids_hash(self) -> str:
        return exact_artifact_ids_hash(self.exact_artifact_ids)

    @property
    def expires_at(self) -> datetime:
        # Plan expiry is deliberately short; execution persists and rechecks
        # this value rather than trusting a renderer-held preview.
        return self.created_at + timedelta(hours=1)

    def canonical_bytes(self) -> bytes:
        payload = {
            "schema_id": "urn:v3:artifact-gc-plan:1.0.0",
            "created_at": _iso(self.created_at),
            "phase": self.phase,
            "grace_period_seconds": self.grace_period_seconds,
            "reachability_fingerprint": self.reachability_fingerprint,
            "exact_artifact_ids_hash": self.exact_artifact_ids_hash,
            "exact_byte_size": self.exact_byte_size,
            "expires_at": _iso(self.expires_at),
            "open_promotion_intent_ids": list(self.open_promotion_intent_ids),
            "items": [
                {
                    "artifact_id": item.artifact_id,
                    "byte_size": item.byte_size,
                    "published_at": _iso(item.published_at),
                    "storage_key": item.storage_key,
                }
                for item in self.items
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> "GarbageCollectionPlan":
        """Rebuild only a byte-exact plan that was durably stored as JSON."""

        if not isinstance(payload, bytes):
            raise GarbageCollectionSafetyError("GC plan payload must be bytes")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GarbageCollectionSafetyError("GC plan payload is not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise GarbageCollectionSafetyError("GC plan payload must be a JSON object")
        try:
            canonical_payload = canonical_json_bytes(value)
        except (TypeError, ValueError) as exc:
            raise GarbageCollectionSafetyError("GC plan payload is not canonical JSON") from exc
        if canonical_payload != payload:
            raise GarbageCollectionSafetyError("GC plan payload is not canonical JSON")
        if set(value) != {
            "schema_id",
            "created_at",
            "phase",
            "grace_period_seconds",
            "reachability_fingerprint",
            "exact_artifact_ids_hash",
            "exact_byte_size",
            "expires_at",
            "open_promotion_intent_ids",
            "items",
        }:
            raise GarbageCollectionSafetyError("GC plan payload fields are not canonical")
        if value["schema_id"] != "urn:v3:artifact-gc-plan:1.0.0":
            raise GarbageCollectionSafetyError("GC plan schema is not canonical")
        if not isinstance(value["created_at"], str) or not isinstance(
            value["expires_at"], str
        ):
            raise GarbageCollectionSafetyError("GC plan timestamps are invalid")
        try:
            created_at = datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
            expires_at = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
            created_wire = _iso(created_at)
            expires_wire = _iso(expires_at)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GarbageCollectionSafetyError("GC plan timestamps are invalid") from exc
        if created_wire != value["created_at"] or expires_wire != value["expires_at"]:
            raise GarbageCollectionSafetyError("GC plan timestamps are not canonical")
        grace_period_seconds = value["grace_period_seconds"]
        if (
            not isinstance(grace_period_seconds, int)
            or isinstance(grace_period_seconds, bool)
            or grace_period_seconds < 0
        ):
            raise GarbageCollectionSafetyError("GC plan grace period is invalid")
        fingerprint = value["reachability_fingerprint"]
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or fingerprint != fingerprint.lower()
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise GarbageCollectionSafetyError("GC plan reachability fingerprint is invalid")
        phase = value["phase"]
        if phase not in {"QUARANTINE", "PURGE"}:
            raise GarbageCollectionSafetyError("GC plan phase is invalid")
        raw_open_ids = value["open_promotion_intent_ids"]
        if not isinstance(raw_open_ids, list) or any(
            not isinstance(item, str) or not item for item in raw_open_ids
        ):
            raise GarbageCollectionSafetyError("GC plan open promotion intents are invalid")
        open_ids = tuple(raw_open_ids)
        if tuple(sorted(open_ids)) != open_ids or len(set(open_ids)) != len(open_ids):
            raise GarbageCollectionSafetyError(
                "GC plan open promotion intents are not canonical"
            )
        raw_items = value["items"]
        if not isinstance(raw_items, list):
            raise GarbageCollectionSafetyError("GC plan items must be a JSON array")
        items: list[GarbageCollectionItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping) or set(raw_item) != {
                "artifact_id",
                "byte_size",
                "published_at",
                "storage_key",
            }:
                raise GarbageCollectionSafetyError("GC plan item fields are not canonical")
            published_at = raw_item["published_at"]
            if not isinstance(published_at, str):
                raise GarbageCollectionSafetyError("GC plan item timestamp is invalid")
            try:
                item_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                item = GarbageCollectionItem(
                    artifact_id=raw_item["artifact_id"],
                    byte_size=raw_item["byte_size"],
                    published_at=item_time,
                    storage_key=raw_item["storage_key"],
                )
            except Exception as exc:
                raise GarbageCollectionSafetyError("GC plan item is invalid") from exc
            if _iso(item_time) != published_at:
                raise GarbageCollectionSafetyError("GC plan item timestamp is not canonical")
            items.append(item)
        exact_ids_hash = value["exact_artifact_ids_hash"]
        if (
            not isinstance(exact_ids_hash, str)
            or len(exact_ids_hash) != 64
            or exact_ids_hash != exact_ids_hash.lower()
            or any(character not in "0123456789abcdef" for character in exact_ids_hash)
        ):
            raise GarbageCollectionSafetyError("GC plan exact ID hash is invalid")
        exact_byte_size = value["exact_byte_size"]
        if (
            not isinstance(exact_byte_size, int)
            or isinstance(exact_byte_size, bool)
            or exact_byte_size < 0
        ):
            raise GarbageCollectionSafetyError("GC plan exact byte size is invalid")
        try:
            plan = cls(
                created_at=created_at,
                grace_period_seconds=grace_period_seconds,
                reachability_fingerprint=fingerprint,
                items=tuple(items),
                open_promotion_intent_ids=open_ids,
                phase=phase,
            )
        except Exception as exc:
            raise GarbageCollectionSafetyError("GC plan fields are not canonical") from exc
        if exact_ids_hash != plan.exact_artifact_ids_hash:
            raise GarbageCollectionSafetyError("GC plan exact ID hash is not canonical")
        if exact_byte_size != plan.exact_byte_size:
            raise GarbageCollectionSafetyError("GC plan exact byte size is not canonical")
        if expires_at != plan.expires_at:
            raise GarbageCollectionSafetyError("GC plan expiry is not canonical")
        if plan.canonical_bytes() != payload:
            raise GarbageCollectionSafetyError("GC plan payload does not rebuild exactly")
        return plan

    @property
    def plan_artifact_id(self) -> str:
        return artifact_id_for_bytes(self.canonical_bytes())


def plan_garbage_collection(
    descriptors: tuple[ArtifactDescriptor, ...],
    graph: ReachabilityGraph,
    *,
    now: datetime,
    grace_period: timedelta,
    open_promotion_intent_ids: tuple[str, ...] = (),
    phase: str = "QUARANTINE",
) -> GarbageCollectionPlan:
    _iso(now)
    if grace_period < timedelta(0):
        raise ValueError("grace period cannot be negative")
    reachable = graph.reachable_artifacts()
    cutoff = now - grace_period
    candidates = tuple(
        sorted(
            (
                GarbageCollectionItem(
                    artifact_id=descriptor.artifact_id,
                    byte_size=descriptor.byte_size,
                    published_at=descriptor.published_at,
                    storage_key=descriptor.storage_key,
                )
                for descriptor in descriptors
                if descriptor.state == "PUBLISHED"
                and descriptor.artifact_id not in reachable
                and descriptor.published_at <= cutoff
            ),
            key=lambda item: item.artifact_id,
        )
    )
    return GarbageCollectionPlan(
        created_at=now,
        grace_period_seconds=int(grace_period.total_seconds()),
        reachability_fingerprint=graph.fingerprint(),
        items=candidates,
        open_promotion_intent_ids=tuple(sorted(open_promotion_intent_ids)),
        phase=phase,
    )


@dataclass(frozen=True, slots=True)
class GarbageCollectionConfirmation:
    plan_artifact_id: str
    artifact_ids: tuple[str, ...]
    confirmed_at: datetime
    confirmation_nonce: str = ""

    def __post_init__(self) -> None:
        sha256_from_artifact_id(self.plan_artifact_id)
        _iso(self.confirmed_at)
        if tuple(sorted(self.artifact_ids)) != self.artifact_ids:
            raise ValueError("confirmed artifact IDs must be sorted")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("confirmed Artifact IDs must be unique")
        for artifact_id in self.artifact_ids:
            sha256_from_artifact_id(artifact_id)


@dataclass(frozen=True, slots=True)
class ArtifactTombstone:
    artifact_id: str
    deleted_at: datetime
    plan_artifact_id: str


class ArtifactDeletionPort(Protocol):
    def delete_published_bytes(self, artifact_id: str) -> bool:
        """Delete exact bytes; return true only after confirmed absence."""


def execute_confirmed_garbage_collection(
    plan: GarbageCollectionPlan,
    confirmation: GarbageCollectionConfirmation,
    current_graph: ReachabilityGraph,
    deletion_port: ArtifactDeletionPort,
    *,
    deleted_at: datetime,
) -> tuple[ArtifactTombstone, ...]:
    _iso(deleted_at)
    planned_ids = tuple(item.artifact_id for item in plan.items)
    if confirmation.plan_artifact_id != plan.plan_artifact_id:
        raise GarbageCollectionSafetyError("confirmation does not identify this exact plan")
    if confirmation.artifact_ids != planned_ids:
        raise GarbageCollectionSafetyError("confirmation must cover the exact previewed artifact set")
    if confirmation.confirmed_at < plan.created_at:
        raise GarbageCollectionSafetyError("confirmation predates the plan")
    currently_reachable = current_graph.reachable_artifacts()
    newly_referenced = sorted(set(planned_ids) & set(currently_reachable))
    if newly_referenced:
        raise GarbageCollectionSafetyError("artifacts became reachable: " + ", ".join(newly_referenced))

    tombstones: list[ArtifactTombstone] = []
    for artifact_id in planned_ids:
        if deletion_port.delete_published_bytes(artifact_id):
            tombstones.append(ArtifactTombstone(artifact_id, deleted_at, plan.plan_artifact_id))
        else:
            raise GarbageCollectionSafetyError(f"deletion was not confirmed for {artifact_id}")
    return tuple(tombstones)
