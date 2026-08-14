from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from v3_backend.adapters.artifact_store.filesystem import FileSystemArtifactStore
from v3_backend.adapters.market_data.akshare import (
    AKSHARE_PROVIDER_VERSION,
    AkshareAShareEodAdapter,
)
from v3_backend.adapters.market_data.capability_policy import (
    publish_field_capability_policy,
    publish_source_authority_evidence,
)
from v3_backend.contracts.common.truth_admission import (
    NOT_FORMAL_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.data_truth import (
    AvailableTimeSemantics,
    CapabilityAvailability,
    CapabilityTarget,
    ConflictMode,
    ConnectorDataCapability,
    FieldCandidate,
    FieldCapability,
    FieldCapabilityPolicy,
    FieldCapabilityState,
    FieldProvenance,
    FieldSourceRule,
    FieldValueKind,
    FormalMarketStateUnavailable,
    MarketDataCapabilityProfile,
    MarketDataFieldCode,
    NormalizationError,
    PersistedProviderAdmission,
    ProviderAdapterRegistry,
    ProviderCanonicalAdmissionUnavailable,
    ProviderExecutionUnavailable,
    ProviderPolicyMismatch,
    ProviderRuntimeConfig,
    ProviderDescriptor,
    ResolutionStatus,
    RevisionSemantics,
    SourceCostClass,
    SourceAuthorityEvidence,
    SourceResolutionPolicy,
    StrictFormalMarketStateGate,
    evaluate_capability_profile,
    field_candidates_from_eod,
    formal_market_state_requirements,
    normalize_a_share_eod,
    research_requirements,
    resolve_field,
    resolve_field_capability_policy,
)
from v3_backend.domain.payload_authority.model import (
    CanonicalPayloadBinding,
    PayloadResolutionRequest,
)
from v3_backend.domain.payload_authority.service import CanonicalPayloadResolver


UTC = timezone.utc
NOW = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)
FREE_PROVIDER = "pvd_akshare_eastmoney_a_share_eod_v1"
FREE_CONNECTOR = "cov_akshare_1_18_84_v0"
REQUEST = {
    "symbol": "000001",
    "period": "daily",
    "start_date": "20260105",
    "end_date": "20260105",
    "adjust": "",
    "timeout": 10,
}


class FakeFrame:
    def to_dict(self, *, orient: str):
        if orient != "records":
            raise AssertionError("unexpected orientation")
        return [
            {
                "日期": "2026-01-05",
                "股票代码": "000001",
                "开盘": 10.0,
                "收盘": 10.2,
                "最高": 10.3,
                "最低": 9.9,
                "成交量": 1000,
                "成交额": 10100.0,
            }
        ]


class FakeAkshare:
    __version__ = AKSHARE_PROVIDER_VERSION

    def stock_zh_a_hist(self, **request: object) -> FakeFrame:
        return FakeFrame()


def free_adapter() -> AkshareAShareEodAdapter:
    return AkshareAShareEodAdapter(
        connector_version_id=FREE_CONNECTOR,
        loader=FakeAkshare,
        clock=lambda: NOW,
    )


def make_policy(
    provider_id: str,
    connector_version_id: str,
    *,
    state: FieldCapabilityState = FieldCapabilityState.AVAILABLE,
    cost: SourceCostClass = SourceCostClass.UNKNOWN,
    complete: bool = True,
) -> FieldCapabilityPolicy:
    codes = tuple(MarketDataFieldCode) if complete else (MarketDataFieldCode.OHLC,)
    fields = []
    for code in codes:
        observed_state = state
        fields.append(
            FieldCapability(
                field_code=code,
                state=observed_state,
                source_field_semantic=(
                    f"synthetic.{code.value.lower()}"
                    if observed_state in {
                        FieldCapabilityState.AVAILABLE,
                        FieldCapabilityState.PARTIAL,
                    }
                    else None
                ),
                available_time_semantics=(
                    AvailableTimeSemantics.PROVIDER_REPORTED
                    if observed_state is FieldCapabilityState.AVAILABLE
                    else AvailableTimeSemantics.UNKNOWN
                ),
                revision_semantics=(
                    RevisionSemantics.REVISION_AWARE
                    if observed_state is FieldCapabilityState.AVAILABLE
                    else RevisionSemantics.UNKNOWN
                ),
                provenance_required=True,
                reason_code=(
                    None
                    if observed_state in {
                        FieldCapabilityState.AVAILABLE,
                        FieldCapabilityState.PARTIAL,
                    }
                    else "SYNTHETIC_CAPABILITY_NOT_PROVEN"
                ),
            )
        )
    return FieldCapabilityPolicy(
        policy_version=f"{provider_id}-policy-v1",
        connector_version_id=connector_version_id,
        provider_id=provider_id,
        logical_dataset="CN_A_SHARE_EOD",
        frequency="P1D",
        normalization_contract_version="synthetic-neutral-v1",
        source_cost_class=cost,
        fields=tuple(fields),
    )


def provenance(
    provider_id: str,
    connector_version_id: str,
    field_code: MarketDataFieldCode,
    *,
    complete: bool = True,
    authority_evidence_artifact_id: str | None = None,
) -> FieldProvenance:
    digest = hashlib.sha256(f"{provider_id}:{field_code.value}".encode()).hexdigest()
    return FieldProvenance(
        provider_id=provider_id,
        connector_version_id=connector_version_id,
        logical_dataset="CN_A_SHARE_EOD",
        raw_capture_id="raw_" + digest,
        artifact_id="art_sha256_" + digest,
        content_hash=digest,
        source_field_semantic=f"synthetic.{field_code.value.lower()}",
        effective_time=NOW,
        available_time=NOW if complete else None,
        revision_id="rev-1" if complete else None,
        revision_semantics=(
            RevisionSemantics.REVISION_AWARE
            if complete
            else RevisionSemantics.UNKNOWN
        ),
        acquired_at=NOW,
        value_kind=FieldValueKind.DIRECT,
        authority_evidence_artifact_id=authority_evidence_artifact_id,
    )


def candidate(
    provider_id: str,
    connector_version_id: str,
    field_code: MarketDataFieldCode,
    value: object,
    *,
    complete: bool = True,
) -> FieldCandidate:
    return FieldCandidate(
        field_code=field_code,
        value=value,
        capability_state=FieldCapabilityState.AVAILABLE,
        provenance=provenance(
            provider_id, connector_version_id, field_code, complete=complete
        ),
    )


def policy_for_fields(
    target: CapabilityTarget,
    provider_ids: tuple[str, ...],
    fields: tuple[MarketDataFieldCode, ...],
) -> SourceResolutionPolicy:
    return SourceResolutionPolicy(
        policy_version=f"{target.value.lower()}-policy-v1",
        target=target,
        field_rules=tuple(
            FieldSourceRule(
                field_code=code,
                ordered_provider_ids=provider_ids,
                material=code
                not in {
                    MarketDataFieldCode.VOLUME,
                    MarketDataFieldCode.AMOUNT,
                },
                conflict_mode=(
                    ConflictMode.RETAIN_AND_SELECT
                    if target is CapabilityTarget.RESEARCH
                    else ConflictMode.FAIL_CLOSED
                ),
            )
            for code in fields
        ),
    )


class StaticBindingResolver:
    def __init__(self, binding: CanonicalPayloadBinding) -> None:
        self.binding = binding

    def resolve(self, request: PayloadResolutionRequest) -> CanonicalPayloadBinding:
        return self.binding


class StaticAdmissionResolver:
    def __init__(self, admission: PersistedProviderAdmission | None) -> None:
        self.admission = admission

    def resolve(self, config: ProviderRuntimeConfig) -> PersistedProviderAdmission | None:
        return self.admission


class StaticPolicyResolver:
    def __init__(self, policy: FieldCapabilityPolicy) -> None:
        self.policy = policy

    def resolve(self, admission: PersistedProviderAdmission) -> FieldCapabilityPolicy:
        return self.policy


class SyntheticFutureAdapter:
    def __init__(self, provider_id: str, connector_version_id: str) -> None:
        self.provider_id = provider_id
        self.connector_version_id = connector_version_id
        self.policy = make_policy(provider_id, connector_version_id, complete=True)

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id=self.provider_id,
            stable_name="synthetic-future-provider",
            source_authority="SYNTHETIC_TEST_ONLY",
            metadata_hash=hashlib.sha256(b"synthetic-future-provider").hexdigest(),
        )

    def capabilities(self) -> tuple[ConnectorDataCapability, ...]:
        return (
            ConnectorDataCapability(
                connector_version_id=self.connector_version_id,
                provider_id=self.provider_id,
                capability_code="CN_A_SHARE_EOD",
                logical_dataset="CN_A_SHARE_EOD",
                frequency="P1D",
                revision_semantics=RevisionSemantics.REVISION_AWARE,
                provenance_required=True,
                policy_artifact_id=self.policy.policy_artifact_id,
            ),
        )

    def field_capability_policy(self) -> FieldCapabilityPolicy:
        return self.policy

    def capture(self, request):
        raise AssertionError("synthetic port conformance test does not acquire data")


class ProviderNeutralFoundationTests(unittest.TestCase):
    def test_current_adapter_terminates_vendor_columns_before_domain_normalization(self) -> None:
        capture = free_adapter().capture(REQUEST)
        neutral = capture.observations.rows[0]
        self.assertEqual(neutral.symbol, "000001")
        self.assertFalse(any("日期" in name for name in neutral.__dataclass_fields__))
        snapshot = normalize_a_share_eod(capture)
        record = snapshot.records[0]
        self.assertEqual(record.symbol, "000001")
        self.assertEqual(record.provider_id, FREE_PROVIDER)
        self.assertEqual(record.artifact_id, capture.envelope.artifact_id)
        self.assertIn(("open", "AKShare.stock_zh_a_hist.开盘"), record.source_semantics)
        candidates = field_candidates_from_eod(
            record, free_adapter().field_capability_policy()
        )
        observed = {item.field_code: item for item in candidates}
        self.assertEqual(
            observed[MarketDataFieldCode.OHLC].provenance.raw_capture_id,
            capture.envelope.raw_capture_id,
        )
        self.assertEqual(
            observed[MarketDataFieldCode.TRADING_STATUS].provenance.value_kind,
            FieldValueKind.UNAVAILABLE,
        )
        self.assertIsNone(observed[MarketDataFieldCode.TRADING_STATUS].value)

    def test_normalizer_rejects_observations_not_bound_to_raw_capture_bytes(self) -> None:
        capture = free_adapter().capture(REQUEST)
        changed_row = replace(capture.observations.rows[0], close="9999.00")
        changed_batch = replace(capture.observations, rows=(changed_row,))
        with self.assertRaisesRegex(
            NormalizationError,
            "provider-neutral observations do not match immutable capture bytes",
        ):
            normalize_a_share_eod(replace(capture, observations=changed_batch))

    def test_free_provider_declares_every_field_without_fabrication(self) -> None:
        adapter = free_adapter()
        policy = adapter.field_capability_policy()
        self.assertEqual({item.field_code for item in policy.fields}, set(MarketDataFieldCode))
        self.assertEqual(
            policy.capability(MarketDataFieldCode.OHLC).state,
            FieldCapabilityState.AVAILABLE,
        )
        self.assertEqual(
            policy.capability(MarketDataFieldCode.TRADING_STATUS).state,
            FieldCapabilityState.UNAVAILABLE,
        )
        self.assertEqual(
            policy.capability(MarketDataFieldCode.PIT_VISIBILITY).state,
            FieldCapabilityState.UNKNOWN,
        )
        capability = adapter.capabilities()[0]
        self.assertEqual(capability.policy_artifact_id, policy.policy_artifact_id)
        self.assertEqual(capability.revision_semantics, RevisionSemantics.UNKNOWN)

    def test_capability_policy_is_deterministic_and_unknown_is_distinct(self) -> None:
        first = free_adapter().field_capability_policy()
        second = free_adapter().field_capability_policy()
        self.assertEqual(first.artifact_bytes, second.artifact_bytes)
        self.assertEqual(first.policy_artifact_id, second.policy_artifact_id)
        self.assertNotEqual(
            FieldCapabilityState.UNKNOWN, FieldCapabilityState.UNAVAILABLE
        )
        decoded = FieldCapabilityPolicy.from_canonical_bytes(first.artifact_bytes)
        self.assertEqual(decoded, first)

    def test_capability_policy_publishes_in_existing_store_and_resolves_through_p1(self) -> None:
        policy = free_adapter().field_capability_policy()
        with tempfile.TemporaryDirectory() as directory:
            store = FileSystemArtifactStore(directory)
            published = publish_field_capability_policy(
                store,
                policy,
                provenance_entity_id="prv_data_truth_capability_policy_test",
                published_at=NOW,
            )
            self.assertEqual(published.descriptor.artifact_id, policy.policy_artifact_id)
            request = PayloadResolutionRequest(
                owner_namespace="DATA_TRUTH",
                owner_id=FREE_CONNECTOR,
                owner_version="1",
                payload_role="DATA_TRUTH_CAPABILITY_POLICY",
                context_identity=policy.policy_identity,
                max_bytes=1_000_000,
            )
            binding = CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=request.owner_id,
                owner_version=request.owner_version,
                payload_role=request.payload_role,
                artifact_id=policy.policy_artifact_id,
                expected_sha256=published.descriptor.sha256,
                expected_byte_size=published.descriptor.byte_size,
                context_identity=request.context_identity,
                binding_version="1",
                schema_fingerprint=published.descriptor.schema_fingerprint,
            )
            resolver = CanonicalPayloadResolver(
                binding_resolver=StaticBindingResolver(binding), byte_reader=store
            )
            resolved = resolve_field_capability_policy(resolver, request)
            self.assertEqual(resolved, policy)

    def test_multi_source_resolution_is_per_field_and_deterministic(self) -> None:
        p1, p2 = "pvd_source_one", "pvd_source_two"
        c1, c2 = "cov_source_one", "cov_source_two"
        fields = (MarketDataFieldCode.OHLC, MarketDataFieldCode.TRADING_STATUS)
        resolution_policy = policy_for_fields(CapabilityTarget.RESEARCH, (p1, p2), fields)
        ohlc = candidate(p1, c1, MarketDataFieldCode.OHLC, ("10", "11", "9", "10.5"))
        status = candidate(p2, c2, MarketDataFieldCode.TRADING_STATUS, "TRADING")
        first = resolve_field(MarketDataFieldCode.OHLC, (ohlc,), resolution_policy)
        second = resolve_field(
            MarketDataFieldCode.TRADING_STATUS, (status,), resolution_policy
        )
        self.assertEqual(first.selected_provenance.provider_id, p1)
        self.assertEqual(second.selected_provenance.provider_id, p2)
        self.assertEqual(
            first.selected_provenance.selection_policy_id,
            resolution_policy.policy_identity,
        )
        self.assertTrue(first.selected_provenance.raw_capture_id.startswith("raw_"))
        self.assertTrue(first.selected_provenance.artifact_id.startswith("art_sha256_"))
        self.assertEqual(first.selected_provenance.logical_dataset, "CN_A_SHARE_EOD")
        self.assertEqual(first.selected_provenance.revision_id, "rev-1")

    def test_research_conflict_retains_evidence_and_uses_explicit_priority(self) -> None:
        p1, p2 = "pvd_preferred", "pvd_secondary"
        policy = policy_for_fields(
            CapabilityTarget.RESEARCH, (p1, p2), (MarketDataFieldCode.BOARD,)
        )
        one = candidate(p1, "cov_preferred", MarketDataFieldCode.BOARD, "MAIN")
        two = candidate(p2, "cov_secondary", MarketDataFieldCode.BOARD, "CHINEXT")
        forward = resolve_field(MarketDataFieldCode.BOARD, (one, two), policy)
        reverse = resolve_field(MarketDataFieldCode.BOARD, (two, one), policy)
        self.assertEqual(forward.value, "MAIN")
        self.assertEqual(reverse.value, "MAIN")
        self.assertEqual(len(forward.conflict_provenance), 2)
        self.assertIn("SOURCE_CONFLICT_RETAINED", forward.reason_codes)

    def test_formal_material_conflict_fails_closed(self) -> None:
        p1, p2 = "pvd_preferred", "pvd_secondary"
        policy = policy_for_fields(
            CapabilityTarget.FORMAL_MARKET_STATE,
            (p1, p2),
            (MarketDataFieldCode.TRADING_STATUS,),
        )
        one = candidate(p1, "cov_preferred", MarketDataFieldCode.TRADING_STATUS, "TRADING")
        two = candidate(p2, "cov_secondary", MarketDataFieldCode.TRADING_STATUS, "SUSPENDED")
        resolved = resolve_field(
            MarketDataFieldCode.TRADING_STATUS, (one, two), policy
        )
        self.assertEqual(resolved.status, ResolutionStatus.NOT_AVAILABLE)
        self.assertIsNone(resolved.value)
        self.assertEqual(len(resolved.conflict_provenance), 2)

    def test_formal_conflict_requires_exact_authority_evidence_to_resolve(self) -> None:
        p1, p2 = "pvd_authoritative", "pvd_other"
        connector = "cov_authoritative"
        evidence = SourceAuthorityEvidence(
            resolution_policy_version="formal-authoritative-board-v1",
            field_code=MarketDataFieldCode.BOARD,
            authoritative_provider_id=p1,
            authoritative_connector_version_id=connector,
            logical_dataset="CN_A_SHARE_EOD",
        )
        policy = SourceResolutionPolicy(
            policy_version="formal-authoritative-board-v1",
            target=CapabilityTarget.FORMAL_MARKET_STATE,
            field_rules=(
                FieldSourceRule(
                    field_code=MarketDataFieldCode.BOARD,
                    ordered_provider_ids=(p1, p2),
                    material=True,
                    conflict_mode=ConflictMode.AUTHORITATIVE_EVIDENCE,
                    authoritative_provider_id=p1,
                    authority_evidence_artifact_id=evidence.artifact_id,
                ),
            ),
        )
        one = candidate(p1, connector, MarketDataFieldCode.BOARD, "MAIN")
        two = candidate(p2, "cov_other", MarketDataFieldCode.BOARD, "CHINEXT")
        unresolved = resolve_field(MarketDataFieldCode.BOARD, (two, one), policy)
        self.assertEqual(unresolved.status, ResolutionStatus.NOT_AVAILABLE)
        with tempfile.TemporaryDirectory() as directory:
            store = FileSystemArtifactStore(directory)
            published = publish_source_authority_evidence(
                store,
                evidence,
                provenance_entity_id="prv_data_truth_source_authority_test",
                published_at=NOW,
            )
            request = PayloadResolutionRequest(
                owner_namespace="DATA_TRUTH_SOURCE_AUTHORITY",
                owner_id="source_authority_board_v1",
                owner_version="1",
                payload_role="DATA_TRUTH_SOURCE_AUTHORITY_EVIDENCE",
                context_identity="formal-authoritative-board-v1",
                max_bytes=1_000_000,
            )
            binding = CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=request.owner_id,
                owner_version=request.owner_version,
                payload_role=request.payload_role,
                artifact_id=evidence.artifact_id,
                expected_sha256=published.descriptor.sha256,
                expected_byte_size=published.descriptor.byte_size,
                context_identity=request.context_identity,
                binding_version="1",
                schema_fingerprint=published.descriptor.schema_fingerprint,
            )
            resolver = CanonicalPayloadResolver(
                binding_resolver=StaticBindingResolver(binding), byte_reader=store
            )
            resolved = resolve_field(
                MarketDataFieldCode.BOARD,
                (two, one),
                policy,
                authority_resolver=resolver,
                authority_request=request,
            )
            self.assertEqual(resolved.status, ResolutionStatus.RESOLVED)
            self.assertEqual(resolved.value, "MAIN")
            self.assertEqual(resolved.selected_provenance.provider_id, p1)
            self.assertEqual(
                resolved.selected_provenance.authority_evidence_artifact_id,
                evidence.artifact_id,
            )

    def test_no_eligible_provider_is_explicit_missing(self) -> None:
        policy = policy_for_fields(
            CapabilityTarget.RESEARCH,
            ("pvd_expected",),
            (MarketDataFieldCode.OHLC,),
        )
        observed = candidate(
            "pvd_not_eligible", "cov_not_eligible", MarketDataFieldCode.OHLC, "x"
        )
        resolved = resolve_field(MarketDataFieldCode.OHLC, (observed,), policy)
        self.assertEqual(resolved.status, ResolutionStatus.MISSING)
        self.assertEqual(resolved.reason_codes, ("NO_ELIGIBLE_PROVIDER_FIELD",))

    def test_partial_free_data_is_research_available_with_pre_alpha_ceiling(self) -> None:
        policy = free_adapter().field_capability_policy()
        fields = (
            MarketDataFieldCode.OHLC,
            MarketDataFieldCode.VOLUME,
            MarketDataFieldCode.AMOUNT,
        )
        resolution_policy = policy_for_fields(
            CapabilityTarget.RESEARCH, (FREE_PROVIDER,), fields
        )
        resolutions = {
            code: resolve_field(
                code,
                (
                    candidate(
                        FREE_PROVIDER,
                        FREE_CONNECTOR,
                        code,
                        f"research-{code.value}",
                        complete=False,
                    ),
                ),
                resolution_policy,
            )
            for code in fields
        }
        profile = MarketDataCapabilityProfile(
            profile_version="research-free-v1",
            target=CapabilityTarget.RESEARCH,
            resolution_policy=resolution_policy,
            requirements=research_requirements(),
        )
        evaluation = evaluate_capability_profile(
            profile, resolutions, {FREE_PROVIDER: policy}
        )
        self.assertEqual(evaluation.availability, CapabilityAvailability.AVAILABLE)
        self.assertEqual(evaluation.truth_ceiling, PRE_ALPHA_CEILING)
        self.assertIn(MarketDataFieldCode.TRADING_STATUS, evaluation.missing_fields)
        self.assertTrue(evaluation.reason_codes)
        self.assertTrue(evaluation.capability_report)

    def test_same_free_data_is_formal_market_state_not_available(self) -> None:
        policy = free_adapter().field_capability_policy()
        fields = tuple(requirement.field_code for requirement in formal_market_state_requirements())
        resolution_policy = policy_for_fields(
            CapabilityTarget.FORMAL_MARKET_STATE, (FREE_PROVIDER,), fields
        )
        resolutions = {
            code: resolve_field(
                code,
                (
                    candidate(
                        FREE_PROVIDER,
                        FREE_CONNECTOR,
                        code,
                        f"free-{code.value}",
                        complete=False,
                    ),
                ),
                resolution_policy,
            )
            for code in (MarketDataFieldCode.OHLC, MarketDataFieldCode.VOLUME)
        }
        profile = MarketDataCapabilityProfile(
            profile_version="formal-best-available-v1",
            target=CapabilityTarget.FORMAL_MARKET_STATE,
            resolution_policy=resolution_policy,
            requirements=formal_market_state_requirements(),
        )
        gate = StrictFormalMarketStateGate(profile)
        evaluation = gate.evaluate(resolutions, {FREE_PROVIDER: policy})
        self.assertEqual(
            evaluation.availability, CapabilityAvailability.NOT_AVAILABLE
        )
        with self.assertRaises(FormalMarketStateUnavailable):
            gate.require_available(resolutions, {FREE_PROVIDER: policy})

    def test_paid_cost_class_alone_does_not_promote_formal(self) -> None:
        provider_id, connector_id = "pvd_paid_named_vendor", "cov_paid_named_vendor"
        paid_policy = make_policy(
            provider_id,
            connector_id,
            state=FieldCapabilityState.UNKNOWN,
            cost=SourceCostClass.PAID,
            complete=False,
        )
        resolution_policy = policy_for_fields(
            CapabilityTarget.FORMAL_MARKET_STATE,
            (provider_id,),
            tuple(requirement.field_code for requirement in formal_market_state_requirements()),
        )
        profile = MarketDataCapabilityProfile(
            profile_version="paid-name-is-not-formal-v1",
            target=CapabilityTarget.FORMAL_MARKET_STATE,
            resolution_policy=resolution_policy,
            requirements=formal_market_state_requirements(),
        )
        evaluation = evaluate_capability_profile(profile, {}, {provider_id: paid_policy})
        self.assertEqual(
            evaluation.availability, CapabilityAvailability.NOT_AVAILABLE
        )

    def test_complete_synthetic_evidence_can_pass_capability_gate_without_minting_truth(self) -> None:
        provider_id, connector_id = "pvd_complete_synthetic", "cov_complete_synthetic"
        persisted = make_policy(provider_id, connector_id, complete=True)
        fields = tuple(requirement.field_code for requirement in formal_market_state_requirements())
        resolution_policy = policy_for_fields(
            CapabilityTarget.FORMAL_MARKET_STATE, (provider_id,), fields
        )
        resolutions = {
            code: resolve_field(
                code,
                (candidate(provider_id, connector_id, code, f"value-{code.value}"),),
                resolution_policy,
            )
            for code in fields
        }
        profile = MarketDataCapabilityProfile(
            profile_version="complete-synthetic-formal-v1",
            target=CapabilityTarget.FORMAL_MARKET_STATE,
            resolution_policy=resolution_policy,
            requirements=formal_market_state_requirements(),
        )
        evaluation = StrictFormalMarketStateGate(profile).require_available(
            resolutions, {provider_id: persisted}
        )
        self.assertEqual(evaluation.availability, CapabilityAvailability.AVAILABLE)
        self.assertEqual(evaluation.truth_ceiling, NOT_FORMAL_CEILING)
        self.assertIn(
            "CAPABILITY_GATE_DOES_NOT_MINT_CANONICAL_TRUTH",
            evaluation.reason_codes,
        )

    def test_acquisition_time_never_substitutes_for_provider_available_time(self) -> None:
        snapshot = normalize_a_share_eod(free_adapter().capture(REQUEST))
        record = snapshot.records[0]
        self.assertEqual(record.acquisition_time, NOW)
        self.assertIsNone(record.available_time)
        self.assertIsNone(record.revision_id)

    def test_registry_denies_installed_but_unadmitted_provider(self) -> None:
        adapter = free_adapter()
        policy = adapter.field_capability_policy()
        registry = ProviderAdapterRegistry({FREE_PROVIDER: lambda config: adapter})
        config = ProviderRuntimeConfig(
            provider_id=FREE_PROVIDER,
            connector_version_id=FREE_CONNECTOR,
            runtime_profile_id="research-free-v1",
        )
        admission = PersistedProviderAdmission(
            provider_id=FREE_PROVIDER,
            connector_version_id=FREE_CONNECTOR,
            policy_artifact_id=policy.policy_artifact_id,
            admitted=False,
        )
        with self.assertRaises(ProviderCanonicalAdmissionUnavailable):
            registry.bind(
                config,
                StaticAdmissionResolver(admission),
                StaticPolicyResolver(policy),
            )

    def test_synthetic_future_provider_uses_same_registration_seam(self) -> None:
        provider_id, connector_id = "pvd_future_adapter", "cov_future_adapter"
        adapter = SyntheticFutureAdapter(provider_id, connector_id)
        registry = ProviderAdapterRegistry({provider_id: lambda config: adapter})
        config = ProviderRuntimeConfig(
            provider_id=provider_id,
            connector_version_id=connector_id,
            runtime_profile_id="institutional-paid-v1",
            credential_reference_id="crf_external_secret_reference",
            usage_policy_reference_id="art_sha256_"
            + hashlib.sha256(b"non-secret-usage-metadata").hexdigest(),
        )
        admission = PersistedProviderAdmission(
            provider_id=provider_id,
            connector_version_id=connector_id,
            policy_artifact_id=adapter.policy.policy_artifact_id,
            admitted=True,
        )
        binding = registry.bind(
            config,
            StaticAdmissionResolver(admission),
            StaticPolicyResolver(adapter.policy),
        )
        self.assertIs(binding.adapter, adapter)
        self.assertNotIn("api_key", ProviderRuntimeConfig.__dataclass_fields__)
        self.assertNotIn("secret", ProviderRuntimeConfig.__dataclass_fields__)

    def test_registry_keeps_admission_known_when_adapter_is_missing(self) -> None:
        policy = free_adapter().field_capability_policy()
        config = ProviderRuntimeConfig(
            provider_id=FREE_PROVIDER,
            connector_version_id=FREE_CONNECTOR,
            runtime_profile_id="research-free-v1",
        )
        admission = PersistedProviderAdmission(
            provider_id=FREE_PROVIDER,
            connector_version_id=FREE_CONNECTOR,
            policy_artifact_id=policy.policy_artifact_id,
            admitted=True,
        )
        with self.assertRaises(ProviderExecutionUnavailable):
            ProviderAdapterRegistry({}).bind(
                config,
                StaticAdmissionResolver(admission),
                StaticPolicyResolver(policy),
            )

    def test_adapter_code_cannot_override_persisted_policy(self) -> None:
        adapter = free_adapter()
        declared = adapter.field_capability_policy()
        persisted = replace(declared, policy_version="persisted-different-v2")
        registry = ProviderAdapterRegistry({FREE_PROVIDER: lambda config: adapter})
        config = ProviderRuntimeConfig(
            provider_id=FREE_PROVIDER,
            connector_version_id=FREE_CONNECTOR,
            runtime_profile_id="research-free-v1",
            credential_reference_id="crf_windows_credential_manager_reference",
        )
        admission = PersistedProviderAdmission(
            provider_id=FREE_PROVIDER,
            connector_version_id=FREE_CONNECTOR,
            policy_artifact_id=persisted.policy_artifact_id,
            admitted=True,
        )
        binding = registry.bind(
            config,
            StaticAdmissionResolver(admission),
            StaticPolicyResolver(persisted),
        )
        with self.assertRaises(ProviderPolicyMismatch):
            binding.capture(REQUEST)


if __name__ == "__main__":
    unittest.main()
