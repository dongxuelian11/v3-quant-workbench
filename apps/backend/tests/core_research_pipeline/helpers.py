"""Explicit bounded development fixture for the repo-native research smoke."""

from __future__ import annotations

import sqlite3
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from apps.backend.tests.systemic_a2_strategy_signal_payload.test_formal_strategy_payload import (
    FormalFixture,
)
from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.sqlite.portfolio_risk_owner import SQLitePortfolioRiskPolicyOwner
from v3_backend.adapters.sqlite.risk_application import SQLiteRiskApplicationRepository
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.artifacts.policy import ADMITTED, FormatRule, SafeFormatPolicy
from v3_backend.domain.backtest_runtime import (
    AshareTradingRuleProfileVersion,
    Board,
    BoardTradingRule,
    ExecutionTimingProfileVersion,
    cn_a_share_2023_08_28_cost_policy,
)
from v3_backend.domain.portfolio_construction import (
    CanonicalPortfolioOwnerService,
    ConstructionMethod,
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.research_pipeline import (
    RESEARCH_BACKTEST_RESULT_ROLE,
    CoreResearchPipelineService,
    ResearchBarObservation,
    ResearchExecutionAssumptionProfile,
    ResearchPipelineRequest,
    ResearchSessionObservation,
)
from v3_backend.domain.risk_runtime import (
    CanonicalRiskApplicationService,
    CanonicalRiskPolicyAuthoringService,
    MaxSingleNamePolicyInput,
)
from v3_backend.domain.strategies import (
    FormalStrategyEvaluationService,
    SCORE_PAYLOAD_ROLE,
    SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
)
from v3_backend.domain.weights import RuntimeIdentity


PUBLISHED_AT = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)


def research_artifact_policy() -> SafeFormatPolicy:
    return SafeFormatPolicy(
        (
            FormatRule(
                SCORE_PAYLOAD_ROLE,
                "application/json",
                ADMITTED,
                "canonical-json-v1",
                "bounded development score fixture resolved through P1 bytes",
            ),
            FormatRule(
                RESEARCH_BACKTEST_RESULT_ROLE,
                "application/json",
                ADMITTED,
                "canonical-json-v1",
                "PRE_ALPHA research result envelope with explicit assumptions",
            ),
        )
    )


def _board(instrument_id: str) -> Board:
    if instrument_id.endswith(".SH"):
        return Board.SSE_MAIN
    if instrument_id.endswith(".BJ"):
        return Board.BSE
    return Board.SZSE_MAIN


def _rule_profile() -> AshareTradingRuleProfileVersion:
    return AshareTradingRuleProfileVersion.create(
        profile_name="RESEARCH_FIXTURE_CN_A_SHARE_RULES_V1",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        settlement_days=1,
        board_rules=(
            BoardTradingRule(Board.SSE_MAIN, 100, 100, "0.10", "0.10"),
            BoardTradingRule(Board.SSE_STAR, 200, 1, "0.20", "0.20"),
            BoardTradingRule(Board.SZSE_MAIN, 100, 100, "0.10", "0.10"),
            BoardTradingRule(Board.SZSE_CHINEXT, 100, 100, "0.20", "0.20"),
            BoardTradingRule(Board.BSE, 100, 1, "0.30", "0.30"),
        ),
        truth_admission=PRE_ALPHA_CEILING,
    )


def _timing_profile() -> ExecutionTimingProfileVersion:
    return ExecutionTimingProfileVersion.create(
        profile_name="RESEARCH_FIXTURE_RAW_OPEN_V1",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        market_timezone="Asia/Shanghai",
        raw_open_eligibility_cutoff_local_time="09:15:00",
        raw_open_execution_local_time="09:25:00",
        truth_admission=PRE_ALPHA_CEILING,
    )


@dataclass(slots=True)
class PipelineDevelopmentFixture:
    formal: FormalFixture
    artifact_root: Path
    artifact_store: FileSystemArtifactStore
    request: ResearchPipelineRequest
    service: CoreResearchPipelineService
    database_path: Path

    def close(self) -> None:
        self.formal.close()


def build_pipeline_development_fixture() -> PipelineDevelopmentFixture:
    formal = FormalFixture(unittest.TestCase())
    artifact_root = Path(formal.temporary.name) / "artifacts"
    policy = research_artifact_policy()
    store = FileSystemArtifactStore(artifact_root, policy=policy)
    staged = store.stage_bytes(formal.payload)
    publication = store.publish(
        staged.staging_token,
        expected_sha256=staged.sha256,
        expected_byte_size=staged.byte_size,
        media_type="application/json",
        role=SCORE_PAYLOAD_ROLE,
        provenance_entity_id="prv_research_pipeline_score_fixture",
        schema_fingerprint=SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
        semantic_fingerprint=formal.context_identity,
        published_at=PUBLISHED_AT,
    )
    if publication.descriptor.artifact_id != formal.artifact_id:
        raise AssertionError("development score fixture artifact identity drifted")
    formal.service = FormalStrategyEvaluationService(
        repositories=formal.repositories,
        byte_reader=store,
    )

    project_context_revision_id = "pcr_research_pipeline"
    connection = sqlite3.connect(formal.database_path)
    try:
        connection.execute(
            """
            INSERT INTO project_context_revision(
              project_context_revision_id,project_id,revision_no,context_json,
              canonical_hash,created_by,created_at
            ) VALUES(?,?,1,'{}',?,'research-pipeline-smoke',?)
            """,
            (
                project_context_revision_id,
                "prj_a2",
                "7" * 64,
                PUBLISHED_AT.isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    runtime = RuntimeIdentity(
        code_version="git:research-pipeline-smoke",
        runtime_profile_id="v3.research-pipeline-development/1.0.0",
        environment_fingerprint="cpython-3.14-bounded-development-fixture",
    )
    construction_spec = PortfolioConstructionSpecVersion.create(
        method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
        method_version="1.0.0",
        target_cash_weight="0.1",
        max_instrument_weight="0.45",
        runtime_identity=runtime,
    )
    upstream_owner = SQLitePortfolioRiskPolicyOwner(formal.database_path, artifact_root)
    risk_repository = SQLiteRiskApplicationRepository(formal.database_path, artifact_root)
    policy_result = CanonicalRiskPolicyAuthoringService(
        upstream_owner
    ).author_and_publish(
        project_id="prj_a2",
        project_context_revision_id=project_context_revision_id,
        definitions=(MaxSingleNamePolicyInput("0.45"),),
        runtime_identity=runtime,
        published_at=PUBLISHED_AT,
    )

    instruments = tuple(sorted(formal.binding.universe.instrument_ids))
    sessions = tuple(
        ResearchSessionObservation(
            session_date=session_date,
            is_open=True,
            bars=tuple(
                ResearchBarObservation(
                    instrument_id=instrument_id,
                    board=_board(instrument_id),
                    raw_open=str(10 + index + day_offset),
                    raw_close=str(10 + index + day_offset) + ".5",
                )
                for index, instrument_id in enumerate(instruments)
            ),
        )
        for day_offset, session_date in enumerate((date(2026, 1, 6), date(2026, 1, 7)))
    )
    request = ResearchPipelineRequest(
        project_id="prj_a2",
        project_context_revision_id=project_context_revision_id,
        strategy_request=formal.request,
        construction_spec=construction_spec,
        risk_policy_set_version_id=policy_result.policy_set.risk_policy_set_version_id,
        runtime_identity=runtime,
        base_currency="CNY",
        as_of=datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
        decision_time=datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc),
        rebalance_time=datetime(2026, 1, 6, 0, 30, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 7, 8, 0, tzinfo=timezone.utc),
        published_at=PUBLISHED_AT,
        assumption_profile=ResearchExecutionAssumptionProfile.free_data_v1(),
        observations=sessions,
        initial_cash="100000",
        initial_holdings=(),
        rule_profile=_rule_profile(),
        cost_policy=cn_a_share_2023_08_28_cost_policy(
            commission_rate="0.0003",
            minimum_commission="5",
        ),
        execution_timing_profile=_timing_profile(),
    )
    service = CoreResearchPipelineService(
        strategy=formal.service,
        portfolio=CanonicalPortfolioOwnerService(upstream_owner),
        risk=CanonicalRiskApplicationService(risk_repository),
        adjusted_weight_owner=risk_repository,
        result_artifact_store=store,
    )
    return PipelineDevelopmentFixture(
        formal=formal,
        artifact_root=artifact_root,
        artifact_store=store,
        request=request,
        service=service,
        database_path=formal.database_path,
    )


__all__ = [
    "PipelineDevelopmentFixture",
    "build_pipeline_development_fixture",
    "research_artifact_policy",
]
