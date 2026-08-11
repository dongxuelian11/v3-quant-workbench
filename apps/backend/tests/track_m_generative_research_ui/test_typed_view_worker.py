from __future__ import annotations

from copy import deepcopy
import unittest

from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from v3_backend.agents.contracts import PermissionLevel
from v3_backend.agents.permissions import PermissionDenied
from v3_backend.agents.generative_research_view import (
    MetricGroupBlock,
    PydanticResearchViewWorker,
    ResearchViewSpecV1,
)


EVIDENCE_ID = f"rwv_sha256_{'a' * 64}"


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "v3.generative_research_view/1.0.0",
        "spec_id": "track-m-function-fixture-001",
        "session_view_id": "session-a",
        "permission": "L1_DRAFT",
        "authority": "AGENT_DRAFT_PROPOSAL",
        "title": "Typed reward view",
        "blocks": [
            {
                "type": "MetricGroup",
                "block_id": "metric-001",
                "title": "Reward metrics",
                "data_authority": "CANONICAL_EVIDENCE",
                "evidence_ids": [EVIDENCE_ID],
                "metrics": [
                    {
                        "label": "IC",
                        "evidence_id": EVIDENCE_ID,
                        "selector": {"kind": "FACT", "label": "IC", "normalization": "NUMBER"},
                    }
                ],
            }
        ],
    }


def valid_model_response(_messages: list[object], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, valid_payload())])


class TypedResearchViewWorkerTests(unittest.TestCase):
    def test_pydantic_ai_returns_a_typed_l1_view_proposal(self) -> None:
        worker = PydanticResearchViewWorker(
            model=FunctionModel(valid_model_response, model_name="track-m-function-model"),
            permission=PermissionLevel.L1_DRAFT,
        )
        result = worker.run(
            prompt="Draft a bounded evidence view.",
            session_view_id="session-a",
            evidence_ids=(EVIDENCE_ID,),
            text_draft="Fallback text draft.",
        )
        self.assertEqual(result.status, "VALID")
        self.assertIsInstance(result.view_spec, ResearchViewSpecV1)
        self.assertIsInstance(result.view_spec.blocks[0], MetricGroupBlock)
        self.assertEqual(result.view_spec.permission, "L1_DRAFT")
        self.assertEqual(result.view_spec.authority, "AGENT_DRAFT_PROPOSAL")
        self.assertEqual(result.text_draft, "Fallback text draft.")

    def test_invalid_structured_output_fails_closed_and_preserves_text_draft(self) -> None:
        def invalid_response(_messages: list[object], info: AgentInfo) -> ModelResponse:
            response = valid_model_response(_messages, info)
            payload = deepcopy(response.parts[0].args)
            payload["blocks"][0]["metrics"][0]["value"] = "999"
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

        worker = PydanticResearchViewWorker(
            model=FunctionModel(invalid_response, model_name="track-m-invalid-function-model"),
            permission=PermissionLevel.L1_DRAFT,
        )
        result = worker.run(
            prompt="Attempt a raw replacement value.",
            session_view_id="session-a",
            evidence_ids=(EVIDENCE_ID,),
            text_draft="Keep this bounded text draft.",
        )
        self.assertEqual(result.status, "INVALID")
        self.assertIsNone(result.view_spec)
        self.assertEqual(result.error, "INVALID_STRUCTURED_RESEARCH_VIEW")
        self.assertEqual(result.text_draft, "Keep this bounded text draft.")

    def test_typed_schema_supports_exactly_the_seven_closed_block_types(self) -> None:
        selector = {"kind": "FACT", "label": "IC", "normalization": "NUMBER"}
        field_selector = {"kind": "EVIDENCE_FIELD", "field": "title", "normalization": "NONE"}
        common = {"evidence_ids": [EVIDENCE_ID]}
        payload = {
            "schema_version": "v3.generative_research_view/1.0.0",
            "spec_id": "track-m-all-blocks-001",
            "session_view_id": "session-a",
            "permission": "L1_DRAFT",
            "authority": "AGENT_DRAFT_PROPOSAL",
            "title": "All closed blocks",
            "blocks": [
                {"type": "Narrative", "block_id": "n", "title": "Narrative", "data_authority": "AGENT_DRAFT_DERIVED", **common, "text": "Bounded draft."},
                {"type": "MetricGroup", "block_id": "m", "title": "Metrics", "data_authority": "CANONICAL_EVIDENCE", **common, "metrics": [{"label": "IC", "evidence_id": EVIDENCE_ID, "selector": selector}]},
                {"type": "DataTable", "block_id": "d", "title": "Table", "data_authority": "CANONICAL_EVIDENCE", **common, "columns": [{"key": "title", "header": "Title", "selector": field_selector}], "rows": [{"evidence_id": EVIDENCE_ID}], "sort": None, "top_n": None},
                {"type": "TimeSeriesChart", "block_id": "t", "title": "Time", "data_authority": "CANONICAL_EVIDENCE", **common, "x_label": "Date", "y_label": "IC", "points": [{"evidence_id": EVIDENCE_ID, "x_selector": {"kind": "FACT", "label": "As of", "normalization": "ISO_DATE"}, "y_selector": selector}], "date_window": None},
                {"type": "BarChart", "block_id": "b", "title": "Bars", "data_authority": "CANONICAL_EVIDENCE", **common, "category_label": "Evidence", "value_label": "IC", "bars": [{"evidence_id": EVIDENCE_ID, "category_selector": field_selector, "value_selector": selector}], "sort": "INPUT", "top_n": None},
                {"type": "EvidenceList", "block_id": "e", "title": "Evidence", "data_authority": "CANONICAL_EVIDENCE", **common, "fields": [{"key": "title", "label": "Title", "selector": field_selector}]},
                {"type": "Callout", "block_id": "c", "title": "Boundary", "data_authority": "AGENT_DRAFT_DERIVED", **common, "tone": "WARNING", "text": "Validation remains NOT_RUN."},
            ],
        }
        spec = ResearchViewSpecV1.model_validate(payload)
        self.assertEqual(
            [block.type for block in spec.blocks],
            ["Narrative", "MetricGroup", "DataTable", "TimeSeriesChart", "BarChart", "EvidenceList", "Callout"],
        )

    def test_pydantic_schema_rejects_duplicate_block_identity(self) -> None:
        payload = valid_payload()
        payload["blocks"].append(deepcopy(payload["blocks"][0]))
        with self.assertRaisesRegex(ValidationError, "block_id values must be unique"):
            ResearchViewSpecV1.model_validate(payload)

    def test_pydantic_schema_matches_the_frozen_v0_structural_boundaries(self) -> None:
        from v3_backend.agents.generative_research_view.models import (
            BOUNDED_TEXT_MAX,
            EVIDENCE_ID_PATTERN,
            MAX_BAR_POINTS,
            MAX_BLOCKS,
            MAX_EVIDENCE_IDS_PER_BLOCK,
            MAX_EVIDENCE_LIST_FIELDS,
            MAX_METRICS,
            MAX_TABLE_COLUMNS,
            MAX_TABLE_ROWS,
            MAX_TIME_SERIES_POINTS,
            SHORT_TEXT_MAX,
        )

        self.assertEqual(
            (
                SHORT_TEXT_MAX,
                BOUNDED_TEXT_MAX,
                MAX_BLOCKS,
                MAX_EVIDENCE_IDS_PER_BLOCK,
                MAX_METRICS,
                MAX_TABLE_COLUMNS,
                MAX_TABLE_ROWS,
                MAX_TIME_SERIES_POINTS,
                MAX_BAR_POINTS,
                MAX_EVIDENCE_LIST_FIELDS,
                EVIDENCE_ID_PATTERN,
            ),
            (256, 4096, 64, 128, 32, 20, 500, 200, 100, 10, r"^[a-z][a-z0-9_]*_sha256_[0-9a-f]{64}$"),
        )

        evidence_ids = tuple(
            f"rwv_{index}_sha256_{index:064x}" for index in range(MAX_EVIDENCE_IDS_PER_BLOCK + 1)
        )
        narrative = {
            "type": "Narrative",
            "block_id": "narrative-boundary",
            "title": "Narrative boundary",
            "data_authority": "AGENT_DRAFT_DERIVED",
            "evidence_ids": list(evidence_ids[:MAX_EVIDENCE_IDS_PER_BLOCK]),
            "text": "n" * BOUNDED_TEXT_MAX,
        }
        payload = valid_payload()
        payload.update({"title": "s" * SHORT_TEXT_MAX, "blocks": [narrative]})
        ResearchViewSpecV1.model_validate(payload)

        callout = {
            "type": "Callout",
            "block_id": "callout-boundary",
            "title": "Callout boundary",
            "data_authority": "AGENT_DRAFT_DERIVED",
            "evidence_ids": [EVIDENCE_ID],
            "tone": "INFO",
            "text": "c" * BOUNDED_TEXT_MAX,
        }
        ResearchViewSpecV1.model_validate({**valid_payload(), "blocks": [callout]})

        invalid_cases = [
            {**payload, "title": "s" * (SHORT_TEXT_MAX + 1)},
            {**payload, "blocks": [{**narrative, "text": "n" * (BOUNDED_TEXT_MAX + 1)}]},
            {**payload, "blocks": [{**narrative, "evidence_ids": list(evidence_ids)}]},
            {**payload, "blocks": [{**narrative, "evidence_ids": [evidence_ids[0], evidence_ids[0]]}]},
            {**payload, "blocks": [{**narrative, "evidence_ids": [f"MALFORMED_sha256_{'a' * 64}"]}]},
            {**payload, "blocks": [{**callout, "text": "c" * (BOUNDED_TEXT_MAX + 1)}]},
        ]
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    ResearchViewSpecV1.model_validate(invalid)

        blocks = [{**narrative, "block_id": f"block-{index}", "evidence_ids": [EVIDENCE_ID]} for index in range(MAX_BLOCKS)]
        ResearchViewSpecV1.model_validate({**valid_payload(), "blocks": blocks})
        with self.assertRaises(ValidationError):
            ResearchViewSpecV1.model_validate({**valid_payload(), "blocks": blocks + [{**narrative, "block_id": "block-overflow", "evidence_ids": [EVIDENCE_ID]}]})

    def test_pydantic_date_window_uses_strict_deterministic_iso_semantics(self) -> None:
        time_series = {
            "type": "TimeSeriesChart",
            "block_id": "strict-window",
            "title": "Strict window",
            "data_authority": "CANONICAL_EVIDENCE",
            "evidence_ids": [EVIDENCE_ID],
            "x_label": "Date",
            "y_label": "IC",
            "points": [{
                "evidence_id": EVIDENCE_ID,
                "x_selector": {"kind": "FACT", "label": "As of", "normalization": "ISO_DATE"},
                "y_selector": {"kind": "FACT", "label": "IC", "normalization": "NUMBER"},
            }],
            "date_window": {"start": "2026-08-11", "end": "2026-08-12T00:00:00Z"},
        }
        ResearchViewSpecV1.model_validate({**valid_payload(), "blocks": [time_series]})
        ResearchViewSpecV1.model_validate({**valid_payload(), "blocks": [{**time_series, "date_window": {"start": "2026-08-11T09:00:00+08:00", "end": "2026-08-11T01:00:01Z"}}]})

        for date_window in (
            {"start": "2026-08-11T09:00:00", "end": "2026-08-12T00:00:00Z"},
            {"start": "Aug 11 2026", "end": "2026-08-12"},
            {"start": "2026-02-30", "end": "2026-08-12"},
            {"start": "2026-08-13", "end": "2026-08-12"},
        ):
            with self.subTest(date_window=date_window):
                with self.assertRaises(ValidationError):
                    ResearchViewSpecV1.model_validate({**valid_payload(), "blocks": [{**time_series, "date_window": date_window}]})

        percent_payload = valid_payload()
        percent_payload["blocks"][0]["metrics"][0]["selector"]["normalization"] = "PERCENT"
        with self.assertRaises(ValidationError):
            ResearchViewSpecV1.model_validate(percent_payload)

    def test_worker_denies_l2_execute_and_l3_publish(self) -> None:
        for permission in (PermissionLevel.L2_EXECUTE, PermissionLevel.L3_PUBLISH):
            worker = PydanticResearchViewWorker(
                model=FunctionModel(valid_model_response, model_name="track-m-denied-function-model"),
                permission=permission,
            )
            with self.assertRaises(PermissionDenied):
                worker.run(
                    prompt="Escalate authority.",
                    session_view_id="session-a",
                    evidence_ids=(EVIDENCE_ID,),
                )


if __name__ == "__main__":
    unittest.main()
