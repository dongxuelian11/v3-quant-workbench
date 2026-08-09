
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


class CanonicalizationError(ValueError):
    pass


def _utf16_sort_key(value: str) -> bytes:
    try:
        return value.encode("utf-16-be")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError("unpaired Unicode surrogate is forbidden") from exc


def _string(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError("unpaired Unicode surrogate is forbidden") from exc
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _float(value: float) -> str:
    if not math.isfinite(value):
        raise CanonicalizationError("non-finite JSON number is forbidden")
    if value == 0:
        return "0"
    text = repr(value).lower()
    absolute = abs(value)
    if 1e-6 <= absolute < 1e21:
        fixed = format(Decimal(text), "f")
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        return fixed
    if "e" not in text:
        return text[:-2] if text.endswith(".0") else text
    mantissa, exponent = text.split("e", 1)
    if mantissa.endswith(".0"):
        mantissa = mantissa[:-2]
    exponent_value = int(exponent)
    sign = "+" if exponent_value >= 0 else "-"
    return f"{mantissa}e{sign}{abs(exponent_value)}"


def _normalize_extended(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_wire") and callable(value.to_wire):
        return value.to_wire()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise CanonicalizationError("naive datetime is forbidden")
        utc_value = value.astimezone(timezone.utc)
        text = utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return text.replace(".000000Z", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _encode(value: Any) -> str:
    value = _normalize_extended(value)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, Decimal):
        raise CanonicalizationError("Decimal must cross the wire as a decimal string")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalizationError("JSON object keys must be strings")
        parts = []
        for key in sorted(value, key=_utf16_sort_key):
            parts.append(f"{_string(key)}:{_encode(value[key])}")
        return "{" + ",".join(parts) + "}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    raise CanonicalizationError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return deterministic RFC 8785-style canonical JSON for the frozen wire subset."""

    return _encode(value)


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_artifact_id(value: Any) -> str:
    return "art_sha256_" + canonical_sha256(value)
