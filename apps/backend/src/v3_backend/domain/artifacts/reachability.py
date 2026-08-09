"""Artifact reachability closure and confirmed garbage-collection semantics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .exceptions import GarbageCollectionSafetyError
from .identity import artifact_id_for_bytes, sha256_from_artifact_id
from .model import ArtifactDescriptor, ArtifactReference


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
        if self.byte_size < 0:
            raise ValueError("GC byte_size cannot be negative")
        _iso(self.published_at)
        if self.storage_key.startswith(('/', '\\')) or ".." in self.storage_key.split("/"):
            raise ValueError("GC storage key must be a canonical relative key")


@dataclass(frozen=True, slots=True)
class GarbageCollectionPlan:
    created_at: datetime
    grace_period_seconds: int
    reachability_fingerprint: str
    items: tuple[GarbageCollectionItem, ...]

    def __post_init__(self) -> None:
        _iso(self.created_at)
        if self.grace_period_seconds < 0:
            raise ValueError("grace period cannot be negative")
        if tuple(sorted(self.items, key=lambda item: item.artifact_id)) != self.items:
            raise ValueError("GC items must be sorted by artifact ID")
        if len({item.artifact_id for item in self.items}) != len(self.items):
            raise ValueError("GC plan cannot contain duplicate artifacts")

    @property
    def exact_byte_size(self) -> int:
        return sum(item.byte_size for item in self.items)

    def canonical_bytes(self) -> bytes:
        payload = {
            "schema_id": "urn:v3:artifact-gc-plan:1.0.0",
            "created_at": _iso(self.created_at),
            "grace_period_seconds": self.grace_period_seconds,
            "reachability_fingerprint": self.reachability_fingerprint,
            "exact_byte_size": self.exact_byte_size,
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

    @property
    def plan_artifact_id(self) -> str:
        return artifact_id_for_bytes(self.canonical_bytes())


def plan_garbage_collection(
    descriptors: tuple[ArtifactDescriptor, ...],
    graph: ReachabilityGraph,
    *,
    now: datetime,
    grace_period: timedelta,
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
    )


@dataclass(frozen=True, slots=True)
class GarbageCollectionConfirmation:
    plan_artifact_id: str
    artifact_ids: tuple[str, ...]
    confirmed_at: datetime

    def __post_init__(self) -> None:
        sha256_from_artifact_id(self.plan_artifact_id)
        _iso(self.confirmed_at)
        if tuple(sorted(self.artifact_ids)) != self.artifact_ids:
            raise ValueError("confirmed artifact IDs must be sorted")


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
