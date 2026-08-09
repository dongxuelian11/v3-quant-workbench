"""Library-independent canonical Parquet dataset manifest identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from v3_backend.domain.artifacts.identity import (
    artifact_id_for_bytes,
    sha256_from_artifact_id,
    validate_sha256,
)


_LOGICAL_TYPES = frozenset(
    {
        "boolean",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "float32",
        "float64",
        "utf8",
        "binary",
        "date",
        "timestamp_utc",
        "decimal",
    }
)


def _canonical_json_bytes(value: Any) -> bytes:
    def validate(item: Any, path: str) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            raise ValueError(f"floating point is forbidden in canonical identity at {path}")
        if isinstance(item, list):
            for index, child in enumerate(item):
                validate(child, f"{path}[{index}]")
            return
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError(f"canonical object keys must be strings at {path}")
            for key, child in item.items():
                validate(child, f"{path}.{key}")
            return
        raise ValueError(f"unsupported canonical identity value at {path}: {type(item).__name__}")

    validate(value, "$")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _validate_time(value: str, name: str, *, aware: bool) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty ISO value")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if aware and (parsed.tzinfo is None or parsed.utcoffset() is None):
        raise ValueError(f"{name} must include a timezone")


@dataclass(frozen=True, slots=True)
class LogicalField:
    name: str
    logical_type: str
    nullable: bool
    decimal_scale: int | None = None

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("field name must not be empty")
        if self.logical_type not in _LOGICAL_TYPES:
            raise ValueError(f"unsupported logical type: {self.logical_type!r}")
        if not isinstance(self.nullable, bool):
            raise ValueError("nullable must be boolean")
        if self.logical_type == "decimal":
            if not isinstance(self.decimal_scale, int) or isinstance(self.decimal_scale, bool):
                raise ValueError("decimal fields require an integer scale")
        elif self.decimal_scale is not None:
            raise ValueError("decimal_scale is valid only for decimal fields")

    def canonical_value(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": self.name,
            "logical_type": self.logical_type,
            "nullable": self.nullable,
        }
        if self.decimal_scale is not None:
            value["decimal_scale"] = self.decimal_scale
        return value


@dataclass(frozen=True, slots=True)
class LogicalSchema:
    fields: tuple[LogicalField, ...]
    primary_key: tuple[str, ...]
    sort_keys: tuple[str, ...]
    calendar: str
    timezone: str
    null_policy: str

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError("logical schema must contain fields")
        names = tuple(field.name for field in self.fields)
        if len(set(names)) != len(names):
            raise ValueError("logical schema field names must be unique")
        if not self.primary_key or not set(self.primary_key) <= set(names):
            raise ValueError("primary key must reference declared fields")
        if len(set(self.primary_key)) != len(self.primary_key):
            raise ValueError("primary key cannot contain duplicates")
        if not set(self.sort_keys) <= set(names) or len(set(self.sort_keys)) != len(self.sort_keys):
            raise ValueError("sort keys must be unique declared fields")
        if not self.calendar or not self.timezone or not self.null_policy:
            raise ValueError("calendar, timezone, and null_policy are required")

    def canonical_value(self) -> dict[str, Any]:
        return {
            "fields": [field.canonical_value() for field in self.fields],
            "primary_key": list(self.primary_key),
            "sort_keys": list(self.sort_keys),
            "calendar": self.calendar,
            "timezone": self.timezone,
            "null_policy": self.null_policy,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.canonical_value())).hexdigest()


@dataclass(frozen=True, slots=True)
class ParquetPartition:
    logical_path: str
    artifact_id: str
    byte_size: int
    row_count: int
    schema_fingerprint: str
    partition_values: tuple[tuple[str, str | int | bool | None], ...]
    min_effective_time: str
    max_effective_time: str
    max_available_time: str
    statistics_artifact_id: str | None = None

    def __post_init__(self) -> None:
        path = PurePosixPath(self.logical_path)
        if (
            not self.logical_path
            or "\\" in self.logical_path
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or str(path) != self.logical_path
        ):
            raise ValueError("logical_path must be a canonical relative POSIX path")
        sha256_from_artifact_id(self.artifact_id)
        if self.statistics_artifact_id is not None:
            sha256_from_artifact_id(self.statistics_artifact_id)
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool) or self.byte_size < 0:
            raise ValueError("partition byte_size must be a non-negative integer")
        if not isinstance(self.row_count, int) or isinstance(self.row_count, bool) or self.row_count < 0:
            raise ValueError("partition row_count must be a non-negative integer")
        validate_sha256(self.schema_fingerprint)
        keys = tuple(key for key, _ in self.partition_values)
        if tuple(sorted(self.partition_values, key=lambda item: item[0])) != self.partition_values:
            raise ValueError("partition_values must be sorted by key")
        if len(set(keys)) != len(keys) or any(not key for key in keys):
            raise ValueError("partition value keys must be non-empty and unique")
        if any(
            value is not None and not isinstance(value, (str, int, bool))
            for _, value in self.partition_values
        ):
            raise ValueError("partition values must use canonical scalar types; floats are forbidden")
        _validate_time(self.min_effective_time, "min_effective_time", aware=False)
        _validate_time(self.max_effective_time, "max_effective_time", aware=False)
        _validate_time(self.max_available_time, "max_available_time", aware=True)
        if self.min_effective_time > self.max_effective_time:
            raise ValueError("minimum effective time cannot exceed maximum")

    def canonical_value(self, *, include_byte_identity: bool) -> dict[str, Any]:
        value: dict[str, Any] = {
            "logical_path": self.logical_path,
            "row_count": self.row_count,
            "schema_fingerprint": self.schema_fingerprint,
            "partition_values": {key: item for key, item in self.partition_values},
            "min_effective_time": self.min_effective_time,
            "max_effective_time": self.max_effective_time,
            "max_available_time": self.max_available_time,
        }
        if include_byte_identity:
            value["artifact_id"] = self.artifact_id
            value["byte_size"] = self.byte_size
            if self.statistics_artifact_id is not None:
                value["statistics_artifact_id"] = self.statistics_artifact_id
        return value


@dataclass(frozen=True, slots=True)
class ParquetDatasetManifest:
    logical_schema: LogicalSchema
    partitions: tuple[ParquetPartition, ...]
    producer_version: str
    environment_profile_id: str
    writer_settings: tuple[tuple[str, str | int | bool], ...]
    format_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not self.partitions:
            raise ValueError("dataset manifest must contain partitions")
        if not self.producer_version or not self.environment_profile_id:
            raise ValueError("producer version and environment profile are required")
        if self.format_version != "1.0.0":
            raise ValueError("unsupported manifest format version")
        if tuple(sorted(self.partitions, key=lambda item: item.logical_path)) != self.partitions:
            object.__setattr__(self, "partitions", tuple(sorted(self.partitions, key=lambda item: item.logical_path)))
        paths = tuple(partition.logical_path for partition in self.partitions)
        if len(set(paths)) != len(paths):
            raise ValueError("partition logical paths must be unique")
        if any(partition.schema_fingerprint != self.logical_schema.fingerprint for partition in self.partitions):
            raise ValueError("partition schema fingerprint differs from dataset logical schema")
        if tuple(sorted(self.writer_settings, key=lambda item: item[0])) != self.writer_settings:
            raise ValueError("writer_settings must be sorted by key")
        settings = dict(self.writer_settings)
        if len(settings) != len(self.writer_settings):
            raise ValueError("writer setting keys must be unique")
        if any(
            not isinstance(value, (str, int, bool)) or isinstance(value, float)
            for value in settings.values()
        ):
            raise ValueError("writer settings must use closed canonical scalar types")
        required_settings = {"compression", "row_group_rows", "utc_timestamps"}
        if not required_settings <= set(settings):
            raise ValueError("writer settings must pin compression, row-group policy, and UTC timestamps")
        if not isinstance(settings["compression"], str) or not settings["compression"]:
            raise ValueError("compression setting must be a non-empty identifier")
        if (
            not isinstance(settings["row_group_rows"], int)
            or isinstance(settings["row_group_rows"], bool)
            or settings["row_group_rows"] <= 0
        ):
            raise ValueError("row_group_rows must be a positive integer")
        if settings["utc_timestamps"] is not True:
            raise ValueError("Parquet writer timestamps must be pinned to UTC")

    @property
    def schema_fingerprint(self) -> str:
        return self.logical_schema.fingerprint

    def _semantic_value(self) -> dict[str, Any]:
        return {
            "logical_schema": self.logical_schema.canonical_value(),
            "partitions": [
                partition.canonical_value(include_byte_identity=False) for partition in self.partitions
            ],
        }

    @property
    def semantic_fingerprint(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self._semantic_value())).hexdigest()

    def canonical_value(self) -> dict[str, Any]:
        return {
            "schema_id": "urn:v3:parquet-dataset-manifest:1.0.0",
            "format_version": self.format_version,
            "logical_schema": self.logical_schema.canonical_value(),
            "schema_fingerprint": self.schema_fingerprint,
            "semantic_fingerprint": self.semantic_fingerprint,
            "producer_version": self.producer_version,
            "environment_profile_id": self.environment_profile_id,
            "writer_settings": {key: value for key, value in self.writer_settings},
            "partitions": [partition.canonical_value(include_byte_identity=True) for partition in self.partitions],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def artifact_id(self) -> str:
        return artifact_id_for_bytes(self.canonical_bytes)
