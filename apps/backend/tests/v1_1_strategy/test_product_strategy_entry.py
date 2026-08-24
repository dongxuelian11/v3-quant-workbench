from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from v3_backend.contracts.registry import OPERATIONS
from v3_backend.domain.tasks.entities import TASK_TERMINAL_STATES
from v3_backend.runtime.product_facades import build_product_facades
from v3_backend.runtime.product_runtime import ProductRuntime, mint_uuid7
from v3_backend.runtime.product_strategy import ProductStrategyService
from v3_backend.runtime.product_workers import ProductResearchWorkerConfig
from v3_backend.runtime.request_router import RequestRouter

from .test_product_strategy_authoring import _strategy_case, _strategy_spec


_OPERATION = "ProductEntryService.v1.publishResearchStrategy"
_PREVIEW_OPERATION = "ProductEntryService.v1.previewResearchStrategy"


def _handlers(product: ProductRuntime):
    return {
        operation_id: handler
        for facade in build_product_facades(product)
        for operation_id, handler in facade.handlers().items()
    }


class ProductStrategyEntryAcceptanceTests(unittest.TestCase):
    def test_preview_is_side_effect_free_and_matches_subsequent_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-preview-") as directory:
            product, project, imported, study, service = _strategy_case(Path(directory))
            spec = _strategy_spec(service, imported, study)
            connection = product._connection(read_only=True)
            try:
                before = {
                    table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in (
                        "task",
                        "run",
                        "task_attempt",
                        "artifact",
                        "artifact_reference",
                        "publication_intent",
                        "strategy_version",
                    )
                }
            finally:
                connection.close()

            request_id = mint_uuid7()
            body = {
                "request_id": request_id,
                "project_id": project["project_id"],
                "project_context_revision_id": imported[
                    "project_context_revision_id"
                ],
                "expected_api_version": "1.1",
                **{
                    key: value
                    for key, value in spec.to_wire().items()
                    if key not in {"schema_version", "research_strategy_spec_id"}
                },
            }
            response = RequestRouter(_handlers(product)).route(
                {
                    "kind": "request",
                    "request_id": request_id,
                    "operation_id": _PREVIEW_OPERATION,
                    "contract_version": "1.1",
                    "project_id": project["project_id"],
                    "project_context_revision_id": imported[
                        "project_context_revision_id"
                    ],
                    "body": body,
                }
            )
            self.assertEqual(response["status"], "OK", response)
            preview = response["body"]["read_model"]
            self.assertEqual(preview["side_effects"], "NONE")
            self.assertEqual(
                preview["research_strategy_spec_id"],
                spec.research_strategy_spec_id,
            )

            connection = product._connection(read_only=True)
            try:
                after = {
                    table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in before
                }
            finally:
                connection.close()
            self.assertEqual(after, before, "preview must not create Task, owner or Artifact rows")

            published = service.publish_strategy(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                spec=spec,
            )
            self.assertEqual(
                preview["strategy_definition_version_id"],
                published["strategy_definition_version_id"],
            )
            self.assertEqual(
                preview["transition_count"], published["decision_chain_count"]
            )
            self.assertEqual(
                preview["planned_decision_chain_count"],
                published["decision_chain_count"],
            )

    def test_contract_is_closed_and_carries_refs_not_numeric_owner_payloads(self) -> None:
        operation = OPERATIONS.get(_OPERATION)
        self.assertIsNotNone(operation)
        assert operation is not None
        self.assertEqual(operation.version, "1.1.0")
        properties = operation.request_type.SCHEMA["properties"]
        self.assertEqual(
            set(properties),
            {
                "request_id",
                "project_id",
                "project_context_revision_id",
                "expected_api_version",
                "idempotency_key",
                "universe_version_id",
                "entry_signal_factor_version_id",
                "exit_signal_factor_version_id",
                "position_sizing",
                "max_positions",
                "gross_exposure",
                "rebalance",
                "cost_policy_version_id",
                "execution_policy_version_id",
                "risk_policy_set_version_id",
                "initial_cash",
                "assumption_profile_id",
            },
        )
        self.assertTrue(
            {
                "bars",
                "factor_values",
                "target_weights",
                "signal_values",
                "portfolio",
                "risk_adjusted_weights",
            }.isdisjoint(properties)
        )

    def test_durable_task_precedes_isolated_strategy_publication_and_restarts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-strategy-entry-") as directory:
            root = Path(directory)
            _pre_product, project, imported, study, pre_service = _strategy_case(root)
            spec = _strategy_spec(pre_service, imported, study)
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=0.75
                ),
            )
            request_id = mint_uuid7()
            body = {
                "request_id": request_id,
                "project_id": project["project_id"],
                "project_context_revision_id": imported[
                    "project_context_revision_id"
                ],
                "expected_api_version": "1.1",
                "idempotency_key": "publish-golden-strategy-1",
                **{
                    key: value
                    for key, value in spec.to_wire().items()
                    if key not in {"schema_version", "research_strategy_spec_id"}
                },
            }
            router = RequestRouter(_handlers(product))
            started = time.monotonic()
            response = router.route(
                {
                    "kind": "request",
                    "request_id": request_id,
                    "operation_id": _OPERATION,
                    "contract_version": "1.1",
                    "project_id": project["project_id"],
                    "project_context_revision_id": imported[
                        "project_context_revision_id"
                    ],
                    "body": body,
                }
            )
            elapsed = time.monotonic() - started
            try:
                self.assertEqual(response["status"], "OK", response)
                accepted = response["body"]["read_model"]
                self.assertLess(elapsed, 2.0)
                self.assertEqual(accepted["accepted_state"], "QUEUED")
                self.assertEqual(accepted["truth"], "NOT_FORMAL")
                self.assertEqual(accepted["admission"], "PRE_ALPHA")
                self.assertEqual(
                    accepted["research_strategy_spec_id"],
                    spec.research_strategy_spec_id,
                )
                task = product.task_persistence.read_task(accepted["task_id"])
                self.assertEqual(task.operation_id, _OPERATION)
                self.assertEqual(
                    product.references(
                        project["project_id"], "PRODUCT_STRATEGY_READ_MODEL"
                    ),
                    [],
                    "durable Task must exist before Strategy publication starts",
                )

                replay_id = mint_uuid7()
                replay_body = {**body, "request_id": replay_id}
                replay = router.route(
                    {
                        "kind": "request",
                        "request_id": replay_id,
                        "operation_id": _OPERATION,
                        "contract_version": "1.1",
                        "project_id": project["project_id"],
                        "project_context_revision_id": imported[
                            "project_context_revision_id"
                        ],
                        "body": replay_body,
                    }
                )
                self.assertEqual(replay["status"], "OK", replay)
                self.assertEqual(
                    replay["body"]["read_model"]["task_id"], accepted["task_id"]
                )

                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    task = product.task_persistence.read_task(accepted["task_id"])
                    if task.state in TASK_TERMINAL_STATES:
                        break
                    time.sleep(0.05)
                self.assertEqual(task.state.value, "SUCCEEDED")
                restored = ProductStrategyService(ProductRuntime(root)).get_strategy(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_strategy_spec_id=accepted[
                        "research_strategy_spec_id"
                    ],
                )
                self.assertEqual(
                    restored["research_strategy_spec_id"],
                    accepted["research_strategy_spec_id"],
                )
                self.assertGreater(restored["decision_chain_count"], 0)
            finally:
                product.research_workers.shutdown_all()


if __name__ == "__main__":
    unittest.main()
