from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from v3_backend.adapters.local_data import LocalDataImportIntentV1, LocalDataImportLimits
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_factor import ProductFactorStudyService
from v3_backend.runtime.product_runtime import ProductRuntime
from v3_backend.runtime.product_strategy import (
    ProductStrategyService,
    ResearchStrategySpecV1,
)
from v3_backend.errors.exceptions import TruthPreconditionFailedError

from apps.backend.tests.v1_1_factor.test_factor_panel import GOLDEN_FORMULA, _panel_csv


def _strategy_case(root: Path):
    product = ProductRuntime(root)
    project = create_project(
        product,
        display_name="Canonical product strategy",
        notes=None,
        idempotency_key="create-product-strategy",
    )
    imported = ProductDataService(product).import_local_dataset(
        project_id=project["project_id"],
        project_context_revision_id=project["project_context_revision_id"],
        display_name="strategy-panel.csv",
        source=io.BytesIO(_panel_csv()),
        intent=LocalDataImportIntentV1(
            media_type="text/csv",
            volume_unit="SHARES",
            amount_unit="CNY",
            timezone="Asia/Shanghai",
            adjustment="UNADJUSTED",
        ),
        limits=LocalDataImportLimits(max_partition_bytes=6_000),
    )
    study = ProductFactorStudyService(product).run_factor_study(
        project_id=project["project_id"],
        project_context_revision_id=imported["project_context_revision_id"],
        formula_source=GOLDEN_FORMULA,
        analysis_output_name="MJ",
    )
    service = ProductStrategyService(product)
    return product, project, imported, study, service


def _strategy_spec(
    service: ProductStrategyService,
    imported: dict[str, object],
    study: dict[str, object],
    *,
    exit_output_name: str = "DEATH_CROSS",
    assumption_mode: str = "RESEARCH_APPROXIMATE",
) -> ResearchStrategySpecV1:
    profiles = service.bounded_profile_ids()
    if assumption_mode != "RESEARCH_APPROXIMATE":
        profiles = {
            **profiles,
            "assumption_profile_id": next(
                item["assumption_profile_id"]
                for item in service.bounded_assumption_profiles()
                if item["mode"] == assumption_mode
            ),
        }
    outputs = study["outputs"]
    assert isinstance(outputs, dict)
    entry = outputs["GOLDEN_CROSS"]
    exit_signal = outputs[exit_output_name]
    assert isinstance(entry, dict) and isinstance(exit_signal, dict)
    return ResearchStrategySpecV1.create(
        universe_version_id=str(imported["universe_version_id"]),
        entry_signal_factor_version_id=str(entry["factor_definition_version_id"]),
        exit_signal_factor_version_id=str(exit_signal["factor_definition_version_id"]),
        position_sizing="EQUAL_WEIGHT_ACTIVE_SIGNALS",
        max_positions=2,
        gross_exposure="1",
        rebalance="NEXT_OPEN_AFTER_SIGNAL",
        cost_policy_version_id=profiles["cost_policy_version_id"],
        execution_policy_version_id=profiles["execution_policy_version_id"],
        risk_policy_set_version_id=profiles["risk_policy_set_version_id"],
        initial_cash="1000000",
        assumption_profile_id=profiles["assumption_profile_id"],
    )


class ProductStrategyAuthoringAcceptanceTests(unittest.TestCase):
    def test_actual_boolean_factor_materializations_publish_canonical_strategy_chain(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-") as directory:
            root = Path(directory)
            product, project, imported, study, service = _strategy_case(root)
            spec = _strategy_spec(service, imported, study)

            published = service.publish_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                spec=spec,
            )

            self.assertEqual(published["schema_version"], "v3.product-strategy-read-model/1.0.0")
            self.assertEqual(published["truth"], "NOT_FORMAL")
            self.assertEqual(published["admission"], "PRE_ALPHA")
            self.assertEqual(published["project_id"], project["project_id"])
            self.assertEqual(
                published["project_context_revision_id"],
                imported["project_context_revision_id"],
            )
            self.assertEqual(published["snapshot_id"], imported["snapshot_id"])
            self.assertEqual(
                published["universe_version_id"], imported["universe_version_id"]
            )
            self.assertEqual(
                published["entry_signal_ref"]["factor_definition_version_id"],
                spec.entry_signal_factor_version_id,
            )
            self.assertEqual(
                published["entry_signal_ref"]["materialization_id"],
                study["outputs"]["GOLDEN_CROSS"]["materialization_id"],
            )
            self.assertEqual(
                published["exit_signal_ref"]["factor_definition_version_id"],
                spec.exit_signal_factor_version_id,
            )
            self.assertEqual(
                published["exit_signal_ref"]["materialization_id"],
                study["outputs"]["DEATH_CROSS"]["materialization_id"],
            )
            self.assertTrue(published["research_strategy_spec_id"].startswith("rssv_sha256_"))
            self.assertTrue(
                published["research_strategy_spec_artifact_id"].startswith(
                    "art_sha256_"
                )
            )
            self.assertTrue(
                published["strategy_definition_version_id"].startswith("sdv_sha256_")
            )
            self.assertTrue(published["strategy_version_id"].startswith("stv_"))
            self.assertTrue(published["state_materialization_id"].startswith("rsm_sha256_"))
            self.assertGreater(published["decision_chain_count"], 0)
            self.assertEqual(
                set(published["decision_chain_id_prefixes"]),
                {
                    "sig_sha256_",
                    "sel_sha256_",
                    "pint_sha256_",
                    "twv_sha256_",
                    "rar_sha256_",
                    "rawv_sha256_",
                },
            )
            self.assertNotIn("target_weights", published)
            self.assertNotIn("bars", published)
            self.assertNotIn("factor_values", published)

            connection = product._connection()
            try:
                version = connection.execute(
                    """
                    SELECT project_id,strategy_ir_artifact_id,validation_artifact_id,
                           content_hash,compiler_profile_id,state
                    FROM strategy_version WHERE strategy_version_id=?
                    """,
                    (published["strategy_version_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNotNone(version)
            self.assertEqual(version[0], project["project_id"])
            self.assertEqual(
                version[1], published["strategy_definition_artifact_id"]
            )
            self.assertEqual(
                version[2], published["strategy_validation_artifact_id"]
            )
            self.assertEqual(version[4], "v3-strategy-compiler/1.0.0")
            self.assertEqual(version[5], "PUBLISHED")

            reopened = ProductStrategyService(ProductRuntime(root)).get_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                research_strategy_spec_id=published["research_strategy_spec_id"],
            )
            self.assertEqual(reopened, published)

            replayed = service.publish_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                spec=spec,
            )
            self.assertEqual(
                replayed["strategy_version_id"], published["strategy_version_id"]
            )

    def test_cross_project_strategy_authoring_is_rejected_without_read_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-scope-") as directory:
            product, _project, imported, study, service = _strategy_case(Path(directory))
            spec = _strategy_spec(service, imported, study)
            other = create_project(
                product,
                display_name="Other strategy project",
                notes=None,
                idempotency_key="create-other-strategy-project",
            )

            with self.assertRaises(TruthPreconditionFailedError):
                service.publish_strategy(
                    project_id=other["project_id"],
                    project_context_revision_id=other["project_context_revision_id"],
                    spec=spec,
                )

            self.assertEqual(
                product.references(other["project_id"], "PRODUCT_STRATEGY_READ_MODEL"),
                [],
            )

    def test_conflicting_entry_and_exit_signals_fail_before_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-conflict-") as directory:
            product, project, imported, study, service = _strategy_case(Path(directory))
            spec = _strategy_spec(
                service,
                imported,
                study,
                exit_output_name="GOLDEN_CROSS",
            )

            with self.assertRaisesRegex(
                TruthPreconditionFailedError,
                "entry and exit cannot both be true",
            ):
                service.publish_strategy(
                    project_id=project["project_id"],
                    project_context_revision_id=imported["project_context_revision_id"],
                    spec=spec,
                )

            self.assertEqual(
                product.references(project["project_id"], "PRODUCT_STRATEGY_READ_MODEL"),
                [],
            )

    def test_tampered_factor_partition_fails_before_strategy_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-factor-tamper-") as directory:
            product, project, imported, study, service = _strategy_case(Path(directory))
            spec = _strategy_spec(service, imported, study)
            output = study["outputs"]["GOLDEN_CROSS"]
            manifest = json.loads(
                product.read_verified_bytes(output["materialization_artifact_id"]).decode("utf-8")
            )
            partition_id = manifest["partitions"][0]["artifact_id"]
            descriptor = product.require_published_artifact(partition_id)
            path = product.artifact_root.joinpath(*descriptor["storage_key"].split("/"))
            raw = path.read_bytes()
            path.write_bytes(b"X" + raw[1:])

            with self.assertRaises(TruthPreconditionFailedError):
                service.publish_strategy(
                    project_id=project["project_id"],
                    project_context_revision_id=imported["project_context_revision_id"],
                    spec=spec,
                )

            self.assertEqual(
                product.references(project["project_id"], "PRODUCT_STRATEGY_READ_MODEL"),
                [],
            )

    def test_exact_factor_refs_survive_a_later_study_in_the_same_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-history-") as directory:
            product, project, imported, study, service = _strategy_case(Path(directory))
            spec = _strategy_spec(service, imported, study)
            ProductFactorStudyService(product).run_factor_study(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                formula_source="ALT: MA(CLOSE,3);",
                analysis_output_name="ALT",
            )

            published = service.publish_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                spec=spec,
            )

            self.assertEqual(
                published["entry_signal_ref"]["factor_definition_version_id"],
                spec.entry_signal_factor_version_id,
            )
            self.assertEqual(
                published["exit_signal_ref"]["factor_definition_version_id"],
                spec.exit_signal_factor_version_id,
            )

    def test_restart_readback_revalidates_actual_factor_partition_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-recovery-factor-") as directory:
            root = Path(directory)
            product, project, imported, study, service = _strategy_case(root)
            spec = _strategy_spec(service, imported, study)
            published = service.publish_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                spec=spec,
            )
            output = study["outputs"]["GOLDEN_CROSS"]
            manifest = json.loads(
                product.read_verified_bytes(output["materialization_artifact_id"]).decode("utf-8")
            )
            partition_id = manifest["partitions"][0]["artifact_id"]
            descriptor = product.require_published_artifact(partition_id)
            path = product.artifact_root.joinpath(*descriptor["storage_key"].split("/"))
            raw = path.read_bytes()
            path.write_bytes(b"X" + raw[1:])

            with self.assertRaises(TruthPreconditionFailedError):
                ProductStrategyService(ProductRuntime(root)).get_strategy(
                    project_id=project["project_id"],
                    project_context_revision_id=imported["project_context_revision_id"],
                    research_strategy_spec_id=published["research_strategy_spec_id"],
                )

    def test_restart_readback_rejects_released_state_link(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-link-") as directory:
            root = Path(directory)
            product, project, imported, study, service = _strategy_case(root)
            spec = _strategy_spec(service, imported, study)
            published = service.publish_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                spec=spec,
            )
            connection = product._connection()
            try:
                connection.execute(
                    """
                    UPDATE artifact_reference SET state='RELEASED'
                    WHERE owner_type='Project' AND owner_id=? AND role=?
                      AND artifact_id=? AND state='ACTIVE'
                    """,
                    (
                        project["project_id"],
                        "PRODUCT_STRATEGY_STATE_MATERIALIZATION",
                        published["state_materialization_artifact_id"],
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(TruthPreconditionFailedError):
                ProductStrategyService(ProductRuntime(root)).get_strategy(
                    project_id=project["project_id"],
                    project_context_revision_id=imported["project_context_revision_id"],
                    research_strategy_spec_id=published["research_strategy_spec_id"],
                )

    def test_restart_readback_rejects_retired_strategy_version(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-retired-") as directory:
            root = Path(directory)
            product, project, imported, study, service = _strategy_case(root)
            spec = _strategy_spec(service, imported, study)
            published = service.publish_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                spec=spec,
            )
            connection = product._connection()
            try:
                connection.execute(
                    "UPDATE strategy_version SET state='RETIRED' WHERE strategy_version_id=?",
                    (published["strategy_version_id"],),
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(TruthPreconditionFailedError):
                ProductStrategyService(ProductRuntime(root)).get_strategy(
                    project_id=project["project_id"],
                    project_context_revision_id=imported["project_context_revision_id"],
                    research_strategy_spec_id=published["research_strategy_spec_id"],
                )

    def test_restart_readback_rejects_profile_refs_that_disagree_with_spec_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-profile-drift-") as directory:
            root = Path(directory)
            product, project, imported, study, service = _strategy_case(root)
            spec = _strategy_spec(service, imported, study)
            published = service.publish_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                spec=spec,
            )
            strict_profile_id = next(
                item["assumption_profile_id"]
                for item in service.bounded_assumption_profiles()
                if item["mode"] == "STRICT_FAIL_CLOSED"
            )
            tampered = json.loads(json.dumps(published))
            tampered["profile_refs"]["assumption_profile_id"] = strict_profile_id
            service._publish_json(
                project["project_id"],
                "PRODUCT_STRATEGY_READ_MODEL",
                "v3.product-strategy-read-model/1.0.0",
                published["research_strategy_spec_id"],
                tampered,
            )

            with self.assertRaisesRegex(
                TruthPreconditionFailedError,
                "does not match its verified spec",
            ):
                ProductStrategyService(ProductRuntime(root)).get_strategy(
                    project_id=project["project_id"],
                    project_context_revision_id=imported["project_context_revision_id"],
                    research_strategy_spec_id=published["research_strategy_spec_id"],
                )


if __name__ == "__main__":
    unittest.main()
