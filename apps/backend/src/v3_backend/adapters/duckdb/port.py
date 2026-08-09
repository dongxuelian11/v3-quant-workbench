"""Read-only typed DuckDB query boundary; raw/renderer SQL is not an API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from v3_backend.domain.artifacts.exceptions import CapabilityUnavailable
from v3_backend.domain.artifacts.identity import sha256_from_artifact_id


_COLUMN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_OPERATORS = frozenset({"EQ", "NE", "LT", "LE", "GT", "GE", "IN", "IS_NULL", "IS_NOT_NULL"})


@dataclass(frozen=True, slots=True)
class DatasetFilter:
    column: str
    operator: str
    values: tuple[str | int | bool, ...] = ()

    def __post_init__(self) -> None:
        if _COLUMN_RE.fullmatch(self.column) is None:
            raise ValueError("filter column must be a declared identifier")
        if self.operator not in _OPERATORS:
            raise ValueError("filter operator is not admitted")
        if self.operator in {"IS_NULL", "IS_NOT_NULL"} and self.values:
            raise ValueError("null filters do not accept values")
        if self.operator == "IN" and not self.values:
            raise ValueError("IN requires values")
        if self.operator not in {"IN", "IS_NULL", "IS_NOT_NULL"} and len(self.values) != 1:
            raise ValueError("comparison filters require one value")
        if len(self.values) > 10_000:
            raise ValueError("filter value count exceeds the admitted bound")
        if any(not isinstance(value, (str, int, bool)) for value in self.values):
            raise ValueError("filter values must be closed scalar types; floats are forbidden")


@dataclass(frozen=True, slots=True)
class DatasetQuery:
    manifest_artifact_id: str
    columns: tuple[str, ...]
    filters: tuple[DatasetFilter, ...] = ()
    limit: int = 1000

    def __post_init__(self) -> None:
        sha256_from_artifact_id(self.manifest_artifact_id)
        if not self.columns or any(_COLUMN_RE.fullmatch(column) is None for column in self.columns):
            raise ValueError("query columns must be declared identifiers")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("query columns must be unique")
        if len(self.columns) > 256:
            raise ValueError("query projection exceeds the admitted column bound")
        if len(self.filters) > 100 or any(not isinstance(item, DatasetFilter) for item in self.filters):
            raise ValueError("query filters must be bounded typed filters")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or not 1 <= self.limit <= 100_000:
            raise ValueError("query limit must be between 1 and 100000")


@dataclass(frozen=True, slots=True)
class DatasetQueryResult:
    result_artifact_id: str
    row_count: int


class DuckDbReadPort(Protocol):
    @property
    def capability_state(self) -> str: ...

    def query_dataset(self, request: DatasetQuery) -> DatasetQueryResult: ...


class UnavailableDuckDbAdapter:
    capability_state = "UNAVAILABLE"
    read_only = True
    reason = "no DuckDB library/environment profile has been admitted"

    def query_dataset(self, request: DatasetQuery) -> DatasetQueryResult:
        raise CapabilityUnavailable("DUCKDB", self.reason)


def duckdb_adapter_without_admission() -> DuckDbReadPort:
    return UnavailableDuckDbAdapter()
