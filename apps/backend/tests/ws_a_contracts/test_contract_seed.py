
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "apps" / "backend" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
FIXTURES = Path(__file__).parent / "fixtures"

from v3_backend.contracts.common.ids import IDENTITY_SPECS, LIFECYCLE_STATES_BY_OBJECT
from v3_backend.contracts.registry import OPERATION_COUNT, OPERATIONS, SERVICE_CONTRACTS
from v3_backend.errors.codes import ErrorCode


class ContractSeedConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads((FIXTURES / "asl" / "index.json").read_text(encoding="utf-8"))

    def test_fixture_manifest_hashes(self) -> None:
        manifest = json.loads((FIXTURES / "conformance_manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            data = (FIXTURES / entry["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"], entry["path"])

    def test_registry_counts_and_frozen_seventeen_service_subset(self) -> None:
        # Product Entry expansion (task-authorized, non-P0): 17->18 services,
        # 64->74 operations.  The original frozen v1 registry and the first
        # three Product Entry 1.0 wire methods remain an EXACT subset; the
        # fourth and fifth operations are additive 1.1 and may not collide.
        legacy_services = [
            item for item in self.index["services"] if item["service"] != "ProductEntryService"
        ]
        self.assertEqual(len(legacy_services), 17)
        self.assertEqual(len(SERVICE_CONTRACTS), 18)
        self.assertEqual(OPERATION_COUNT, 74)
        self.assertEqual(len(OPERATIONS), len(set(OPERATIONS)))
        for item in legacy_services:
            contract = SERVICE_CONTRACTS[item["service"]]
            self.assertEqual(contract.contract_id, item["contract_id"])
            self.assertEqual(tuple(op.operation_id for op in contract.operations), tuple(item["method_operation_ids"]))
        product_entry = SERVICE_CONTRACTS["ProductEntryService"]
        self.assertEqual(len(product_entry.operations), 10)
        self.assertEqual(product_entry.api_version, "1.1.0")
        self.assertEqual(
            tuple(operation.version for operation in product_entry.operations[:3]),
            ("1.0.0", "1.0.0", "1.0.0"),
        )
        self.assertEqual(
            tuple(operation.operation_id for operation in product_entry.operations[:3]),
            (
                "ProductEntryService.v1.listBacktestRunSpecs",
                "ProductEntryService.v1.importResearchPackage",
                "ProductEntryService.v1.submitResearch",
            ),
        )
        self.assertEqual(
            product_entry.operations[3].operation_id,
            "ProductEntryService.v1.importLocalDataset",
        )
        self.assertEqual(product_entry.operations[3].version, "1.1.0")
        self.assertEqual(
            product_entry.operations[4].operation_id,
            "ProductEntryService.v1.submitFactorStudy",
        )
        self.assertEqual(product_entry.operations[4].version, "1.1.0")
        self.assertEqual(
            product_entry.operations[5].operation_id,
            "ProductEntryService.v1.previewResearchStrategy",
        )
        self.assertEqual(product_entry.operations[5].version, "1.1.0")
        self.assertEqual(
            product_entry.operations[6].operation_id,
            "ProductEntryService.v1.publishResearchStrategy",
        )
        self.assertEqual(product_entry.operations[6].version, "1.1.0")
        self.assertEqual(
            product_entry.operations[7].operation_id,
            "ProductEntryService.v1.previewResearchBacktest",
        )
        self.assertEqual(product_entry.operations[7].version, "1.1.0")
        self.assertEqual(
            product_entry.operations[8].operation_id,
            "ProductEntryService.v1.submitResearchBacktest",
        )
        self.assertEqual(product_entry.operations[8].version, "1.1.0")
        self.assertEqual(
            product_entry.operations[9].operation_id,
            "ProductEntryService.v1.getProjectHome",
        )
        self.assertEqual(product_entry.operations[9].version, "1.1.0")
        legacy_operation_ids = {
            operation_id
            for item in legacy_services
            for operation_id in item["method_operation_ids"]
        }
        self.assertEqual(len(legacy_operation_ids), 64)
        self.assertEqual(
            set(op.operation_id for op in product_entry.operations) & legacy_operation_ids,
            set(),
            "Product Entry operation IDs must not collide with frozen IDs",
        )

    def test_explicit_dto_classes_and_schemas_match_every_contract(self) -> None:
        for index_item in self.index["services"]:
            fixture = json.loads((FIXTURES / "asl" / index_item["path"]).read_text(encoding="utf-8"))
            contract = SERVICE_CONTRACTS[index_item["service"]]
            by_id = contract.by_operation_id
            for method in fixture["methods"]:
                operation = by_id[method["operation_id"]]
                self.assertEqual(operation.request_type.__name__, method["request_dto"]["name"])
                self.assertEqual(operation.response_type.__name__, method["response_dto"]["name"])
                self.assertEqual(operation.request_type.SCHEMA, method["request_dto"]["schema"])
                self.assertEqual(operation.response_type.SCHEMA, method["response_dto"]["schema"])
                self.assertIs(method["request_dto"]["schema"]["additionalProperties"], False)
                self.assertIs(method["response_dto"]["schema"]["additionalProperties"], False)

    def test_error_codes_are_exact_authority_union(self) -> None:
        expected = set()
        for item in self.index["services"]:
            fixture = json.loads((FIXTURES / "asl" / item["path"]).read_text(encoding="utf-8"))
            for method in fixture["methods"]:
                expected.update(method["errors"])
        self.assertEqual({code.value for code in ErrorCode}, expected)

    def test_id_and_lifecycle_registry_matches_authority(self) -> None:
        registry = json.loads((FIXTURES / "02_DOMAIN_OBJECT_REGISTRY.json").read_text(encoding="utf-8"))
        self.assertEqual(len(IDENTITY_SPECS), len(registry["objects"]))
        for item in registry["objects"]:
            self.assertEqual(IDENTITY_SPECS[item["name"]].identity, item["identity"])
            self.assertEqual(LIFECYCLE_STATES_BY_OBJECT[item["name"]], tuple(item["lifecycle"]))

    def test_no_generic_service_api(self) -> None:
        for contract in SERVICE_CONTRACTS.values():
            self.assertFalse(hasattr(contract, "execute"))
            for operation in contract.operations:
                self.assertNotIn("action", operation.request_type.SCHEMA.get("properties", {}))


if __name__ == "__main__":
    unittest.main()
