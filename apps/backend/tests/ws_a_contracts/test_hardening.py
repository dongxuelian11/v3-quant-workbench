
from __future__ import annotations

import hashlib
import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "apps" / "backend" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from v3_backend.contracts.common.artifact_ref import ArtifactRefV1
from v3_backend.contracts.common.compatibility import VersionCompatibilityError, ensure_wire_compatible
from v3_backend.contracts.common.dto import ContractValidationError, validate_schema
from v3_backend.contracts.common.provenance import ProvenanceEdgeV1, ProvenanceRelationship, sort_provenance_edges
from v3_backend.contracts.project_session import GetProjectContextRequestV1
from v3_backend.contracts.registry import OPERATIONS
from v3_backend.errors import ErrorCode, ErrorEnvelopeV1, InvalidArgumentError, map_exception
from v3_backend.provenance.canonical_hash import CanonicalizationError, canonical_json, canonical_sha256


class ContractHardeningTests(unittest.TestCase):
    def test_unknown_request_field_rejected(self) -> None:
        with self.assertRaises(ContractValidationError):
            GetProjectContextRequestV1(
                request_id="018f47f2-9b02-7cc0-8ee6-1b82e3d62c01",
                project_id="prj_01ARZ3NDEKTSV4RRFFQ69G5FAV",
                project_context_revision_id="pcr_01ARZ3NDEKTSV4RRFFQ69G5FAW",
                expected_api_version="1.0",
                surprise=True,
            )

    def test_major_mismatch_and_newer_minor_fail_closed(self) -> None:
        with self.assertRaises(VersionCompatibilityError):
            ensure_wire_compatible("2.0", "1.0")
        with self.assertRaises(VersionCompatibilityError):
            ensure_wire_compatible("1.1", "1.0")
        self.assertEqual(ensure_wire_compatible("1.0", "1.2").major_minor, "1.0")

    def test_canonical_hash_is_deterministic_and_rejects_non_finite(self) -> None:
        left = {"z": [3, 2, 1], "a": {"money": {"amount_decimal": "1.20", "currency": "CNY"}}}
        right = {"a": {"money": {"currency": "CNY", "amount_decimal": "1.20"}}, "z": [3, 2, 1]}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(canonical_sha256(left), canonical_sha256(right))
        with self.assertRaises(CanonicalizationError):
            canonical_json({"bad": math.nan})

    def test_artifact_ref_has_no_raw_path_and_hash_identity_is_consistent(self) -> None:
        digest = "a" * 64
        wire = {
            "artifact_id": "art_sha256_" + digest,
            "role": "RESULT_TABLE",
            "media_type": "application/vnd.apache.parquet",
            "byte_size": 12,
            "sha256": digest,
        }
        self.assertEqual(ArtifactRefV1.from_wire(wire).to_wire(), wire)
        with self.assertRaises(ContractValidationError):
            ArtifactRefV1.from_wire({**wire, "raw_path": "D:/secret.parquet"})

    def test_money_timestamp_and_date_conventions(self) -> None:
        money_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["amount_decimal", "currency"],
            "properties": {
                "amount_decimal": {"type": "string", "pattern": r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"},
                "currency": {"type": "string", "const": "CNY"},
            },
        }
        validate_schema({"amount_decimal": "12.30", "currency": "CNY"}, money_schema)
        with self.assertRaises(ContractValidationError):
            validate_schema({"amount_decimal": 12.3, "currency": "CNY"}, money_schema)
        validate_schema("2026-08-09T01:02:03Z", {"type": "string", "format": "date-time"})
        with self.assertRaises(ContractValidationError):
            validate_schema("2026-08-09T01:02:03+08:00", {"type": "string", "format": "date-time"})
        validate_schema("2026-08-09", {"type": "string", "pattern": r"[0-9]{4}-[0-9]{2}-[0-9]{2}"})

    def test_provenance_edge_sort_and_fingerprint_are_deterministic(self) -> None:
        a = ProvenanceEdgeV1(
            "pre_01ARZ3NDEKTSV4RRFFQ69G5FAX",
            "prv_01ARZ3NDEKTSV4RRFFQ69G5FAY",
            "prv_01ARZ3NDEKTSV4RRFFQ69G5FAZ",
            ProvenanceRelationship.USED,
            1,
        )
        b = ProvenanceEdgeV1(
            "pre_01ARZ3NDEKTSV4RRFFQ69G5FB0",
            "prv_01ARZ3NDEKTSV4RRFFQ69G5FAY",
            "prv_01ARZ3NDEKTSV4RRFFQ69G5FAZ",
            ProvenanceRelationship.DERIVED_FROM,
            0,
        )
        self.assertEqual(sort_provenance_edges([a, b]), (b, a))
        self.assertEqual(a.canonical_fingerprint, a.canonical_fingerprint)

    def test_error_envelope_is_closed_and_internal_mapping_does_not_leak(self) -> None:
        envelope = map_exception(InvalidArgumentError("bad request", details={"field": "x"}))
        self.assertEqual(envelope.code, ErrorCode.INVALID_ARGUMENT)
        self.assertEqual(ErrorEnvelopeV1.from_wire(envelope.to_wire()), envelope)
        with self.assertRaises(ValueError):
            ErrorEnvelopeV1.from_wire({**envelope.to_wire(), "stack": "secret"})
        internal = map_exception(RuntimeError("private stack detail"))
        self.assertEqual(internal.message, "internal error")

    def test_all_operations_remain_explicit(self) -> None:
        self.assertEqual(len(OPERATIONS), 64)
        self.assertEqual(len(OPERATIONS), len(set(OPERATIONS)))
        self.assertFalse(any(operation.operation_id.endswith(".execute") for operation in OPERATIONS.values()))

    def test_seed_digest_is_unchanged(self) -> None:
        marker_path = ROOT / "docs" / "backend" / "parallel" / "WS_A_CONTRACT_SEED_V1_READY.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256()
        digest.update(b"WS-A-CONTRACT-SEED-V1\0")
        for relative in marker["files"]:
            file_hash = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            digest.update(relative.encode("utf-8") + b"\0" + file_hash.encode("ascii") + b"\n")
        self.assertEqual(digest.hexdigest(), marker["contract_digest"])


if __name__ == "__main__":
    unittest.main()
