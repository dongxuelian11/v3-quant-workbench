"""Explicit DEVELOPMENT / INTEGRATION FIXTURE WS-E runtime.

This entrypoint is never selected by the production default. It constructs one
real canonical H -> I -> J chain and replays its read-only projection through
the same framed WS-E runtime used by production.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.backtest_runtime import (
    AshareTradingRuleProfileVersion,
    BacktestRunSpec,
    Board,
    BoardTradingRule,
    DailyMarketState,
    DeterministicAshareBacktestEngine,
    ExactInputReference,
    ExecutionTimingProfileVersion,
    InstrumentDefinition,
    MarketSession,
    ScheduledWeights,
    cn_a_share_2023_08_28_cost_policy,
)
from v3_backend.domain.risk_runtime import (
    RiskPolicyDefinition,
    RiskPolicySetVersion,
    apply_risk,
)
from v3_backend.domain.weights import RuntimeIdentity
from v3_backend.provenance.canonical_hash import canonical_sha256
from v3_backend.runtime.composition_root import RuntimePorts, build_runtime, default_capabilities
from v3_backend.runtime.framed_stdio import ProtocolViolation
from v3_backend.runtime.handshake import read_supervisor_token

from .projection import EvidenceSourceMode, build_round3_evidence_bundle


BACKEND_VERSION = "0.1.0-round3-integration-fixture"
TRANSPORT = "stdio-framed-v1"
PROJECT_ID = "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV"
SESSION_VIEW_ID = "session-view-round3-integration-001"


@dataclass(frozen=True)
class DevelopmentCanonicalChain:
    """Test-only references to the actual canonical H/I/J owner outputs."""

    portfolio_intent: Any
    portfolio_result: Any
    risk_result: Any
    backtest_run_spec: BacktestRunSpec
    backtest_run_result: Any


def _diagnostic(level: str, code: str, message: str) -> None:
    record: dict[str, Any] = {"level": level, "code": code, "message": message}
    sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
    sys.stderr.flush()


def _load_portfolio_fixture_type():
    tests_root = Path(__file__).resolve().parents[4] / "tests"
    tests_root_text = str(tests_root)
    if tests_root_text not in sys.path:
        sys.path.insert(0, tests_root_text)
    from track_h_portfolio_construction.test_portfolio_construction import (  # noqa: PLC0415
        PortfolioConstructionFixture,
    )

    return PortfolioConstructionFixture


def _board(instrument_id: str) -> Board:
    if instrument_id.endswith(".SZ"):
        return Board.SZSE_MAIN
    if instrument_id.endswith(".BJ"):
        return Board.BSE
    return Board.SSE_MAIN


def build_development_chain() -> DevelopmentCanonicalChain:
    fixture_type = _load_portfolio_fixture_type()
    fixture = fixture_type(methodName="runTest")
    fixture.setUp()
    portfolio_result = fixture.construct()

    risk_runtime = RuntimeIdentity(
        code_version="git:round3-integration-fixture",
        runtime_profile_id="v3.risk-runtime/1.0.0",
        environment_fingerprint="development-integration-fixture",
    )
    policy = RiskPolicyDefinition.pass_through(
        code_version=risk_runtime.code_version,
        runtime_profile_id=risk_runtime.runtime_profile_id,
    )
    risk_result = apply_risk(
        source_target=portfolio_result.target,
        policy_set=RiskPolicySetVersion.create((policy,)),
        runtime_identity=risk_runtime,
    )

    target = portfolio_result.target
    adjusted = risk_result.adjusted_weights
    # The canonical H fixture already carries an aware Asia/Shanghai rebalance
    # timestamp. Preserve its calendar date without consulting host tzdata.
    market_date = target.rebalance_time.date()
    instruments = tuple(
        InstrumentDefinition(instrument_id, _board(instrument_id))
        for instrument_id in target.source.universe_instrument_ids
    )
    session = MarketSession(
        market_date,
        True,
        tuple(
            DailyMarketState(instrument_id, "10", "10")
            for instrument_id in target.source.universe_instrument_ids
        ),
    )
    effective_from = date(2026, 1, 1)
    rule_profile = AshareTradingRuleProfileVersion.create(
        profile_name="ROUND3_INTEGRATION_FIXTURE_RULES_V1",
        effective_from=effective_from,
        effective_to=None,
        settlement_days=1,
        board_rules=(
            BoardTradingRule(Board.SSE_MAIN, 100, 100, "0.10", "0.10"),
            BoardTradingRule(Board.SSE_STAR, 200, 1, "0.20", "0.20"),
            BoardTradingRule(Board.SZSE_MAIN, 100, 100, "0.10", "0.10"),
            BoardTradingRule(Board.SZSE_CHINEXT, 100, 100, "0.20", "0.20"),
            BoardTradingRule(Board.BSE, 100, 1, "0.30", "0.30"),
        ),
    )
    timing_profile = ExecutionTimingProfileVersion.create(
        profile_name="ROUND3_INTEGRATION_FIXTURE_RAW_OPEN_V1",
        effective_from=effective_from,
        effective_to=None,
        market_timezone="Asia/Shanghai",
        raw_open_eligibility_cutoff_local_time="09:15:00",
        raw_open_execution_local_time="09:25:00",
    )
    reference_kinds = (
        "SNAPSHOT",
        "MARKET_DATA",
        "TRADING_CALENDAR",
        "UNIVERSE",
        "CORPORATE_ACTIONS",
        "OFFICIAL_TRADING_HOURS",
        "OFFICIAL_COST_RULES",
    )
    exact_references = tuple(
        ExactInputReference(
            kind,
            "round3-integration-fixture-" + kind.lower(),
            canonical_sha256({"kind": kind, "fixture": "round3-integration-closure-01"}),
            PRE_ALPHA_CEILING,
        )
        for kind in reference_kinds
    )
    run_spec = BacktestRunSpec.create(
        initial_cash="100000",
        initial_holdings=(),
        instruments=instruments,
        sessions=(session,),
        schedule=(ScheduledWeights(target.rebalance_time, adjusted),),
        rule_profile=rule_profile,
        cost_policy=cn_a_share_2023_08_28_cost_policy(
            commission_rate="0.0003",
            minimum_commission="5",
        ),
        execution_timing_profile=timing_profile,
        exact_references=exact_references,
        runtime_identity=RuntimeIdentity(
            code_version="git:round3-integration-fixture",
            runtime_profile_id="v3.a-share-backtest-runtime/1.0.0",
            environment_fingerprint="development-integration-fixture",
        ),
    )
    run_result = DeterministicAshareBacktestEngine().run(run_spec)
    return DevelopmentCanonicalChain(
        portfolio_intent=fixture.intent,
        portfolio_result=portfolio_result,
        risk_result=risk_result,
        backtest_run_spec=run_spec,
        backtest_run_result=run_result,
    )


def build_development_bundle():
    chain = build_development_chain()
    return build_round3_evidence_bundle(
        session_view_id=SESSION_VIEW_ID,
        source_mode=EvidenceSourceMode.DEVELOPMENT_INTEGRATION_FIXTURE,
        portfolio_intent=chain.portfolio_intent,
        portfolio_result=chain.portfolio_result,
        risk_result=chain.risk_result,
        backtest_run_spec=chain.backtest_run_spec,
        backtest_run_result=chain.backtest_run_result,
    )


class _SingleBundleReplay:
    def __init__(self) -> None:
        self._event = {
            "event_id": "round3-integration-fixture-evidence-001",
            "project_id": PROJECT_ID,
            "project_sequence": 1,
            "event_type": "round3.research.evidence.bundle.v1",
            "occurred_at": "2026-01-06T01:31:00Z",
            "body": build_development_bundle().to_wire(),
        }

    def replay(self, after_sequence: int, limit: int):
        if after_sequence < 1 and limit >= 1:
            return (self._event,)
        return ()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m v3_backend.adapters.round3_evidence.development_runtime"
    )
    parser.add_argument("--transport", required=True, choices=[TRANSPORT])
    parser.parse_args(argv)
    try:
        token = read_supervisor_token()
        runtime = build_runtime(
            token,
            BACKEND_VERSION,
            RuntimePorts(
                capabilities=default_capabilities(),
                event_replay=_SingleBundleReplay(),
            ),
        )
        runtime.run(sys.stdin.buffer, sys.stdout.buffer)
        return 0
    except ProtocolViolation as exc:
        _diagnostic("ERROR", "RUNTIME_PROTOCOL_VIOLATION", str(exc))
        return 2
    except Exception as exc:
        _diagnostic(
            "ERROR",
            "ROUND3_INTEGRATION_FIXTURE_RUNTIME_ERROR",
            f"explicit integration fixture runtime terminated: {type(exc).__name__}: {exc}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROJECT_ID",
    "SESSION_VIEW_ID",
    "DevelopmentCanonicalChain",
    "build_development_chain",
    "build_development_bundle",
    "main",
]
