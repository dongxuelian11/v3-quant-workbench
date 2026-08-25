from __future__ import annotations

import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v3_backend.contracts.registry import SERVICE_CONTRACTS
from v3_backend.errors.exceptions import TruthPreconditionFailedError
from v3_backend.runtime.composition_root import RuntimePorts, RuntimeSession
from v3_backend.runtime.framed_stdio import FrameDecoder, encode_frame
from v3_backend.runtime.handshake import create_hello, token_proof
from v3_backend.runtime.local_data_transfer import LOCAL_DATA_TRANSFER_PROTOCOL
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_runtime import ProductRuntime, connect_catalog

from .test_local_data_import import CSV_SHARES


TOKEN = bytes(range(32))
CONTROL_ID = "01890f3c-7b5a-7000-8000-000000000007"


def _begin(project: dict[str, str], *, byte_size: int) -> dict[str, object]:
    return {
        "kind": "localData.beginTransfer",
        "protocol_version": LOCAL_DATA_TRANSFER_PROTOCOL,
        "project_id": project["project_id"],
        "project_context_revision_id": project["project_context_revision_id"],
        "display_name": "golden.csv",
        "media_type": "text/csv",
        "expected_byte_size": byte_size,
    }


class LocalDataTransferTests(unittest.TestCase):
    def test_chunked_transfer_publishes_exact_project_scoped_raw_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-local-data-transfer-") as directory:
            product = ProductRuntime(Path(directory))
            project = create_project(
                product,
                display_name="Native local transfer",
                notes=None,
                idempotency_key="native-transfer-project",
            )
            service = product.local_data_transfers
            ready = service.handle(
                "localData.beginTransfer", _begin(project, byte_size=len(CSV_SHARES))
            )
            transfer_id = ready["transfer_id"]
            offset = 0
            for payload in (CSV_SHARES[:37], CSV_SHARES[37:]):
                accepted = service.handle(
                    "localData.appendChunk",
                    {
                        "kind": "localData.appendChunk",
                        "protocol_version": LOCAL_DATA_TRANSFER_PROTOCOL,
                        "transfer_id": transfer_id,
                        "offset": offset,
                        "payload_base64": base64.b64encode(payload).decode("ascii"),
                        "chunk_sha256": hashlib.sha256(payload).hexdigest(),
                    },
                )
                offset += len(payload)
                self.assertEqual(accepted["next_offset"], offset)
            source = service.handle(
                "localData.finishTransfer",
                {
                    "kind": "localData.finishTransfer",
                    "protocol_version": LOCAL_DATA_TRANSFER_PROTOCOL,
                    "transfer_id": transfer_id,
                    "expected_sha256": hashlib.sha256(CSV_SHARES).hexdigest(),
                    "expected_byte_size": len(CSV_SHARES),
                },
            )["source"]
            self.assertEqual(source["artifact_id"], "art_sha256_" + source["sha256"])
            self.assertEqual(source["byte_size"], len(CSV_SHARES))
            self.assertEqual(product.read_verified_bytes(source["artifact_id"]), CSV_SHARES)
            connection = connect_catalog(product.database_path, read_only=True)
            try:
                reference = connection.execute(
                    """
                    SELECT r.owner_id,r.role,a.semantic_role,a.state
                    FROM artifact_reference r JOIN artifact a ON a.artifact_id=r.artifact_id
                    WHERE r.artifact_id=? AND r.state='ACTIVE'
                    """,
                    (source["artifact_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(
                tuple(reference),
                (project["project_id"], "LOCAL_DATA_RAW_FILE", "LOCAL_DATA_RAW_FILE", "PUBLISHED"),
            )

    def test_wrong_scope_chunk_or_final_identity_fails_without_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-local-data-transfer-negative-") as directory:
            product = ProductRuntime(Path(directory))
            project = create_project(
                product,
                display_name="Transfer negatives",
                notes=None,
                idempotency_key="native-transfer-negative-project",
            )
            other_project = create_project(
                product,
                display_name="Other transfer project",
                notes=None,
                idempotency_key="native-transfer-other-project",
            )
            service = product.local_data_transfers
            with self.assertRaises(TruthPreconditionFailedError):
                service.handle(
                    "localData.beginTransfer",
                    {**_begin(project, byte_size=len(CSV_SHARES)), "project_id": other_project["project_id"]},
                )

            ready = service.handle(
                "localData.beginTransfer", _begin(project, byte_size=len(CSV_SHARES))
            )
            transfer_id = ready["transfer_id"]
            with self.assertRaises(TruthPreconditionFailedError):
                service.handle(
                    "localData.appendChunk",
                    {
                        "kind": "localData.appendChunk",
                        "protocol_version": LOCAL_DATA_TRANSFER_PROTOCOL,
                        "transfer_id": transfer_id,
                        "offset": 0,
                        "payload_base64": base64.b64encode(CSV_SHARES).decode("ascii"),
                        "chunk_sha256": "0" * 64,
                    },
                )
            service.handle(
                "localData.appendChunk",
                {
                    "kind": "localData.appendChunk",
                    "protocol_version": LOCAL_DATA_TRANSFER_PROTOCOL,
                    "transfer_id": transfer_id,
                    "offset": 0,
                    "payload_base64": base64.b64encode(CSV_SHARES).decode("ascii"),
                    "chunk_sha256": hashlib.sha256(CSV_SHARES).hexdigest(),
                },
            )
            with self.assertRaises(TruthPreconditionFailedError):
                service.handle(
                    "localData.finishTransfer",
                    {
                        "kind": "localData.finishTransfer",
                        "protocol_version": LOCAL_DATA_TRANSFER_PROTOCOL,
                        "transfer_id": transfer_id,
                        "expected_sha256": "f" * 64,
                        "expected_byte_size": len(CSV_SHARES),
                    },
                )
            self.assertEqual(product.artifact_store.recover_staging(), ())
            connection = connect_catalog(product.database_path, read_only=True)
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM artifact WHERE semantic_role='LOCAL_DATA_RAW_FILE'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 0)

    def test_runtime_control_owns_correlation_and_strips_it_from_stage_owner(self) -> None:
        fixed_hello = create_hello("backend", 1, "0.1.0", [], nonce="ab" * 32)
        accept = {
            "kind": "supervisor.accept",
            "token_proof": token_proof(TOKEN, fixed_hello["nonce"]),
            "requested_protocol": "v3.local/1.0",
            "requested_asl_versions": {name: "1.0" for name in SERVICE_CONTRACTS},
            "desktop_version": "0.1.0",
            "project_id": None,
            "project_context_revision_id": None,
            "last_project_event_sequence": 0,
        }
        owner_messages: list[dict[str, object]] = []

        def owner(kind: str, message: object) -> dict[str, object]:
            owner_messages.append(dict(message))
            return {
                "kind": "localData.transferReady",
                "transfer_id": "ldt_01ARZ3NDEKTSV4RRFFQ69G5FAX",
                "next_offset": 0,
                "max_chunk_bytes": 262_144,
            }

        request = {
            **_begin(
                {
                    "project_id": "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "project_context_revision_id": "pcr_01ARZ3NDEKTSV4RRFFQ69G5FAW",
                },
                byte_size=100,
            ),
            "control_request_id": CONTROL_ID,
            "runtime_generation": 7,
            "deadline_at": "2026-08-24T12:00:00Z",
        }
        source = io.BytesIO(encode_frame(accept) + encode_frame(request))
        sink = io.BytesIO()
        session = RuntimeSession(
            RuntimePorts(local_data_control=owner),
            TOKEN,
            "0.1.0",
            backend_instance_id="backend",
        )
        with patch("v3_backend.runtime.composition_root.create_hello", return_value=fixed_hello):
            session.run(source, sink)
        decoded = FrameDecoder().feed(sink.getvalue())
        self.assertEqual(decoded[2]["kind"], "localData.transferReady")
        self.assertEqual(decoded[2]["control_request_id"], CONTROL_ID)
        self.assertEqual(decoded[2]["runtime_generation"], 7)
        self.assertEqual(owner_messages, [_begin({
            "project_id": "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "project_context_revision_id": "pcr_01ARZ3NDEKTSV4RRFFQ69G5FAW",
        }, byte_size=100)])


if __name__ == "__main__":
    unittest.main()
