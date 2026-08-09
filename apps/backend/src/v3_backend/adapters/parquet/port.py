"""Parquet adapter port and explicit unadmitted implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from v3_backend.domain.artifacts.exceptions import CapabilityUnavailable
from v3_backend.domain.artifacts.identity import sha256_from_artifact_id

from .manifest import LogicalSchema


@dataclass(frozen=True, slots=True)
class ParquetWriteRequest:
    logical_schema: LogicalSchema
    rows_artifact_id: str
    output_role: str = "PARQUET_PARTITION"

    def __post_init__(self) -> None:
        sha256_from_artifact_id(self.rows_artifact_id)
        if self.output_role != "PARQUET_PARTITION":
            raise ValueError("Parquet writer output role is closed")


class ParquetAdapterPort(Protocol):
    @property
    def capability_state(self) -> str: ...

    def inspect_schema(self, parquet_artifact_id: str) -> LogicalSchema: ...

    def write_partition(self, request: ParquetWriteRequest) -> str: ...


class UnavailableParquetAdapter:
    capability_state = "UNAVAILABLE"
    reason = "no Parquet library/environment profile has been admitted"

    def inspect_schema(self, parquet_artifact_id: str) -> LogicalSchema:
        raise CapabilityUnavailable("PARQUET", self.reason)

    def write_partition(self, request: ParquetWriteRequest) -> str:
        raise CapabilityUnavailable("PARQUET", self.reason)


def parquet_adapter_without_admission() -> ParquetAdapterPort:
    return UnavailableParquetAdapter()
