from __future__ import annotations

import dataclasses
import inspect
import json
import sqlite3
import unittest

from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.domain.research_pipeline import (
    ResearchPipelineRequest,
    ResearchPipelineStatus,
)

from .helpers import build_pipeline_development_fixture, research_artifact_policy


class CoreResearchPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_pipeline_development_fixture()
        self.addCleanup(self.fixture.close)

    def test_complete_owner_connected_research_chain_publishes_readable_result(self) -> None:
        result = self.fixture.service.run(self.fixture.request)
        self.assertEqual(result.status, ResearchPipelineStatus.SUCCESS, result.to_wire())
        self.assertEqual(
            result.completed_stages,
            (
                "STRATEGY",
                "PORTFOLIO",
                "TARGET_WEIGHT",
                "RISK",
                "RISK_ADJUSTED_WEIGHT",
                "BACKTEST",
                "RESULT",
            ),
        )
        for identity in (
            result.strategy_output_id,
            result.portfolio_intent_id,
            result.target_weight_vector_id,
            result.risk_application_receipt_id,
            result.risk_adjusted_weight_vector_id,
            result.backtest_result_id,
            result.run_id,
            result.run_receipt_id,
            result.result_artifact_id,
        ):
            self.assertIsNotNone(identity)
        self.assertTrue(result.result_artifact_readable)

        restarted = FileSystemArtifactStore(
            self.fixture.artifact_root,
            policy=research_artifact_policy(),
        )
        payload = json.loads(restarted.read_bytes(result.result_artifact_id))
        self.assertEqual(
            payload["backtest_result"]["result_id"], result.backtest_result_id
        )
        self.assertEqual(payload["run_receipt"]["run_id"], result.run_id)
        self.assertFalse(payload["research_classification"]["formal_market_truth"])
        self.assertEqual(
            payload["research_classification"]["truth_admission"],
            {
                "canonical_truth_state": "NOT_FORMAL",
                "canonical_admission_state": "PRE_ALPHA",
            },
        )
        self.assertEqual(
            payload["research_classification"]["labels"],
            ["RESEARCH_ONLY", "APPROXIMATE"],
        )
        self.assertEqual(
            payload["assumption_profile"]["profile_id"], "RESEARCH_FREE_DATA_V1"
        )
        self.assertEqual(
            payload["assumption_profile"]["semantics"],
            "explicit research assumptions; not market truth",
        )

        connection = sqlite3.connect(self.fixture.database_path)
        try:
            counts = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "target_weight_vector_publication",
                    "risk_policy_set_publication",
                    "risk_application_receipt_publication",
                    "risk_adjusted_weight_vector_publication",
                )
            )
        finally:
            connection.close()
        self.assertEqual(counts, (1, 1, 1, 1))

    def test_normal_strategy_failure_reports_exact_stage_without_downstream_writes(self) -> None:
        input_request = self.fixture.request.strategy_request.inputs[0]
        bad_strategy_request = dataclasses.replace(
            self.fixture.request.strategy_request,
            inputs=(dataclasses.replace(input_request, owner_id="sgv_missing"),),
        )
        result = self.fixture.service.run(
            dataclasses.replace(
                self.fixture.request,
                strategy_request=bad_strategy_request,
            )
        )
        self.assertEqual(result.status, ResearchPipelineStatus.STRATEGY_FAILED)
        self.assertEqual(result.failed_stage, "STRATEGY")
        self.assertEqual(result.completed_stages, ())
        self.assertIsNone(result.target_weight_vector_id)
        self.assertIsNone(result.result_artifact_id)

    def test_request_boundary_accepts_no_caller_built_downstream_numeric_objects(self) -> None:
        fields = set(inspect.signature(ResearchPipelineRequest).parameters)
        self.assertFalse(
            fields.intersection(
                {
                    "portfolio_intent",
                    "target_weight_vector",
                    "risk_adjusted_weight_vector",
                    "adjusted_weights",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
