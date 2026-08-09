
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class PageRequestV1:
    limit: int = 100
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or not 1 <= self.limit <= 200:
            raise ValueError("page limit must be between 1 and 200")
        if self.cursor is not None and (not isinstance(self.cursor, str) or not self.cursor):
            raise ValueError("cursor must be a non-empty opaque string")


@dataclass(frozen=True)
class EventPageRequestV1:
    after_sequence: int = 0
    limit: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.after_sequence, int) or isinstance(self.after_sequence, bool) or self.after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or not 1 <= self.limit <= 1000:
            raise ValueError("event replay limit must be between 1 and 1000")


@dataclass(frozen=True)
class PagedResponseV1(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None = None
    total_estimate: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            object.__setattr__(self, "items", tuple(self.items))
        if self.next_cursor is not None and (not isinstance(self.next_cursor, str) or not self.next_cursor):
            raise ValueError("next_cursor must be a non-empty opaque string")
        if self.total_estimate is not None and (
            not isinstance(self.total_estimate, int)
            or isinstance(self.total_estimate, bool)
            or self.total_estimate < 0
        ):
            raise ValueError("total_estimate must be a non-negative integer")

    def to_wire(self) -> dict[str, object]:
        result: dict[str, object] = {"items": list(self.items)}
        if self.next_cursor is not None:
            result["next_cursor"] = self.next_cursor
        if self.total_estimate is not None:
            result["total_estimate"] = self.total_estimate
        return result
