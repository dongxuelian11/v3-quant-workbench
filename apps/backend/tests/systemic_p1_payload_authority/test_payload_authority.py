from __future__ import annotations

import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path

from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.domain.artifacts.identity import (
    artifact_id_for_bytes,
    storage_key_for_artifact_id,
)
from v3_backend.domain.payload_authority import (
    RESOLVER_CONTRACT_VERSION,
    CanonicalPayloadBinding,
    CanonicalPayloadResolver,
    PayloadArtifactIdMismatch,
    PayloadArtifactUnavailable,
    PayloadBindingUnavailable,
    PayloadContentMismatch,
    PayloadContextMismatch,
    PayloadOwnerMismatch,
    PayloadReadBoundExceeded,
    PayloadResolutionReceipt,
    PayloadResolutionRequest,
    PayloadRoleMismatch,
    PayloadSizeMismatch,
    VerifiedPayload,
)


class StaticBindingResolver:
    def __init__(self, binding: CanonicalPayloadBinding | None) -> None:
        self.binding = binding
        self.calls = 0

    def resolve(
        self, request: PayloadResolutionRequest
    ) -> CanonicalPayloadBinding | None:
        self.calls += 1
        return self.binding


class StaticByteReader:
    def __init__(self, payload: bytes | None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, int]] = []

    def read_bytes(self, artifact_id: str, *, max_bytes: int) -> bytes:
        self.calls.append((artifact_id, max_bytes))
        if self.payload is None:
            raise FileNotFoundError(artifact_id)
        return self.payload


class CanonicalPayloadAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = b'{"samples":[1,2],"values":[10,20]}'
        self.sha256 = hashlib.sha256(self.payload).hexdigest()
        self.artifact_id = artifact_id_for_bytes(self.payload)
        self.request = PayloadResolutionRequest(
            owner_namespace="DATASET",
            owner_id="dsv_001",
            owner_version="1",
            payload_role="TEXT_REPORT",
            context_identity="ctx_sha256_001",
            max_bytes=1024,
        )
        self.binding = CanonicalPayloadBinding(
            owner_namespace=self.request.owner_namespace,
            owner_id=self.request.owner_id,
            owner_version=self.request.owner_version,
            payload_role=self.request.payload_role,
            artifact_id=self.artifact_id,
            expected_sha256=self.sha256,
            expected_byte_size=len(self.payload),
            context_identity=self.request.context_identity,
            binding_version="dataset-binding/1",
            schema_fingerprint="schema_sha256_001",
            semantic_fingerprint="semantic_sha256_001",
            provenance_reference_id="prv_001",
        )

    def resolver(
        self,
        *,
        binding: CanonicalPayloadBinding | None = None,
        payload: bytes | None = None,
    ) -> tuple[CanonicalPayloadResolver, StaticBindingResolver, StaticByteReader]:
        owner = StaticBindingResolver(self.binding if binding is None else binding)
        reader = StaticByteReader(self.payload if payload is None else payload)
        return (
            CanonicalPayloadResolver(binding_resolver=owner, byte_reader=reader),
            owner,
            reader,
        )

    def binding_with(self, **changes: object) -> CanonicalPayloadBinding:
        values = {
            "owner_namespace": self.binding.owner_namespace,
            "owner_id": self.binding.owner_id,
            "owner_version": self.binding.owner_version,
            "payload_role": self.binding.payload_role,
            "artifact_id": self.binding.artifact_id,
            "expected_sha256": self.binding.expected_sha256,
            "expected_byte_size": self.binding.expected_byte_size,
            "context_identity": self.binding.context_identity,
            "binding_version": self.binding.binding_version,
            "schema_fingerprint": self.binding.schema_fingerprint,
            "semantic_fingerprint": self.binding.semantic_fingerprint,
            "provenance_reference_id": self.binding.provenance_reference_id,
        }
        values.update(changes)
        return CanonicalPayloadBinding(**values)  # type: ignore[arg-type]

    def test_p1_01_deterministic_request_identity(self) -> None:
        same = PayloadResolutionRequest(**{
            "max_bytes": self.request.max_bytes,
            "context_identity": self.request.context_identity,
            "payload_role": self.request.payload_role,
            "owner_version": self.request.owner_version,
            "owner_id": self.request.owner_id,
            "owner_namespace": self.request.owner_namespace,
        })
        self.assertEqual(self.request.request_identity, same.request_identity)
        self.assertTrue(self.request.request_identity.startswith("prq_sha256_"))

    def test_p1_02_deterministic_binding_identity(self) -> None:
        same = self.binding_with()
        self.assertEqual(self.binding.binding_identity, same.binding_identity)
        self.assertTrue(self.binding.binding_identity.startswith("cpb_sha256_"))

    def test_p1_03_deterministic_receipt_identity(self) -> None:
        resolver, _, _ = self.resolver()
        first = resolver.resolve(self.request).receipt
        second = resolver.resolve(self.request).receipt
        self.assertEqual(first.receipt_identity, second.receipt_identity)
        self.assertEqual(first.resolver_contract_version, RESOLVER_CONTRACT_VERSION)
        self.assertTrue(first.receipt_identity.startswith("prr_sha256_"))
        self.assertNotIn("time", first.to_identity_wire())

    def test_p1_04_correct_binding_and_exact_bytes_succeeds(self) -> None:
        resolver, owner, reader = self.resolver()
        result = resolver.resolve(self.request)
        self.assertEqual(result.verified_payload.payload, self.payload)
        self.assertEqual(result.receipt.actual_sha256, self.sha256)
        self.assertEqual(result.receipt.result_status, "VERIFIED")
        self.assertEqual(owner.calls, 1)
        self.assertEqual(reader.calls, [(self.artifact_id, self.request.max_bytes)])

    def test_p1_05_correct_looking_ref_with_altered_bytes_rejects(self) -> None:
        altered = b'{"samples":[1,2],"values":[10,21]}'
        resolver, _, _ = self.resolver(payload=altered)
        with self.assertRaises(PayloadContentMismatch) as observed:
            resolver.resolve(self.request)
        self.assertEqual(observed.exception.code, "PAYLOAD_CONTENT_MISMATCH")

    def test_p1_06_correct_sha_field_with_altered_numeric_payload_rejects(self) -> None:
        altered = b'{"samples":[1,3],"values":[10,20]}'
        resolver, _, _ = self.resolver(payload=altered)
        with self.assertRaises(PayloadContentMismatch):
            resolver.resolve(self.request)

    def test_p1_07_owner_mismatch_rejects_before_byte_read(self) -> None:
        binding = self.binding_with(owner_id="dsv_other")
        resolver, _, reader = self.resolver(binding=binding)
        with self.assertRaises(PayloadOwnerMismatch) as observed:
            resolver.resolve(self.request)
        self.assertEqual(observed.exception.code, "PAYLOAD_OWNER_MISMATCH")
        self.assertEqual(reader.calls, [])

    def test_p1_08_payload_role_mismatch_rejects(self) -> None:
        resolver, _, reader = self.resolver(
            binding=self.binding_with(payload_role="MODEL_BYTES")
        )
        with self.assertRaises(PayloadRoleMismatch):
            resolver.resolve(self.request)
        self.assertEqual(reader.calls, [])

    def test_p1_09_context_mismatch_rejects(self) -> None:
        resolver, _, reader = self.resolver(
            binding=self.binding_with(context_identity="ctx_sha256_other")
        )
        with self.assertRaises(PayloadContextMismatch):
            resolver.resolve(self.request)
        self.assertEqual(reader.calls, [])

    def test_p1_10_artifact_id_and_sha_mismatch_rejects(self) -> None:
        other_artifact_id = artifact_id_for_bytes(b"other")
        resolver, _, reader = self.resolver(
            binding=self.binding_with(artifact_id=other_artifact_id)
        )
        with self.assertRaises(PayloadArtifactIdMismatch):
            resolver.resolve(self.request)
        self.assertEqual(reader.calls, [])

    def test_p1_11_byte_size_mismatch_rejects(self) -> None:
        resolver, _, _ = self.resolver(
            binding=self.binding_with(expected_byte_size=len(self.payload) + 1)
        )
        with self.assertRaises(PayloadSizeMismatch) as observed:
            resolver.resolve(self.request)
        self.assertEqual(observed.exception.code, "PAYLOAD_SIZE_MISMATCH")

    def test_p1_12_max_read_bound_is_positive_and_enforced_twice(self) -> None:
        for invalid in (0, -1, True, "10"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(PayloadReadBoundExceeded):
                    PayloadResolutionRequest(
                        owner_namespace="DATASET",
                        owner_id="dsv_001",
                        owner_version="1",
                        payload_role="TEXT_REPORT",
                        context_identity="ctx_001",
                        max_bytes=invalid,  # type: ignore[arg-type]
                    )

        small_request = PayloadResolutionRequest(
            owner_namespace=self.request.owner_namespace,
            owner_id=self.request.owner_id,
            owner_version=self.request.owner_version,
            payload_role=self.request.payload_role,
            context_identity=self.request.context_identity,
            max_bytes=len(self.payload) - 1,
        )
        resolver, _, reader = self.resolver()
        with self.assertRaises(PayloadReadBoundExceeded):
            resolver.resolve(small_request)
        self.assertEqual(reader.calls, [])

        bounded_payload = b"abc"
        bounded_sha = hashlib.sha256(bounded_payload).hexdigest()
        bounded_binding = self.binding_with(
            artifact_id=artifact_id_for_bytes(bounded_payload),
            expected_sha256=bounded_sha,
            expected_byte_size=3,
        )
        malicious_reader = StaticByteReader(b"abcd")
        bounded_resolver = CanonicalPayloadResolver(
            binding_resolver=StaticBindingResolver(bounded_binding),
            byte_reader=malicious_reader,
        )
        bounded_request = PayloadResolutionRequest(
            owner_namespace=self.request.owner_namespace,
            owner_id=self.request.owner_id,
            owner_version=self.request.owner_version,
            payload_role=self.request.payload_role,
            context_identity=self.request.context_identity,
            max_bytes=3,
        )
        with self.assertRaises(PayloadReadBoundExceeded):
            bounded_resolver.resolve(bounded_request)

    def test_p1_13_missing_binding_remains_unavailable(self) -> None:
        owner = StaticBindingResolver(None)
        reader = StaticByteReader(self.payload)
        resolver = CanonicalPayloadResolver(binding_resolver=owner, byte_reader=reader)
        with self.assertRaises(PayloadBindingUnavailable) as observed:
            resolver.resolve(self.request)
        self.assertEqual(observed.exception.code, "PAYLOAD_BINDING_UNAVAILABLE")
        self.assertEqual(reader.calls, [])

    def test_p1_14_missing_artifact_remains_unavailable(self) -> None:
        owner = StaticBindingResolver(self.binding)
        reader = StaticByteReader(None)
        resolver = CanonicalPayloadResolver(binding_resolver=owner, byte_reader=reader)
        with self.assertRaises(PayloadArtifactUnavailable) as observed:
            resolver.resolve(self.request)
        self.assertEqual(observed.exception.code, "PAYLOAD_ARTIFACT_UNAVAILABLE")
        self.assertIsInstance(observed.exception.__cause__, FileNotFoundError)

    def test_p1_15_resolver_independently_rehashes_reader_bytes(self) -> None:
        resolver, _, _ = self.resolver(payload=b"reader claimed these were verified")
        with self.assertRaises(PayloadContentMismatch):
            resolver.resolve(self.request)

    def test_p1_16_existing_filesystem_artifact_store_is_directly_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = FileSystemArtifactStore(Path(temp))
            stage = store.stage_bytes(self.payload)
            publication = store.publish(
                stage.staging_token,
                expected_sha256=stage.sha256,
                expected_byte_size=stage.byte_size,
                media_type="text/plain",
                role=self.request.payload_role,
                provenance_entity_id="prv_01H00000000000000000000000",
                schema_fingerprint=self.binding.schema_fingerprint,
                semantic_fingerprint=self.binding.semantic_fingerprint,
            )
            binding = self.binding_with(
                artifact_id=publication.descriptor.artifact_id,
                expected_sha256=publication.descriptor.sha256,
                expected_byte_size=publication.descriptor.byte_size,
            )
            resolver = CanonicalPayloadResolver(
                binding_resolver=StaticBindingResolver(binding),
                byte_reader=store,
            )
            result = resolver.resolve(self.request)
            self.assertEqual(result.verified_payload.payload, self.payload)

    def test_p1_17_tampered_published_bytes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = FileSystemArtifactStore(root)
            stage = store.stage_bytes(self.payload)
            publication = store.publish(
                stage.staging_token,
                expected_sha256=stage.sha256,
                expected_byte_size=stage.byte_size,
                media_type="text/plain",
                role=self.request.payload_role,
                provenance_entity_id="prv_01H00000000000000000000000",
            )
            final = root.joinpath(
                *storage_key_for_artifact_id(publication.descriptor.artifact_id).split("/")
            )
            final.write_bytes(b"tampered published bytes")
            resolver = CanonicalPayloadResolver(
                binding_resolver=StaticBindingResolver(self.binding),
                byte_reader=store,
            )
            with self.assertRaises(PayloadContentMismatch) as observed:
                resolver.resolve(self.request)
            self.assertIsNotNone(observed.exception.__cause__)

    def test_p1_18_manually_constructed_verified_payload_is_not_authority(self) -> None:
        forged = VerifiedPayload(
            request_identity=self.request.request_identity,
            binding_identity=self.binding.binding_identity,
            artifact_id=self.artifact_id,
            actual_sha256=self.sha256,
            actual_byte_size=len(self.payload),
            context_identity=self.request.context_identity,
            payload=self.payload,
        )
        resolver, owner, _ = self.resolver()
        with self.assertRaises(TypeError):
            resolver.resolve(forged)  # type: ignore[arg-type]
        self.assertEqual(owner.calls, 0)

    def test_p1_19_manually_constructed_receipt_is_not_authority(self) -> None:
        forged = PayloadResolutionReceipt(
            request_identity=self.request.request_identity,
            binding_identity=self.binding.binding_identity,
            artifact_id=self.artifact_id,
            actual_sha256=self.sha256,
            actual_byte_size=len(self.payload),
            context_identity=self.request.context_identity,
        )
        resolver, owner, _ = self.resolver()
        with self.assertRaises(TypeError):
            resolver.resolve(forged)  # type: ignore[arg-type]
        self.assertEqual(owner.calls, 0)

    def test_p1_20_request_contract_cannot_carry_raw_authoritative_payload(self) -> None:
        fields = set(inspect.signature(PayloadResolutionRequest).parameters)
        forbidden = {"values", "prices", "samples", "scores", "market_state", "payload_bytes"}
        self.assertTrue(forbidden.isdisjoint(fields))
        with self.assertRaises(TypeError):
            PayloadResolutionRequest(
                owner_namespace="DATASET",
                owner_id="dsv_001",
                owner_version="1",
                payload_role="TEXT_REPORT",
                context_identity="ctx_001",
                max_bytes=10,
                values=(1, 2),  # type: ignore[call-arg]
            )


if __name__ == "__main__":
    unittest.main()
