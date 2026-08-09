"""Typed, read-only, fail-closed DuckDB adapter boundary."""

from .port import (
    DatasetFilter,
    DatasetQuery,
    DatasetQueryResult,
    DuckDbReadPort,
    UnavailableDuckDbAdapter,
    duckdb_adapter_without_admission,
)

__all__ = (
    "DatasetFilter",
    "DatasetQuery",
    "DatasetQueryResult",
    "DuckDbReadPort",
    "UnavailableDuckDbAdapter",
    "duckdb_adapter_without_admission",
)
