
from __future__ import annotations

import copy
import math
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar


class ContractValidationError(ValueError):
    """A wire value failed its frozen closed-schema contract."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.reason = message
        super().__init__(f"{path}: {message}")


def _validate_json_value(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(path, "JSON numbers must be finite")
        return
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ContractValidationError(path, "decimal must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(path, "object keys must be strings")
            _validate_json_value(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    raise ContractValidationError(path, f"unsupported JSON value type: {type(value).__name__}")


def _validate_rfc3339_utc(value: str, path: str) -> None:
    if not value.endswith("Z"):
        raise ContractValidationError(path, "timestamp must be RFC3339 UTC with Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(path, "invalid RFC3339 timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ContractValidationError(path, "timestamp must be UTC")


def validate_schema(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, Mapping):
            raise ContractValidationError(path, "expected object")
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        missing = [name for name in required if name not in value]
        if missing:
            raise ContractValidationError(path, "missing required fields: " + ", ".join(missing))
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ContractValidationError(path, "unknown fields: " + ", ".join(unknown))
        for name, item in value.items():
            if name in properties:
                validate_schema(item, properties[name], f"{path}.{name}")
            else:
                _validate_json_value(item, f"{path}.{name}")
        return

    if expected_type == "array":
        if not isinstance(value, (list, tuple)):
            raise ContractValidationError(path, "expected array")
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ContractValidationError(path, f"requires at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ContractValidationError(path, f"allows at most {schema['maxItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                validate_schema(item, schema["items"], f"{path}[{index}]")
        else:
            for index, item in enumerate(value):
                _validate_json_value(item, f"{path}[{index}]")
        return

    if expected_type == "string":
        if not isinstance(value, str):
            raise ContractValidationError(path, "expected string")
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ContractValidationError(path, f"minimum length is {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ContractValidationError(path, f"maximum length is {schema['maxLength']}")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ContractValidationError(path, "value does not match the frozen pattern")
        if "enum" in schema and value not in schema["enum"]:
            raise ContractValidationError(path, "value is not in the frozen enum")
        if "const" in schema and value != schema["const"]:
            raise ContractValidationError(path, f"value must equal {schema['const']!r}")
        if schema.get("format") == "uuid":
            try:
                parsed = uuid.UUID(value)
            except ValueError as exc:
                raise ContractValidationError(path, "invalid UUID") from exc
            if str(parsed) != value.lower():
                raise ContractValidationError(path, "UUID must use canonical hyphenated form")
        elif schema.get("format") == "date-time":
            _validate_rfc3339_utc(value, path)
        return

    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ContractValidationError(path, "expected integer")
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractValidationError(path, f"minimum is {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractValidationError(path, f"maximum is {schema['maximum']}")
        return

    if expected_type == "number":
        if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
            raise ContractValidationError(path, "expected number")
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractValidationError(path, "number must be finite")
        if isinstance(value, Decimal) and not value.is_finite():
            raise ContractValidationError(path, "number must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractValidationError(path, f"minimum is {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractValidationError(path, f"maximum is {schema['maximum']}")
        return

    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise ContractValidationError(path, "expected boolean")
        return

    if expected_type == "null":
        if value is not None:
            raise ContractValidationError(path, "expected null")
        return

    _validate_json_value(value, path)


class ClosedDto(Mapping[str, Any]):
    """Immutable-by-copy DTO with explicit schema and unknown-field rejection."""

    DTO_NAME: ClassVar[str] = "ClosedDto"
    SCHEMA: ClassVar[Mapping[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }
    OPERATION_ID: ClassVar[str] = ""

    def __init__(self, **values: Any) -> None:
        validate_schema(values, self.SCHEMA)
        self._values = copy.deepcopy(values)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ClosedDto":
        if not isinstance(values, Mapping):
            raise ContractValidationError("$", "DTO input must be an object")
        return cls(**dict(values))

    def to_wire(self) -> dict[str, Any]:
        return copy.deepcopy(self._values)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._values!r})"

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self._values == other._values
