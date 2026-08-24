"""Closed-schema, bounded and deterministic local EOD normalization."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, BinaryIO

from v3_backend.provenance.canonical_hash import canonical_json_bytes


CSV_MEDIA_TYPE = "text/csv"
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
NORMALIZED_SCHEMA_VERSION = "v3.local-a-share-eod/1.0.0"
_REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "amount")
_OPTIONAL_COLUMNS = (
    "available_time",
    "is_suspended",
    "is_st",
    "tradable",
    "price_limit_up",
    "price_limit_down",
    "no_price_limit_session",
    "corporate_action_ref",
)
_ALLOWED_COLUMNS = frozenset((*_REQUIRED_COLUMNS, *_OPTIONAL_COLUMNS))


class LocalDataImportError(ValueError):
    """The local source cannot be admitted without guessing or exceeding bounds."""


@dataclass(frozen=True, slots=True)
class LocalDataImportLimits:
    max_bytes: int = 256 * 1024 * 1024
    max_rows: int = 2_000_000
    max_instruments: int = 2_000
    parquet_batch_rows: int = 65_536
    max_parquet_row_groups: int = 16_384
    max_parquet_columns: int = len(_ALLOWED_COLUMNS)
    max_partition_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_bytes",
            "max_rows",
            "max_instruments",
            "parquet_batch_rows",
            "max_parquet_row_groups",
            "max_parquet_columns",
            "max_partition_bytes",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class LocalDataImportIntentV1:
    media_type: str
    volume_unit: str
    amount_unit: str
    timezone: str
    adjustment: str

    def __post_init__(self) -> None:
        if self.media_type not in {CSV_MEDIA_TYPE, PARQUET_MEDIA_TYPE}:
            raise LocalDataImportError("local media_type is not admitted")
        if self.volume_unit not in {"SHARES", "HANDS"}:
            raise LocalDataImportError("volume_unit must be SHARES or HANDS")
        if self.amount_unit != "CNY":
            raise LocalDataImportError("amount_unit must be CNY")
        if self.timezone != "Asia/Shanghai":
            raise LocalDataImportError("timezone must be Asia/Shanghai")
        if self.adjustment != "UNADJUSTED":
            raise LocalDataImportError("adjustment must be UNADJUSTED")


@dataclass(frozen=True, slots=True)
class LocalEodRow:
    instrument_id: str
    symbol: str
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume_shares: int | None
    amount_cny: Decimal | None
    available_time: datetime | None
    is_suspended: bool | None
    is_st: bool | None
    tradable: bool | None
    price_limit_up: Decimal | None
    price_limit_down: Decimal | None
    no_price_limit_session: bool | None
    corporate_action_ref: str | None

    def canonical_value(self) -> dict[str, object]:
        optional = {
            "available_time": self.available_time,
            "is_suspended": self.is_suspended,
            "is_st": self.is_st,
            "tradable": self.tradable,
            "price_limit_up": _decimal_wire(self.price_limit_up),
            "price_limit_down": _decimal_wire(self.price_limit_down),
            "no_price_limit_session": self.no_price_limit_session,
            "corporate_action_ref": self.corporate_action_ref,
        }
        missing = tuple(key for key, value in optional.items() if value is None)
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "session_date": self.session_date,
            "open": _decimal_wire(self.open),
            "high": _decimal_wire(self.high),
            "low": _decimal_wire(self.low),
            "close": _decimal_wire(self.close),
            "volume_shares": self.volume_shares,
            "amount_cny": _decimal_wire(self.amount_cny),
            **optional,
            "missing_reason": {name: "SOURCE_COLUMN_ABSENT_OR_NULL" for name in missing},
        }


@dataclass(frozen=True, slots=True)
class LocalDataNormalizationResult:
    rows: tuple[LocalEodRow, ...]
    partitions: tuple["LocalDataCanonicalPartition", ...]
    normalized_payload: bytes
    normalized_payload_hash: str
    snapshot_semantic_id: str
    raw_content_hash: str
    raw_byte_size: int
    source_media_type: str
    source_volume_unit: str

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def instrument_count(self) -> int:
        return len({row.instrument_id for row in self.rows})


@dataclass(frozen=True, slots=True)
class LocalDataCanonicalPartition:
    partition_key: str
    payload: bytes
    content_hash: str
    row_count: int
    min_session_date: date
    max_session_date: date


class _BoundedHashingRaw(io.RawIOBase):
    def __init__(self, source: BinaryIO, maximum: int) -> None:
        self._source = source
        self._maximum = maximum
        self._hash = hashlib.sha256()
        self.byte_size = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:
        chunk = self._source.read(len(buffer))
        if not isinstance(chunk, bytes):
            raise LocalDataImportError("local source must yield bytes")
        if not chunk:
            return 0
        self.byte_size += len(chunk)
        if self.byte_size > self._maximum:
            raise LocalDataImportError("local source exceeds max_bytes")
        self._hash.update(chunk)
        buffer[: len(chunk)] = chunk
        return len(chunk)

    @property
    def content_hash(self) -> str:
        return self._hash.hexdigest()


def _decimal_wire(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _required_decimal(value: object, field: str) -> Decimal:
    parsed = _optional_decimal(value, field)
    if parsed is None or parsed <= 0:
        raise LocalDataImportError(f"{field} must be a positive finite decimal")
    return parsed


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise LocalDataImportError(f"{field} must be a finite decimal")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise LocalDataImportError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise LocalDataImportError(f"{field} must be a finite decimal")
    return parsed


def _volume_shares(value: object, unit: str) -> int | None:
    parsed = _optional_decimal(value, "volume")
    if parsed is None:
        return None
    if parsed < 0 or parsed != parsed.to_integral_value():
        raise LocalDataImportError("volume must be a non-negative integer")
    multiplier = 100 if unit == "HANDS" else 1
    return int(parsed) * multiplier


def _optional_bool(value: object, field: str) -> bool | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    normalized = value.strip().lower() if isinstance(value, str) else value
    if normalized is True or normalized == 1 or normalized in {"true", "1"}:
        return True
    if normalized is False or normalized == 0 or normalized in {"false", "0"}:
        return False
    raise LocalDataImportError(f"{field} must be true, false, 1, 0, or null")


def _optional_time(value: object) -> datetime | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip()
        candidate = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise LocalDataImportError("available_time must be ISO-8601") from exc
    else:
        raise LocalDataImportError("available_time must be ISO-8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LocalDataImportError("available_time must include a timezone")
    return parsed


def _instrument_id(symbol: str) -> str:
    if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
        raise LocalDataImportError("symbol must be exactly six ASCII digits")
    if symbol.startswith(("4", "8", "92")):
        exchange = "bse"
    elif symbol.startswith(("5", "6", "9")):
        exchange = "sse"
    elif symbol.startswith(("0", "1", "2", "3")):
        exchange = "szse"
    else:
        raise LocalDataImportError("symbol prefix is not an admitted A-share exchange")
    return f"ins_cn_{exchange}_{symbol}"


def _session_date(value: object) -> date:
    if isinstance(value, datetime):
        raise LocalDataImportError("date must not contain a time")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise LocalDataImportError("date must be ISO YYYY-MM-DD")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise LocalDataImportError("date must be ISO YYYY-MM-DD") from exc


def _row(value: Mapping[str, object], intent: LocalDataImportIntentV1) -> LocalEodRow:
    symbol_value = value.get("symbol")
    if not isinstance(symbol_value, str):
        raise LocalDataImportError("symbol must be text")
    symbol = symbol_value.strip()
    open_price = _required_decimal(value.get("open"), "open")
    high = _required_decimal(value.get("high"), "high")
    low = _required_decimal(value.get("low"), "low")
    close = _required_decimal(value.get("close"), "close")
    if low > high or low > min(open_price, close) or high < max(open_price, close):
        raise LocalDataImportError("OHLC envelope is inconsistent")
    amount = _optional_decimal(value.get("amount"), "amount")
    if amount is not None and amount < 0:
        raise LocalDataImportError("amount must be non-negative")
    action = value.get("corporate_action_ref")
    if action is not None and not isinstance(action, str):
        raise LocalDataImportError("corporate_action_ref must be text or null")
    action = action.strip() if isinstance(action, str) else None
    if action and re.fullmatch(r"cax_sha256_[0-9a-f]{64}", action) is None:
        raise LocalDataImportError(
            "corporate_action_ref must be a canonical cax_sha256 ref or null"
        )
    return LocalEodRow(
        instrument_id=_instrument_id(symbol),
        symbol=symbol,
        session_date=_session_date(value.get("date")),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume_shares=_volume_shares(value.get("volume"), intent.volume_unit),
        amount_cny=amount,
        available_time=_optional_time(value.get("available_time")),
        is_suspended=_optional_bool(value.get("is_suspended"), "is_suspended"),
        is_st=_optional_bool(value.get("is_st"), "is_st"),
        tradable=_optional_bool(value.get("tradable"), "tradable"),
        price_limit_up=_optional_decimal(value.get("price_limit_up"), "price_limit_up"),
        price_limit_down=_optional_decimal(value.get("price_limit_down"), "price_limit_down"),
        no_price_limit_session=_optional_bool(
            value.get("no_price_limit_session"), "no_price_limit_session"
        ),
        corporate_action_ref=action or None,
    )


def _validate_columns(columns: tuple[str, ...]) -> None:
    if len(set(columns)) != len(columns):
        raise LocalDataImportError("closed header contains duplicate columns")
    if not set(_REQUIRED_COLUMNS) <= set(columns) or not set(columns) <= _ALLOWED_COLUMNS:
        raise LocalDataImportError("closed header differs from the admitted local EOD schema")


def _result(
    raw_rows: Iterator[Mapping[str, object]],
    *,
    intent: LocalDataImportIntentV1,
    limits: LocalDataImportLimits,
    raw_hash: str,
    raw_size: int,
) -> LocalDataNormalizationResult:
    observed: list[LocalEodRow] = []
    keys: set[tuple[str, date]] = set()
    instruments: set[str] = set()
    for raw in raw_rows:
        if len(observed) >= limits.max_rows:
            raise LocalDataImportError("local source exceeds max_rows")
        item = _row(raw, intent)
        key = (item.instrument_id, item.session_date)
        if key in keys:
            raise LocalDataImportError("duplicate symbol + session_date key")
        keys.add(key)
        instruments.add(item.instrument_id)
        if len(instruments) > limits.max_instruments:
            raise LocalDataImportError("local source exceeds max_instruments")
        observed.append(item)
    if not observed:
        raise LocalDataImportError("local source contains no rows")
    rows = tuple(sorted(observed, key=lambda item: (item.session_date, item.instrument_id)))
    partitions = _canonical_partitions(rows, max_bytes=limits.max_partition_bytes)
    action_refs = tuple(
        sorted(
            {
                row.corporate_action_ref
                for row in rows
                if row.corporate_action_ref is not None
            }
        )
    )
    manifest: dict[str, object] = {
        "schema_version": (
            "v3.local-a-share-eod-manifest/1.2.0"
            if action_refs
            else "v3.local-a-share-eod-manifest/1.1.0"
        ),
        "data_schema_version": NORMALIZED_SCHEMA_VERSION,
        "adjustment": "UNADJUSTED",
        "amount_unit": "CNY",
        "timezone": "Asia/Shanghai",
        "volume_unit": "SHARES",
        "row_count": len(rows),
        "instrument_count": len(instruments),
        "corporate_action_ref_count": sum(
            row.corporate_action_ref is not None for row in rows
        ),
        "partitions": tuple(
            {
                "partition_key": partition.partition_key,
                "content_hash": partition.content_hash,
                "row_count": partition.row_count,
                "min_session_date": partition.min_session_date,
                "max_session_date": partition.max_session_date,
            }
            for partition in partitions
        ),
    }
    if action_refs:
        manifest["corporate_action_refs"] = action_refs
    payload = canonical_json_bytes(
        manifest
    )
    payload_hash = hashlib.sha256(payload).hexdigest()
    return LocalDataNormalizationResult(
        rows=rows,
        partitions=partitions,
        normalized_payload=payload,
        normalized_payload_hash=payload_hash,
        snapshot_semantic_id="snp_sha256_" + payload_hash,
        raw_content_hash=raw_hash,
        raw_byte_size=raw_size,
        source_media_type=intent.media_type,
        source_volume_unit=intent.volume_unit,
    )


def _canonical_partition_payload(
    partition_key: str,
    rows: tuple[dict[str, object], ...],
) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "v3.local-a-share-eod-partition/1.0.0",
            "data_schema_version": NORMALIZED_SCHEMA_VERSION,
            "partition_key": partition_key,
            "adjustment": "UNADJUSTED",
            "amount_unit": "CNY",
            "timezone": "Asia/Shanghai",
            "volume_unit": "SHARES",
            "rows": rows,
        }
    )


def _canonical_partitions(
    rows: tuple[LocalEodRow, ...],
    *,
    max_bytes: int,
) -> tuple[LocalDataCanonicalPartition, ...]:
    partitions: list[LocalDataCanonicalPartition] = []
    pending_rows: list[LocalEodRow] = []
    pending_values: list[dict[str, object]] = []
    pending_value_bytes = 0

    def finish() -> None:
        nonlocal pending_rows, pending_values, pending_value_bytes
        partition_key = f"{len(partitions):08d}"
        payload = _canonical_partition_payload(partition_key, tuple(pending_values))
        if len(payload) > max_bytes:
            raise LocalDataImportError("canonical row exceeds max_partition_bytes")
        partitions.append(
            LocalDataCanonicalPartition(
                partition_key=partition_key,
                payload=payload,
                content_hash=hashlib.sha256(payload).hexdigest(),
                row_count=len(pending_rows),
                min_session_date=pending_rows[0].session_date,
                max_session_date=pending_rows[-1].session_date,
            )
        )
        pending_rows = []
        pending_values = []
        pending_value_bytes = 0

    empty_size = len(_canonical_partition_payload("00000000", ()))
    for row in rows:
        value = row.canonical_value()
        value_size = len(canonical_json_bytes(value))
        projected_size = empty_size + pending_value_bytes + value_size + len(pending_values)
        if pending_values and projected_size > max_bytes:
            finish()
            projected_size = empty_size + value_size
        if projected_size > max_bytes:
            raise LocalDataImportError("canonical row exceeds max_partition_bytes")
        pending_rows.append(row)
        pending_values.append(value)
        pending_value_bytes += value_size
    if pending_values:
        finish()
    return tuple(partitions)


def import_csv_stream(
    source: BinaryIO,
    *,
    intent: LocalDataImportIntentV1,
    limits: LocalDataImportLimits = LocalDataImportLimits(),
) -> LocalDataNormalizationResult:
    if intent.media_type != CSV_MEDIA_TYPE:
        raise LocalDataImportError("CSV importer requires text/csv intent")
    hashing = _BoundedHashingRaw(source, limits.max_bytes)
    buffered = io.BufferedReader(hashing, buffer_size=64 * 1024)
    text = io.TextIOWrapper(buffered, encoding="utf-8-sig", errors="strict", newline="")
    try:
        reader = csv.DictReader(text, dialect="excel", strict=True)
        if reader.fieldnames is None or any(name is None for name in reader.fieldnames):
            raise LocalDataImportError("closed header is required")
        columns = tuple(reader.fieldnames)
        _validate_columns(columns)

        def values() -> Iterator[Mapping[str, object]]:
            try:
                for item in reader:
                    if None in item:
                        raise LocalDataImportError("CSV row has more values than the closed header")
                    yield item
            except UnicodeDecodeError as exc:
                raise LocalDataImportError("CSV must be valid UTF-8 or UTF-8-SIG") from exc
            except csv.Error as exc:
                raise LocalDataImportError("CSV syntax is invalid") from exc

        result = _result(
            values(),
            intent=intent,
            limits=limits,
            raw_hash="PENDING",
            raw_size=0,
        )
    except UnicodeDecodeError as exc:
        raise LocalDataImportError("CSV must be valid UTF-8 or UTF-8-SIG") from exc
    return LocalDataNormalizationResult(
        rows=result.rows,
        partitions=result.partitions,
        normalized_payload=result.normalized_payload,
        normalized_payload_hash=result.normalized_payload_hash,
        snapshot_semantic_id=result.snapshot_semantic_id,
        raw_content_hash=hashing.content_hash,
        raw_byte_size=hashing.byte_size,
        source_media_type=result.source_media_type,
        source_volume_unit=result.source_volume_unit,
    )


def _hash_seekable(source: BinaryIO, maximum: int) -> tuple[str, int]:
    if not source.seekable():
        raise LocalDataImportError("Parquet requires a bounded staged seekable stream")
    source.seek(0)
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = source.read(1024 * 1024)
        if not isinstance(chunk, bytes):
            raise LocalDataImportError("local source must yield bytes")
        if not chunk:
            break
        size += len(chunk)
        if size > maximum:
            raise LocalDataImportError("local source exceeds max_bytes")
        digest.update(chunk)
    source.seek(0)
    return digest.hexdigest(), size


def import_parquet_stream(
    source: BinaryIO,
    *,
    intent: LocalDataImportIntentV1,
    limits: LocalDataImportLimits = LocalDataImportLimits(),
) -> LocalDataNormalizationResult:
    if intent.media_type != PARQUET_MEDIA_TYPE:
        raise LocalDataImportError("Parquet importer requires application/vnd.apache.parquet intent")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise LocalDataImportError("admitted PyArrow runtime is unavailable") from exc
    raw_hash, raw_size = _hash_seekable(source, limits.max_bytes)
    try:
        parquet = pq.ParquetFile(source)
    except Exception as exc:
        raise LocalDataImportError("Parquet metadata is invalid") from exc
    metadata = parquet.metadata
    if metadata.num_rows > limits.max_rows:
        raise LocalDataImportError("local source exceeds max_rows")
    if metadata.num_row_groups > limits.max_parquet_row_groups:
        raise LocalDataImportError("Parquet exceeds max row groups")
    if metadata.num_columns > limits.max_parquet_columns:
        raise LocalDataImportError("Parquet exceeds max columns")
    schema = parquet.schema_arrow
    for field in schema:
        if (
            pa.types.is_nested(field.type)
            or isinstance(field.type, pa.ExtensionType)
            or pa.types.is_dictionary(field.type)
            or pa.types.is_binary(field.type)
            or pa.types.is_large_binary(field.type)
        ):
            raise LocalDataImportError("Parquet accepts flat primitive columns only")
    columns = tuple(field.name for field in schema)
    _validate_columns(columns)

    def values() -> Iterator[Mapping[str, object]]:
        try:
            for batch in parquet.iter_batches(batch_size=limits.parquet_batch_rows):
                projected = batch.to_pydict()
                for index in range(batch.num_rows):
                    yield {name: projected[name][index] for name in columns}
        except LocalDataImportError:
            raise
        except Exception as exc:
            raise LocalDataImportError("Parquet batch decoding failed") from exc

    return _result(
        values(),
        intent=intent,
        limits=limits,
        raw_hash=raw_hash,
        raw_size=raw_size,
    )
