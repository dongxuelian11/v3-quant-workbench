"""Shared, versioned research-package transport bounds.

The JSON contract is the single source for Python and Desktop.  The package
limit is derived from the one MiB frame cap after reserving bounded JSON
envelope space and a fixed safety margin for headers/metadata.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _contract_path() -> Path:
    configured = os.environ.get("V3_RESEARCH_PACKAGE_TRANSPORT_PATH")
    if configured:
        return Path(configured).resolve()
    # apps/backend/src/v3_backend -> repository root
    return Path(__file__).resolve().parents[4] / "packages" / "contracts" / "research_package_transport_v1.json"


def _load() -> dict[str, int | str]:
    path = _contract_path()
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"research package transport contract is unavailable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("research package transport contract must be an object")
    expected = {
        "schema_version",
        "max_frame_bytes",
        "max_package_file_bytes",
        "max_package_file_count",
        "max_package_manifest_bytes",
        "envelope_overhead_bytes",
        "safety_margin_bytes",
        "max_package_total_bytes",
        "max_package_file_base64_chars",
    }
    if set(value) != expected or value.get("schema_version") != "v3.research-package-transport/1.0.0":
        raise RuntimeError("research package transport contract shape/version is invalid")
    numbers = {key: value[key] for key in expected if key != "schema_version"}
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in numbers.values()):
        raise RuntimeError("research package transport contract bounds must be positive integers")
    derived_total = (
        (int(value["max_frame_bytes"]) - int(value["envelope_overhead_bytes"]) - int(value["safety_margin_bytes"]))
        * 3
    ) // 4
    derived_base64 = ((int(value["max_package_file_bytes"]) + 2) // 3) * 4
    if derived_total != int(value["max_package_total_bytes"]):
        raise RuntimeError("research package total limit is not derived from the frame contract")
    if derived_base64 != int(value["max_package_file_base64_chars"]):
        raise RuntimeError("research package base64 limit is not derived from the file limit")
    if int(value["max_package_total_bytes"]) >= int(value["max_frame_bytes"]):
        raise RuntimeError("research package total limit must be below the frame limit")
    return {key: value[key] for key in value}


TRANSPORT_CONTRACT = _load()
TRANSPORT_CONTRACT_SCHEMA_VERSION = str(TRANSPORT_CONTRACT["schema_version"])
MAX_FRAME_BYTES = int(TRANSPORT_CONTRACT["max_frame_bytes"])
MAX_PACKAGE_FILE_BYTES = int(TRANSPORT_CONTRACT["max_package_file_bytes"])
MAX_PACKAGE_FILE_COUNT = int(TRANSPORT_CONTRACT["max_package_file_count"])
MAX_PACKAGE_MANIFEST_BYTES = int(TRANSPORT_CONTRACT["max_package_manifest_bytes"])
PACKAGE_ENVELOPE_OVERHEAD_BYTES = int(TRANSPORT_CONTRACT["envelope_overhead_bytes"])
PACKAGE_FRAME_SAFETY_MARGIN_BYTES = int(TRANSPORT_CONTRACT["safety_margin_bytes"])
MAX_PACKAGE_TOTAL_BYTES = int(TRANSPORT_CONTRACT["max_package_total_bytes"])
MAX_PACKAGE_FILE_BASE64_CHARS = int(TRANSPORT_CONTRACT["max_package_file_base64_chars"])


__all__ = [
    "MAX_FRAME_BYTES",
    "MAX_PACKAGE_FILE_BASE64_CHARS",
    "MAX_PACKAGE_FILE_BYTES",
    "MAX_PACKAGE_FILE_COUNT",
    "MAX_PACKAGE_MANIFEST_BYTES",
    "MAX_PACKAGE_TOTAL_BYTES",
    "PACKAGE_ENVELOPE_OVERHEAD_BYTES",
    "PACKAGE_FRAME_SAFETY_MARGIN_BYTES",
    "TRANSPORT_CONTRACT",
    "TRANSPORT_CONTRACT_SCHEMA_VERSION",
]
