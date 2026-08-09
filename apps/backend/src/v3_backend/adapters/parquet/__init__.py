"""Canonical manifest identity and fail-closed Parquet port."""

from .manifest import LogicalField, LogicalSchema, ParquetDatasetManifest, ParquetPartition
from .port import (
    ParquetAdapterPort,
    ParquetWriteRequest,
    UnavailableParquetAdapter,
    parquet_adapter_without_admission,
)

__all__ = (
    "LogicalField",
    "LogicalSchema",
    "ParquetAdapterPort",
    "ParquetDatasetManifest",
    "ParquetPartition",
    "ParquetWriteRequest",
    "UnavailableParquetAdapter",
    "parquet_adapter_without_admission",
)
