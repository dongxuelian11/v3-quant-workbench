from __future__ import annotations

import dataclasses
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import v3_backend.domain.backtest_runtime as backtest_runtime
from round3_w0_weight_seam.test_weight_seam import WeightSeamFixture
from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.backtest_payloads import BacktestCanonicalPayloadBindingResolver
from v3_backend.domain.artifacts.identity import storage_key_for_artifact_id
from v3_backend.domain.artifacts.policy import ADMITTED, FormatRule, SafeFormatPolicy
from v3_backend.domain.backtest_runtime import (
    CALENDAR_ROLE,
    CALENDAR_SCHEMA,
    CORPORATE_ACTION_ROLE,
    CORPORATE_ACTION_SCHEMA,
    MARKET_ROLE,
    MARKET_SCHEMA,
    SNAPSHOT_ROLE,
    SNAPSHOT_SCHEMA,
    UNIVERSE_ROLE,
    UNIVERSE_SCHEMA,
    WEIGHT_ROLE,
    BacktestPayloadReference,
    CanonicalWeightContentMismatch,
    FormalBacktestPayloadError,
    FormalBacktestRunRequest,
    FormalBacktestRunResult,
    FormalBacktestService,
    ScheduledWeightPayloadReference,
    cn_a_share_2023_08_28_cost_policy,
    cn_a_share_2026_07_06_execution_timing_profile,
    cn_a_share_2026_07_06_rule_profile,
)
from v3_backend.domain.payload_authority import (
    CanonicalPayloadBinding,
    CanonicalPayloadResolver,
    PayloadContentMismatch,
    PayloadResolutionRequest,
)
from v3_backend.domain.weights import (
    RiskAdjustedWeightVector,
    TargetWeightRow,
    TargetWeightVector,
    WeightContractError,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256


DAY = date(2026, 7, 7)
CN = ZoneInfo("Asia/Shanghai")
CONTEXT = "ctx_sha256_systemic_a3_001"


class OwnerBindingRepository:
    def __init__(self) -> None:
        self.bindings: dict[str, CanonicalPayloadBinding] = {}

    def resolve_backtest_payload_binding(
        self, request: PayloadResolutionRequest
    ) -> CanonicalPayloadBinding | None:
        return self.bindings.get(request.request_identity)


class WeightOwner:
    def __init__(self, vectors: tuple[RiskAdjustedWeightVector, ...]) -> None:
        self.vectors = {
            item.risk_adjusted_weight_vector_id: item for item in vectors
        }

    def resolve(self, risk_adjusted_weight_vector_id: str) -> RiskAdjustedWeightVector | None:
        return self.vectors.get(risk_adjusted_weight_vector_id)


class FormalBacktestPayloadTests(WeightSeamFixture):
    def setUp(self) -> None:
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        roles = (
            SNAPSHOT_ROLE,
            MARKET_ROLE,
            CALENDAR_ROLE,
            CORPORATE_ACTION_ROLE,
            UNIVERSE_ROLE,
            WEIGHT_ROLE,
        )
        policy = SafeFormatPolicy(
            tuple(
                FormatRule(
                    role,
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "A3 tests publish strict non-executable canonical JSON",
                )
                for role in roles
            )
        )
        self.store = FileSystemArtifactStore(Path(self.temp.name), policy=policy)
        self.repository = OwnerBindingRepository()
        self.vector = self._risk_vector()
        self.weight_owner = WeightOwner((self.vector,))

        self.snapshot_ref = self._ref("DATA_TRUTH", "snap_a3_001", "1", SNAPSHOT_ROLE)
        self.market_ref = self._ref("DATA_TRUTH", "mdv_a3_001", "1", MARKET_ROLE)
        self.calendar_ref = self._ref("DATA_TRUTH", "cal_a3_001", "1", CALENDAR_ROLE)
        self.actions_ref = self._ref("DATA_TRUTH", "ca_a3_001", "1", CORPORATE_ACTION_ROLE)
        self.universe_ref = self._ref("UNIVERSE", "unv_a3_001", "1", UNIVERSE_ROLE)
        self.weight_ref = self._ref(
            "RISK",
            self.vector.risk_adjusted_weight_vector_id,
            self.vector.schema_version,
            WEIGHT_ROLE,
        )

        self.payloads = {
            SNAPSHOT_ROLE: self._snapshot_payload(),
            MARKET_ROLE: self._market_payload(),
            CALENDAR_ROLE: self._calendar_payload(),
            CORPORATE_ACTION_ROLE: self._actions_payload(),
            UNIVERSE_ROLE: self._universe_payload(),
            WEIGHT_ROLE: self.vector.to_wire(),
        }
        for reference in self.references:
            self._publish(reference, self.payloads[reference.payload_role])
        self.service = self._service()

    @property
    def references(self) -> tuple[BacktestPayloadReference, ...]:
        return (
            self.snapshot_ref,
            self.market_ref,
            self.calendar_ref,
            self.actions_ref,
            self.universe_ref,
            self.weight_ref,
        )

    def _risk_vector(self) -> RiskAdjustedWeightVector:
        rebalance = datetime(2026, 7, 7, 8, 0, tzinfo=CN)
        rows = (
            TargetWeightRow("000001.SZ", "0.5"),
            TargetWeightRow("000002.SZ", "0.4"),
        )
        target = TargetWeightVector.create(
            source=self.source,
            construction_spec=self.construction,
            evidence_refs=self.evidence,
            runtime_identity=self.runtime,
            base_currency="CNY",
            as_of=rebalance - timedelta(hours=1),
            decision_time=rebalance - timedelta(minutes=30),
            rebalance_time=rebalance,
            valid_until=rebalance + timedelta(days=1),
            cash_weight="0.1",
            rows=rows,
        )
        return RiskAdjustedWeightVector.create(
            source_target=target,
            risk_application=self.risk_receipt(target),
            runtime_identity=self.runtime,
            cash_weight="0.1",
            rows=rows,
        )

    @staticmethod
    def _ref(namespace: str, owner_id: str, owner_version: str, role: str):
        return BacktestPayloadReference(
            owner_namespace=namespace,
            owner_id=owner_id,
            owner_version=owner_version,
            payload_role=role,
            context_identity=CONTEXT,
            max_bytes=1024 * 1024,
        )

    def _snapshot_payload(self):
        return {
            "schema_version": SNAPSHOT_SCHEMA,
            "context_identity": CONTEXT,
            "snapshot_id": "snap_a3_001",
            "knowledge_cutoff": "2026-07-07T16:00:00+08:00",
            "market_data_owner_id": "mdv_a3_001",
            "calendar_owner_id": "cal_a3_001",
            "corporate_actions_owner_id": "ca_a3_001",
            "universe_owner_id": "unv_a3_001",
        }

    def _calendar_payload(self):
        return {
            "schema_version": CALENDAR_SCHEMA,
            "context_identity": CONTEXT,
            "calendar_version_id": "cal_a3_001",
            "snapshot_id": "snap_a3_001",
            "sessions": [{"session_date": DAY.isoformat(), "is_open": True}],
        }

    def _universe_payload(self):
        return {
            "schema_version": UNIVERSE_SCHEMA,
            "context_identity": CONTEXT,
            "universe_version_id": "unv_a3_001",
            "snapshot_id": "snap_a3_001",
            "instruments": [
                {
                    "instrument_id": instrument_id,
                    "board": "SZSE_MAIN",
                    "effective_from": "2026-07-01",
                    "effective_to": None,
                }
                for instrument_id in (
                    "000001.SZ",
                    "000002.SZ",
                    "000003.SZ",
                    "000004.SZ",
                )
            ],
        }

    def _market_payload(self, *, first_status="TRADING", first_open="10"):
        records = []
        for instrument_id, price, status in (
            ("000001.SZ", first_open, first_status),
            ("000002.SZ", "20", "TRADING"),
            ("000003.SZ", "30", "TRADING"),
            ("000004.SZ", "40", "TRADING"),
        ):
            records.append(
                {
                    "session_date": DAY.isoformat(),
                    "instrument_id": instrument_id,
                    "board": "SZSE_MAIN",
                    "raw_open": price,
                    "raw_high": price,
                    "raw_low": price,
                    "raw_close": price,
                    "volume": 1000000,
                    "amount": "10000000",
                    "open_trading_status": status,
                    "session_available": True,
                    "restricted_security": False,
                    "buy_restricted": False,
                    "no_price_limit_session": False,
                }
            )
        return {
            "schema_version": MARKET_SCHEMA,
            "context_identity": CONTEXT,
            "market_data_version_id": "mdv_a3_001",
            "snapshot_id": "snap_a3_001",
            "calendar_version_id": "cal_a3_001",
            "universe_version_id": "unv_a3_001",
            "records": records,
        }

    def _actions_payload(self):
        return {
            "schema_version": CORPORATE_ACTION_SCHEMA,
            "context_identity": CONTEXT,
            "corporate_action_set_id": "ca_a3_001",
            "snapshot_id": "snap_a3_001",
            "events": [
                {
                    "action_id": "action_a3_001",
                    "instrument_id": "000001.SZ",
                    "ex_date": DAY.isoformat(),
                    "action_type": "CASH_DIVIDEND",
                    "cash_per_share": "0.1",
                    "ratio_numerator": 1,
                    "ratio_denominator": 1,
                }
            ],
        }

    def _publish(self, reference: BacktestPayloadReference, wire: dict[str, object]):
        payload = canonical_json_bytes(wire)
        stage = self.store.stage_bytes(payload)
        publication = self.store.publish(
            stage.staging_token,
            expected_sha256=stage.sha256,
            expected_byte_size=stage.byte_size,
            media_type="application/json",
            role=reference.payload_role,
            provenance_entity_id="prv_systemic_a3_001",
            schema_fingerprint=reference.schema_fingerprint,
            semantic_fingerprint=CONTEXT,
        )
        request = reference.to_request()
        binding = CanonicalPayloadBinding(
            owner_namespace=reference.owner_namespace,
            owner_id=reference.owner_id,
            owner_version=reference.owner_version,
            payload_role=reference.payload_role,
            artifact_id=publication.descriptor.artifact_id,
            expected_sha256=publication.descriptor.sha256,
            expected_byte_size=publication.descriptor.byte_size,
            context_identity=reference.context_identity,
            binding_version="v3.a3-owner-binding/1.0.0",
            schema_fingerprint=reference.schema_fingerprint,
            semantic_fingerprint=CONTEXT,
            provenance_reference_id="prv_systemic_a3_001",
        )
        self.repository.bindings[request.request_identity] = binding
        self.payloads[reference.payload_role] = wire
        return binding

    def _service(self):
        binding_resolver = BacktestCanonicalPayloadBindingResolver(self.repository)
        payload_resolver = CanonicalPayloadResolver(
            binding_resolver=binding_resolver,
            byte_reader=self.store,
        )
        return FormalBacktestService(
            payload_resolver=payload_resolver,
            weight_resolver=self.weight_owner,
        )

    def request(self, *, initial_cash="100000", initial_holdings=()):
        return FormalBacktestRunRequest.create(
            snapshot=self.snapshot_ref,
            market_data=self.market_ref,
            calendar=self.calendar_ref,
            corporate_actions=self.actions_ref,
            universe=self.universe_ref,
            scheduled_weights=(
                ScheduledWeightPayloadReference(
                    self.vector.source_target.rebalance_time,
                    self.weight_ref,
                ),
            ),
            session_start=DAY,
            session_end=DAY,
            initial_cash=initial_cash,
            initial_holdings=tuple(initial_holdings),
            rule_profile=cn_a_share_2026_07_06_rule_profile(),
            cost_policy=cn_a_share_2023_08_28_cost_policy(
                commission_rate="0",
                minimum_commission="0",
            ),
            execution_timing_profile=cn_a_share_2026_07_06_execution_timing_profile(),
            runtime_identity=self.runtime,
        )

    def _tamper_artifact(self, reference: BacktestPayloadReference, wire):
        binding = self.repository.bindings[reference.to_request().request_identity]
        path = self.store.root.joinpath(
            *storage_key_for_artifact_id(binding.artifact_id).split("/")
        )
        path.write_bytes(canonical_json_bytes(wire))

    def test_a3_01_exact_canonical_happy_path_resolves_and_runs(self):
        execution = self.service.execute(self.request())
        self.assertIsInstance(execution.result, FormalBacktestRunResult)
        self.assertEqual(execution.result.run_spec_id, execution.run_spec.run_spec_id)
        self.assertEqual(len(execution.result.resolution_evidence), 6)
        self.assertEqual(
            {item.payload_role for item in execution.result.resolution_evidence},
            {
                SNAPSHOT_ROLE,
                MARKET_ROLE,
                CALENDAR_ROLE,
                CORPORATE_ACTION_ROLE,
                UNIVERSE_ROLE,
                WEIGHT_ROLE,
            },
        )
        self.assertTrue(execution.result.pure_result.fills)
        execution.result.assert_canonical()
        result_wire = execution.result.to_wire()
        identity_wire = {
            key: value
            for key, value in result_wire.items()
            if key not in {"formal_result_id", "content_sha256"}
        }
        self.assertEqual(canonical_sha256(identity_wire), execution.result.content_sha256)
        self.assertEqual(
            result_wire["rule_profile_sha256"],
            execution.request.rule_profile.content_sha256,
        )
        self.assertEqual(
            result_wire["cost_policy_sha256"],
            execution.request.cost_policy.content_sha256,
        )
        self.assertEqual(
            result_wire["execution_timing_profile_sha256"],
            execution.request.execution_timing_profile.content_sha256,
        )

    def test_a3_02_correct_market_ref_with_altered_price_bytes_rejects(self):
        self._tamper_artifact(self.market_ref, self._market_payload(first_open="11"))
        with self.assertRaises(PayloadContentMismatch):
            self.service.execute(self.request())

    def test_a3_03_formal_request_has_no_detached_market_state_field(self):
        fields = {item.name for item in dataclasses.fields(FormalBacktestRunRequest)}
        self.assertFalse(
            fields
            & {
                "sessions",
                "daily_market_state",
                "market_states",
                "instruments",
                "corporate_action_values",
                "weight_rows",
            }
        )

    def test_a3_04_altered_suspension_bytes_reject(self):
        self._tamper_artifact(
            self.market_ref,
            self._market_payload(first_status="SUSPENDED"),
        )
        with self.assertRaises(PayloadContentMismatch):
            self.service.execute(self.request())

    def test_a3_05_verified_limit_status_controls_tradability(self):
        self._publish(self.market_ref, self._market_payload(first_status="LIMIT_UP"))
        execution = self.service.execute(self.request())
        first_state = execution.run_spec.sessions[0].states[0]
        self.assertTrue(first_state.at_limit_up_open)
        self.assertTrue(first_state.tradable)
        self.assertFalse(first_state.suspended)

    def test_a3_06_wrong_calendar_snapshot_rejects(self):
        altered = {**self._calendar_payload(), "snapshot_id": "snap_wrong"}
        self._publish(self.calendar_ref, altered)
        with self.assertRaises(FormalBacktestPayloadError):
            self.service.execute(self.request())

    def test_a3_07_wrong_corporate_action_snapshot_rejects(self):
        altered = {**self._actions_payload(), "snapshot_id": "snap_wrong"}
        self._publish(self.actions_ref, altered)
        with self.assertRaises(FormalBacktestPayloadError):
            self.service.execute(self.request())

    def test_a3_08_wrong_universe_membership_rejects(self):
        altered = self._universe_payload()
        altered["instruments"] = altered["instruments"][:1]
        self._publish(self.universe_ref, altered)
        with self.assertRaises(FormalBacktestPayloadError):
            self.service.execute(self.request())

    def test_a3_09_valid_ids_with_empty_substitute_bytes_reject(self):
        altered = {**self._actions_payload(), "events": []}
        self._tamper_artifact(self.actions_ref, altered)
        with self.assertRaises(PayloadContentMismatch):
            self.service.execute(self.request())

    def test_a3_10_wrong_risk_adjusted_payload_rejects(self):
        wrong = {**self.vector.to_wire(), "risk_adjusted_weight_vector_id": "rawv_wrong"}
        self._publish(self.weight_ref, wrong)
        with self.assertRaises(CanonicalWeightContentMismatch):
            self.service.execute(self.request())

    def test_a3_11_exact_weight_id_with_detached_altered_rows_rejects(self):
        forged = dataclasses.replace(
            self.vector,
            rows=(TargetWeightRow("000001.SZ", "0.9"),),
        )
        self.weight_owner.vectors[self.vector.risk_adjusted_weight_vector_id] = forged
        with self.assertRaises(WeightContractError):
            self.service.execute(self.request())

    def test_a3_12_market_context_mismatch_rejects(self):
        altered = {**self._market_payload(), "context_identity": "ctx_wrong"}
        self._publish(self.market_ref, altered)
        with self.assertRaises(FormalBacktestPayloadError):
            self.service.execute(self.request())

    def test_a3_13_initial_state_changes_formal_and_run_spec_identity(self):
        first = self.service.execute(self.request(initial_cash="100000"))
        second = self.service.execute(self.request(initial_cash="90000"))
        self.assertNotEqual(first.request.formal_request_id, second.request.formal_request_id)
        self.assertNotEqual(first.run_spec.run_spec_id, second.run_spec.run_spec_id)
        self.assertNotEqual(first.result.formal_result_id, second.result.formal_result_id)

    def test_a3_14_pure_engine_boundary_is_deterministic_and_not_formal(self):
        first = self.service.execute(self.request())
        second = self.service.execute(self.request())
        self.assertEqual(first.result.formal_result_id, second.result.formal_result_id)
        self.assertEqual(first.result.pure_result.result_id, second.result.pure_result.result_id)
        self.assertNotIsInstance(first.result.pure_result, FormalBacktestRunResult)

    def test_a3_15_wrong_board_metadata_rejects(self):
        altered = self._market_payload()
        altered["records"][0]["board"] = "SSE_MAIN"
        self._publish(self.market_ref, altered)
        with self.assertRaises(FormalBacktestPayloadError):
            self.service.execute(self.request())

    def test_a3_16_market_session_availability_must_match_calendar(self):
        altered = self._market_payload()
        altered["records"][0]["session_available"] = False
        self._publish(self.market_ref, altered)
        with self.assertRaises(FormalBacktestPayloadError):
            self.service.execute(self.request())

    def test_a3_17_active_universe_cannot_carry_delisted_market_status(self):
        self._publish(self.market_ref, self._market_payload(first_status="DELISTED"))
        with self.assertRaises(FormalBacktestPayloadError):
            self.service.execute(self.request())

    def test_a3_18_caller_computed_tradable_or_limit_flags_are_rejected(self):
        altered = self._market_payload()
        altered["records"][0]["tradable"] = False
        altered["records"][0]["at_limit_up_open"] = False
        self._publish(self.market_ref, altered)
        with self.assertRaises(FormalBacktestPayloadError):
            self.service.execute(self.request())

    def test_a3_19_formal_result_has_no_public_mint_seam(self):
        execution = self.service.execute(self.request())

        self.assertFalse(hasattr(FormalBacktestRunResult, "create"))
        with self.assertRaisesRegex(TypeError, "minted only by FormalBacktestService"):
            FormalBacktestRunResult()
        constructor_values = tuple(
            getattr(execution.result, field.name)
            for field in dataclasses.fields(FormalBacktestRunResult)
        )
        with self.assertRaisesRegex(TypeError, "minted only by FormalBacktestService"):
            FormalBacktestRunResult(*constructor_values)
        self.assertNotIn(
            "_materialize_formal_backtest_run_result",
            backtest_runtime.__all__,
        )
        self.assertFalse(
            hasattr(backtest_runtime, "_materialize_formal_backtest_run_result")
        )

    def test_a3_20_formal_result_identity_and_wire_remain_exact(self):
        result = self.service.execute(self.request()).result

        self.assertEqual(
            result.formal_result_id,
            "fbtrr_sha256_f299aacc3689a20285d0143acaa848d96a690afe8c7a9b1f112a29eb5609bc03",
        )
        self.assertEqual(
            result.content_sha256,
            "f299aacc3689a20285d0143acaa848d96a690afe8c7a9b1f112a29eb5609bc03",
        )
        self.assertEqual(
            canonical_sha256(result.to_wire()),
            "80021e9a4b5ab9e4af4db1f93f9211079397b4b262763a46040e657845ee8782",
        )
        result.assert_canonical()

    def test_a3_21_caller_materials_do_not_expose_a_supported_mint_api(self):
        execution = self.service.execute(self.request())
        caller_materials = (
            execution.request,
            execution.run_spec,
            execution.result.pure_result,
            execution.result.resolution_evidence,
        )

        self.assertEqual(len(caller_materials), 4)
        self.assertFalse(hasattr(FormalBacktestRunResult, "create"))
        self.assertFalse(
            any(
                "mint" in name.lower() or "materialize" in name.lower()
                for name in backtest_runtime.__all__
            )
        )


if __name__ == "__main__":
    unittest.main()
