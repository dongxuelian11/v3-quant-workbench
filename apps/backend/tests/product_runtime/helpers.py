"""B3 product runtime test setup.

Test-setup only: prepares canonical source data and owners inside a product
storage root (catalog + content-addressed artifact store) through the accepted
canonical owners.  The runtime business path then executes exclusively through
frozen ASL operations over these durable records.  No numeric truth is minted
here that the runtime path would consume as a shortcut: the runtime re-resolves
and re-verifies every canonical ref it executes.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from apps.backend.tests.systemic_a2_strategy_signal_payload.test_formal_strategy_payload import (
    FormalFixture,
)
from v3_backend.adapters.sqlite.portfolio_risk_owner import SQLitePortfolioRiskPolicyOwner
from v3_backend.adapters.sqlite.risk_application import SQLiteRiskApplicationRepository
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
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
    CoreResearchPipelineService,
    ResearchBacktestAssembler,
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
    SCORE_PAYLOAD_ROLE,
    SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
    FormalStrategyEvaluationService,
)
from v3_backend.domain.weights import RuntimeIdentity
from v3_backend.provenance.canonical_hash import canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode
from v3_backend.runtime.product_runtime import (
    ProductRuntime,
    mint_v3_id,
    mint_uuid7,
)

SETUP_PUBLISHED_AT = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)
SETUP_NOW = "2026-01-05T15:00:00Z"
RESEARCH_RUNTIME_IDENTITY = RuntimeIdentity(
    code_version="git:b3-product-setup",
    runtime_profile_id="v3.product-research-setup/1.0.0",
    environment_fingerprint="cpython-3.14-product-smoke",
)


def research_board(instrument_id: str) -> Board:
    if instrument_id.endswith(".SH"):
        return Board.SSE_MAIN
    if instrument_id.endswith(".BJ"):
        return Board.BSE
    return Board.SZSE_MAIN


def research_rule_profile() -> AshareTradingRuleProfileVersion:
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


def research_timing_profile() -> ExecutionTimingProfileVersion:
    return ExecutionTimingProfileVersion.create(
        profile_name="RESEARCH_FIXTURE_RAW_OPEN_V1",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        market_timezone="Asia/Shanghai",
        raw_open_eligibility_cutoff_local_time="09:15:00",
        raw_open_execution_local_time="09:25:00",
        truth_admission=PRE_ALPHA_CEILING,
    )


def research_cost_policy():
    return cn_a_share_2023_08_28_cost_policy(
        commission_rate="0.0003",
        minimum_commission="5",
    )


def build_research_observations(instrument_ids: tuple[str, ...]):
    """Bounded research free-data source inputs (explicit test setup only)."""
    return tuple(
        ResearchSessionObservation(
            session_date=session_date,
            is_open=True,
            bars=tuple(
                ResearchBarObservation(
                    instrument_id=instrument_id,
                    board=research_board(instrument_id),
                    raw_open=str(10 + index + day_offset),
                    raw_close=str(10 + index + day_offset) + ".5",
                )
                for index, instrument_id in enumerate(instrument_ids)
            ),
        )
        for day_offset, session_date in enumerate((date(2026, 1, 6), date(2026, 1, 7)))
    )


@dataclass(slots=True)
class GoldenProductSetup:
    product: ProductRuntime
    project_id: str
    project_context_revision_id: str
    run_spec_id: str
    run_spec_artifact_id: str
    context_artifact_id: str
    session_id: str
    pipeline_result: object
    spec_wire_sha256: str


def build_product_golden_project(storage_root: Path) -> GoldenProductSetup:
    """Prepare the canonical golden project inside one product storage root."""
    product = ProductRuntime(storage_root)
    formal = FormalFixture(unittest.TestCase())
    try:
        setup = _seed_and_assemble(product, formal)
        return setup
    finally:
        formal.close()


def _seed_and_assemble(product: ProductRuntime, formal: FormalFixture) -> GoldenProductSetup:
    project_id = mint_v3_id("prj_")
    project_context_revision_id = mint_v3_id("pcr_")
    session_id = mint_uuid7()
    published_at = SETUP_PUBLISHED_AT

    # 1. Score payload bytes + descriptor into the product store/catalog.
    staged = product.artifact_store.stage_bytes(formal.payload)
    score_publication = product.artifact_store.publish(
        staged.staging_token,
        expected_sha256=staged.sha256,
        expected_byte_size=staged.byte_size,
        media_type="application/json",
        role=SCORE_PAYLOAD_ROLE,
        provenance_entity_id="prv_b3_score_payload",
        schema_fingerprint=SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
        semantic_fingerprint=formal.context_identity,
        published_at=published_at,
    )
    if score_publication.descriptor.artifact_id != formal.artifact_id:
        raise AssertionError("score payload artifact identity drifted")

    # 2. Catalog rows required by the strategy payload resolution path.
    membership_artifact_id = formal.binding.universe.membership_artifact_id
    membership_sha256 = formal.binding.universe.membership_sha256
    connection = connect_catalog(product.database_path)
    uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
    try:
        uow.begin()
        repositories = SQLiteRepositoryRegistry(uow)
        repositories.artifact.declare_staged(
            {
                "artifact_id": formal.artifact_id,
                "sha256": formal.sha256,
                "byte_size": len(formal.payload),
                "media_type": "application/json",
                "semantic_role": SCORE_PAYLOAD_ROLE,
                "storage_key": formal.sha256,
                "schema_fingerprint": SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
                "state": "STAGED",
                "created_at": SETUP_NOW,
            }
        )
        repositories.artifact.publish_verified(
            formal.artifact_id, sha256=formal.sha256, published_at=SETUP_NOW
        )
        repositories.artifact.declare_staged(
            {
                "artifact_id": membership_artifact_id,
                "sha256": membership_sha256,
                "byte_size": 0,
                "media_type": "application/json",
                "semantic_role": "UNIVERSE_MEMBERSHIP",
                "storage_key": membership_sha256,
                "schema_fingerprint": None,
                "state": "STAGED",
                "created_at": SETUP_NOW,
            }
        )
        repositories.artifact.publish_verified(
            membership_artifact_id, sha256=membership_sha256, published_at=SETUP_NOW
        )
        repositories.project.add_new(
            {
                "project_id": project_id,
                "display_name": "B3 Golden Product Project",
                "created_at": SETUP_NOW,
                "state": "ACTIVE",
            }
        )
        repositories.connector.table("connector").add_new(
            {
                "connector_id": "con_b3",
                "stable_name": "b3-product-setup",
                "publisher": "V3",
                "state": "REGISTERED",
                "created_at": SETUP_NOW,
            }
        )
        repositories.connector.table("connector_version").add_new(
            {
                "connector_version_id": "cov_b3",
                "connector_id": "con_b3",
                "semantic_version": "1.0.0",
                "bundle_artifact_id": formal.artifact_id,
                "bundle_sha256": formal.sha256,
                "entrypoint": "b3:owner",
                "declared_manifest_json": {},
                "network_policy": "DENY",
                "state": "ADMITTED",
                "created_at": SETUP_NOW,
            }
        )
        repositories.snapshot.table("data_snapshot").add_new(
            {
                "snapshot_id": formal.base.dataset.binding.snapshot_id,
                "connector_version_id": "cov_b3",
                "manifest_artifact_id": formal.artifact_id,
                "content_hash": formal.binding.snapshot.content_sha256,
                "normalization_spec_version": "1.0.0",
                "truth_profile_id": "formal-a2",
                "state": "PUBLISHED",
                "created_at": SETUP_NOW,
                "published_at": SETUP_NOW,
            }
        )
        repositories.universe.table("universe_definition").add_new(
            {
                "universe_definition_id": "und_b3",
                "project_id": project_id,
                "constructor_kind": "WATCHLIST",
                "definition_json": {},
                "canonical_hash": "1" * 64,
                "state": "PUBLISHED",
                "created_at": SETUP_NOW,
            }
        )
        repositories.universe.table("universe_version").add_new(
            {
                "universe_version_id": formal.base.dataset.binding.universe_version_id,
                "universe_definition_id": "und_b3",
                "snapshot_id": formal.base.dataset.binding.snapshot_id,
                "knowledge_cutoff": SETUP_NOW,
                "membership_artifact_id": membership_artifact_id,
                "audit_artifact_id": membership_artifact_id,
                "content_hash": "2" * 64,
                "state": "PUBLISHED",
                "published_at": SETUP_NOW,
            }
        )
        repositories.dataset.table("dataset_spec").add_new(
            {
                "dataset_spec_id": "dss_b3",
                "project_id": project_id,
                "spec_json": {},
                "canonical_hash": "3" * 64,
                "split_kind": "CHRONOLOGICAL",
                "preprocessing_fit_scope": "TRAIN_ONLY",
                "state": "VALIDATED",
                "created_at": SETUP_NOW,
            }
        )
        repositories.dataset.table("dataset_version").add_new(
            {
                "dataset_version_id": formal.base.dataset.dataset_version_id,
                "dataset_spec_id": "dss_b3",
                "snapshot_id": formal.base.dataset.binding.snapshot_id,
                "universe_version_id": formal.base.dataset.binding.universe_version_id,
                "manifest_artifact_id": formal.artifact_id,
                "leakage_audit_artifact_id": formal.artifact_id,
                "content_hash": "4" * 64,
                "state": "PUBLISHED",
                "published_at": SETUP_NOW,
            }
        )
        repositories.model.table("model_spec").add_new(
            {
                "model_spec_id": "mds_b3",
                "project_id": project_id,
                "model_family": "LINEAR",
                "spec_json": {},
                "environment_profile_id": "env_b3",
                "canonical_hash": "5" * 64,
                "state": "VALIDATED",
                "created_at": SETUP_NOW,
            }
        )
        repositories.model.table("model_version").add_new(
            {
                "model_version_id": "mdv_b3",
                "model_spec_id": "mds_b3",
                "dataset_version_id": formal.base.dataset.dataset_version_id,
                "run_id": "run_b3_setup",
                "model_artifact_id": formal.artifact_id,
                "metrics_artifact_id": formal.artifact_id,
                "content_hash": "6" * 64,
                "safe_format_id": "canonical-json-v1",
                "state": "PUBLISHED",
                "published_at": SETUP_NOW,
            }
        )
        repositories.model.table("prediction_signal_version").add_new(
            {
                "prediction_signal_version_id": formal.source_id,
                "model_version_id": "mdv_b3",
                "dataset_version_id": formal.base.dataset.dataset_version_id,
                "signal_artifact_id": formal.artifact_id,
                "content_hash": formal.sha256,
                "state": "PUBLISHED",
                "published_at": SETUP_NOW,
            }
        )
        repositories.project.append_revision(
            {
                "project_context_revision_id": project_context_revision_id,
                "project_id": project_id,
                "context_json": "{}",
                "canonical_hash": canonical_sha256("{}"),
                "created_by": "b3-product-setup",
                "created_at": SETUP_NOW,
            },
            base_revision_id=None,
        )
        uow.commit()
    finally:
        if uow.active:
            uow.rollback()
        connection.close()

    # 3. Canonical owner chain over the product stores (assembly).
    upstream_owner = SQLitePortfolioRiskPolicyOwner(product.database_path, product.artifact_root)
    risk_repository = SQLiteRiskApplicationRepository(product.database_path, product.artifact_root)
    policy_result = CanonicalRiskPolicyAuthoringService(upstream_owner).author_and_publish(
        project_id=project_id,
        project_context_revision_id=project_context_revision_id,
        definitions=(MaxSingleNamePolicyInput("0.45"),),
        runtime_identity=RESEARCH_RUNTIME_IDENTITY,
        published_at=published_at,
    )
    construction_spec = PortfolioConstructionSpecVersion.create(
        method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
        method_version="1.0.0",
        target_cash_weight="0.1",
        max_instrument_weight="0.45",
        runtime_identity=RESEARCH_RUNTIME_IDENTITY,
    )
    instruments = tuple(sorted(formal.binding.universe.instrument_ids))
    sessions = build_research_observations(instruments)
    request = ResearchPipelineRequest(
        project_id=project_id,
        project_context_revision_id=project_context_revision_id,
        strategy_request=formal.request,
        construction_spec=construction_spec,
        risk_policy_set_version_id=policy_result.policy_set.risk_policy_set_version_id,
        runtime_identity=RESEARCH_RUNTIME_IDENTITY,
        base_currency="CNY",
        as_of=datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
        decision_time=datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc),
        rebalance_time=datetime(2026, 1, 6, 0, 30, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 7, 8, 0, tzinfo=timezone.utc),
        published_at=published_at,
        assumption_profile=ResearchExecutionAssumptionProfile.free_data_v1(),
        observations=sessions,
        initial_cash="100000",
        initial_holdings=(),
        rule_profile=research_rule_profile(),
        cost_policy=research_cost_policy(),
        execution_timing_profile=research_timing_profile(),
    )
    read_connection = connect_catalog(product.database_path, read_only=True)
    read_uow = SQLiteUnitOfWork(read_connection, TransactionMode.READ_ONLY)
    read_uow.begin()
    repositories = SQLiteRepositoryRegistry(read_uow)
    formal_service = FormalStrategyEvaluationService(
        repositories=repositories,
        byte_reader=product.artifact_store,
    )
    pipeline = CoreResearchPipelineService(
        strategy=formal_service,
        portfolio=CanonicalPortfolioOwnerService(upstream_owner),
        risk=CanonicalRiskApplicationService(risk_repository),
        adjusted_weight_owner=risk_repository,
        result_artifact_store=product.artifact_store,
    )
    pipeline_result = pipeline.run(request)
    read_uow.rollback()
    read_connection.close()
    if not pipeline_result.succeeded:
        raise AssertionError(
            f"pipeline setup failed: {pipeline_result.status} {pipeline_result.error_message}"
        )

    # 4. Assemble the canonical run spec and persist it through the product
    #    composition (spec wire + execution context artifacts, project-owned).
    adjusted = risk_repository.require_adjusted_weight_vector(
        pipeline_result.risk_adjusted_weight_vector_id
    )
    spec = ResearchBacktestAssembler().assemble(
        request=request, adjusted_weights=adjusted
    )
    run_spec_id, context_artifact_id = product.spec_codec.persist(
        spec=spec,
        rule_profile=research_rule_profile(),
        cost_policy=research_cost_policy(),
        timing_profile=research_timing_profile(),
        project_id=project_id,
        project_context_revision_id=project_context_revision_id,
        published_at=published_at,
    )
    return GoldenProductSetup(
        product=product,
        project_id=project_id,
        project_context_revision_id=project_context_revision_id,
        run_spec_id=run_spec_id,
        run_spec_artifact_id=None,
        context_artifact_id=context_artifact_id,
        session_id=session_id,
        pipeline_result=pipeline_result,
        spec_wire_sha256=spec.content_sha256,
    )


__all__ = [
    "GoldenProductSetup",
    "build_product_golden_project",
    "build_research_observations",
]
