"""Delivery-only adapter for already durable project events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .framed_stdio import ProtocolViolation


class DurableEventReplayPort(Protocol):
    def replay(self, after_sequence: int, limit: int) -> Sequence[Mapping[str, Any]]: ...


class EventPublisher:
    """Validates sequence delivery without creating or persisting business events."""

    def __init__(self, source: DurableEventReplayPort | None = None) -> None:
        self._source = source
        self._highest_acked = 0
        self._highest_delivered = 0
        self._event_ids: set[str] = set()

    @property
    def highest_acked(self) -> int:
        return self._highest_acked

    def initialize_cursor(self, sequence: int) -> None:
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ProtocolViolation("event delivery cursor must be a non-negative integer")
        if self._highest_delivered and sequence < self._highest_delivered:
            raise ProtocolViolation("event delivery cursor cannot move backwards")
        self._highest_delivered = sequence

    def replay(self, after_sequence: int, limit: int) -> list[dict[str, Any]]:
        if not isinstance(after_sequence, int) or after_sequence < 0:
            raise ProtocolViolation("after_sequence must be a non-negative integer")
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ProtocolViolation("event replay limit must be between 1 and 1000")
        if self._source is None:
            self._highest_delivered = max(self._highest_delivered, after_sequence)
            return []
        result: list[dict[str, Any]] = []
        expected = after_sequence + 1
        for event in self._source.replay(after_sequence, limit):
            normalized = self._normalize(event)
            if normalized["project_sequence"] != expected:
                raise ProtocolViolation("durable event replay contains a sequence gap")
            expected += 1
            result.append(normalized)
        self._highest_delivered = max(
            self._highest_delivered,
            result[-1]["project_sequence"] if result else after_sequence,
        )
        return result

    def accept_live(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        normalized = self._normalize(event)
        event_id = normalized["event_id"]
        if event_id in self._event_ids:
            return None
        sequence = normalized["project_sequence"]
        if self._highest_delivered and sequence != self._highest_delivered + 1:
            raise ProtocolViolation("live event sequence gap requires replay")
        self._event_ids.add(event_id)
        self._highest_delivered = sequence
        return normalized

    def acknowledge(self, sequence: int) -> None:
        if not isinstance(sequence, int) or sequence < self._highest_acked:
            raise ProtocolViolation("event acknowledgement must be monotonic")
        if sequence > self._highest_delivered:
            raise ProtocolViolation("cannot acknowledge an undelivered event")
        self._highest_acked = sequence

    @staticmethod
    def _normalize(event: Mapping[str, Any]) -> dict[str, Any]:
        required = {"event_id", "project_id", "project_sequence", "event_type", "occurred_at", "body"}
        if set(event) != required:
            raise ProtocolViolation("event envelope fields do not match the closed wire shape")
        sequence = event["project_sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise ProtocolViolation("project_sequence must be a positive integer")
        for field in ("event_id", "project_id", "event_type", "occurred_at"):
            if not isinstance(event[field], str) or not event[field]:
                raise ProtocolViolation(f"event {field} must be a non-empty string")
        if not isinstance(event["body"], Mapping):
            raise ProtocolViolation("event body must be an object")
        return {"kind": "event", **dict(event), "body": dict(event["body"])}
