"""A1 formal Dataset construction from P1-verified features and labels."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import timezone
from typing import Protocol

from v3_backend.contracts.common.truth_admission import (
    TruthAdmissionState,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.data_truth.formal import (
    CanonicalSnapshotRepository,
    CanonicalUniverseRepository,
    require_resolved_context,
)
from v3_backend.domain.factors.formal import (
    FACTOR_INPUT_SCHEMA_FINGERPRINT,
    FACTOR_OUTPUT_SCHEMA_FINGERPRINT,
    FACTOR_OUTPUT_SCHEMA_VERSION,
    CanonicalJsonArtifactPublisher,
    FormalFeatureMaterialization,
)
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadResolutionReceipt,
    PayloadResolutionRequest,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

from .model import LabelMissingSemantics, LabelSpec, SplitSpec


FEATURE_VALUES_PAYLOAD_ROLE = "FEATURE_MATERIALIZATION_VALUES"
LABEL_SOURCE_PAYLOAD_ROLE = "DATASET_LABEL_SOURCE"
LABEL_PAYLOAD_ROLE = "DATASET_LABELS"
DATASET_ARTIFACT_ROLE = "DATASET_SAMPLES"
LABEL_SCHEMA_VERSION = "v3.dataset-label-payload/1.1.0"
DATASET_SCHEMA_VERSION = "v3.dataset-samples-payload/1.1.0"
LABEL_SCHEMA_FINGERPRINT = "sch_sha256_" + canonical_sha256(
    {
        "schema_version": LABEL_SCHEMA_VERSION,
        "coordinates": ["instrument_ids", "observation_ids"],
        "context": ["snapshot_id", "universe_version_id", "calendar_version_id", "knowledge_cutoff"],
        "field": ["label_spec_id", "horizon_observations", "shape", "values"],
        "missing": "JSON_NULL_EXCLUDE_SAMPLE",
        "numeric_wire": "CANONICAL_DECIMAL_STRING",
    }
)
DATASET_SCHEMA_FINGERPRINT = "sch_sha256_" + canonical_sha256(
    {
        "schema_version": DATASET_SCHEMA_VERSION,
        "sample": ["sample_id", "instrument_id", "observation_id", "split", "features", "label"],
        "feature_order": "feature_materialization_ids",
        "label_owner": "label_payload_id",
    }
)


class FormalFeatureMaterializationRepository(Protocol):
    def get_materialization(self, feature_materialization_id: str) -> FormalFeatureMaterialization | None: ...


class LabelSpecRepository(Protocol):
    def get_label_spec(self, label_spec_id: str) -> LabelSpec | None: ...


class SplitSpecRepository(Protocol):
    def get_split_spec(self, split_spec_id: str) -> SplitSpec | None: ...


@dataclass(frozen=True, slots=True)
class CanonicalLabelPayloadVersion:
    label_payload_id: str
    label_spec_id: str
    snapshot_id: str
    universe_version_id: str
    calendar_version_id: str
    context_identity: str
    source_receipt: PayloadResolutionReceipt
    engine_version: str
    artifact_id: str
    sha256: str
    byte_size: int
    schema_fingerprint: str
    truth_admission: TruthAdmissionState

    def __post_init__(self) -> None:
        from v3_backend.domain.artifacts.identity import sha256_from_artifact_id, validate_sha256

        if not all((self.label_payload_id, self.label_spec_id, self.snapshot_id, self.universe_version_id, self.calendar_version_id, self.context_identity, self.engine_version)):
            raise ValueError("canonical Label payload identities are required")
        if not isinstance(self.source_receipt, PayloadResolutionReceipt):
            raise TypeError("canonical Label payload requires a P1 source receipt")
        validate_sha256(self.sha256)
        if sha256_from_artifact_id(self.artifact_id) != self.sha256:
            raise ValueError("Label Artifact identity must match sha256")
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool) or self.byte_size < 0:
            raise ValueError("Label byte_size must be a non-negative integer")
        if self.schema_fingerprint != LABEL_SCHEMA_FINGERPRINT:
            raise ValueError("Label payload schema is not admitted")
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("truth_admission must be typed")
        expected = "clp_sha256_" + canonical_sha256(_label_owner_identity_payload(
            label_spec_id=self.label_spec_id,
            snapshot_id=self.snapshot_id,
            universe_version_id=self.universe_version_id,
            calendar_version_id=self.calendar_version_id,
            context_identity=self.context_identity,
            source_receipt=self.source_receipt,
            engine_version=self.engine_version,
            artifact_id=self.artifact_id,
            sha256=self.sha256,
            byte_size=self.byte_size,
            schema_fingerprint=self.schema_fingerprint,
            truth_admission=self.truth_admission,
        ))
        if self.label_payload_id != expected:
            raise ValueError("canonical Label identity does not match owner content")


class CanonicalLabelPayloadRepository(Protocol):
    def get_label_payload(
        self, label_spec_id: str, context_identity: str | None = None
    ) -> CanonicalLabelPayloadVersion | None: ...


class CanonicalHistoricalLabelSource(Protocol):
    def resolve_label_source(
        self,
        *,
        snapshot: CanonicalSnapshotVersion,
        universe: CanonicalUniverseVersion,
        label_spec: LabelSpec,
        max_bytes: int,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[Decimal | None, ...], PayloadResolutionReceipt]: ...


class CanonicalLabelPayloadPublisher(Protocol):
    def publish_label_payload(
        self, owner: CanonicalLabelPayloadVersion
    ) -> CanonicalLabelPayloadVersion: ...


class FormalDatasetPublisher(Protocol):
    def publish_dataset(self, dataset: "FormalDatasetVersion") -> "FormalDatasetVersion": ...


class FormalDatasetRepository(Protocol):
    def get_dataset(self, dataset_version_id: str) -> "FormalDatasetVersion" | None: ...


def feature_output_context_identity(materialization: FormalFeatureMaterialization) -> str:
    return "fmctx_sha256_" + canonical_sha256(
        {
            "feature_materialization_id": materialization.feature_materialization_id,
            "factor_definition_version_id": materialization.factor_definition_version_id,
            "snapshot_id": materialization.snapshot_id,
            "universe_version_id": materialization.universe_version_id,
            "universe_membership_identity": materialization.universe_membership_identity,
            "knowledge_cutoff": materialization.knowledge_cutoff,
            "input_receipt_id": materialization.input_receipt.receipt_identity,
            "output_schema_fingerprint": materialization.output_schema_fingerprint,
        }
    )


def _utc_time(value) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def label_payload_context_identity(
    *,
    snapshot_id: str,
    universe_version_id: str,
    membership_identity: str,
    calendar_version_id: str,
    knowledge_cutoff: str,
    label_spec: LabelSpec,
) -> str:
    return "lblctx_sha256_" + canonical_sha256(
        {
            "snapshot_id": snapshot_id,
            "universe_version_id": universe_version_id,
            "membership_identity": membership_identity,
            "calendar_version_id": calendar_version_id,
            "knowledge_cutoff": knowledge_cutoff,
            "label_spec": label_spec.to_wire(),
            "label_schema_fingerprint": LABEL_SCHEMA_FINGERPRINT,
        }
    )


def label_source_payload_context_identity(
    *,
    snapshot: CanonicalSnapshotVersion,
    universe: CanonicalUniverseVersion,
    label_spec: LabelSpec,
) -> str:
    return "lblsrcctx_sha256_" + canonical_sha256(
        {
            "snapshot": snapshot.to_context_wire(),
            "universe": universe.to_context_wire(),
            "label_spec": label_spec.to_wire(),
            "payload_schema_fingerprint": FACTOR_INPUT_SCHEMA_FINGERPRINT,
        }
    )


def _label_owner_identity_payload(
    *,
    label_spec_id: str,
    snapshot_id: str,
    universe_version_id: str,
    calendar_version_id: str,
    context_identity: str,
    source_receipt: PayloadResolutionReceipt,
    engine_version: str,
    artifact_id: str,
    sha256: str,
    byte_size: int,
    schema_fingerprint: str,
    truth_admission: TruthAdmissionState,
) -> dict[str, object]:
    return {
        "label_spec_id": label_spec_id,
        "snapshot_id": snapshot_id,
        "universe_version_id": universe_version_id,
        "calendar_version_id": calendar_version_id,
        "context_identity": context_identity,
        "source_receipt_id": source_receipt.receipt_identity,
        "engine_version": engine_version,
        "artifact_id": artifact_id,
        "sha256": sha256,
        "byte_size": byte_size,
        "schema_fingerprint": schema_fingerprint,
        "truth_admission": truth_admission.to_wire(),
    }


class DeterministicForwardReturnLabelEngine:
    """Pure LabelSpec engine over verified instrument-major historical values."""

    version = "v3.label-forward-return/1.0.0"

    def compute(
        self,
        *,
        label_spec: LabelSpec,
        instrument_ids: tuple[str, ...],
        observation_ids: tuple[str, ...],
        source_values: tuple[Decimal | None, ...],
    ) -> tuple[str | None, ...]:
        if label_spec.logical_name != "forward-return":
            raise ValueError("formal Label engine requires logical_name=forward-return")
        if label_spec.source_field != "close":
            raise ValueError("formal Label engine currently admits source_field=close only")
        if label_spec.missing_semantics is not LabelMissingSemantics.EXCLUDE_SAMPLE:
            raise ValueError("formal Label engine requires EXCLUDE_SAMPLE missing semantics")
        width = len(observation_ids)
        if not instrument_ids or not observation_ids or len(source_values) != len(instrument_ids) * width:
            raise ValueError("canonical Label source coordinates/shape are invalid")
        horizon = label_spec.horizon_observations
        values: list[str | None] = []
        for instrument_index in range(len(instrument_ids)):
            offset = instrument_index * width
            for observation_index in range(width):
                target_index = observation_index + horizon
                if target_index >= width:
                    values.append(None)
                    continue
                current = source_values[offset + observation_index]
                future = source_values[offset + target_index]
                if current is None or future is None:
                    values.append(None)
                    continue
                if current == 0:
                    values.append(None)
                    continue
                values.append(_decimal_wire((future / current) - Decimal(1)))
        return tuple(values)


class FormalLabelService:
    def __init__(
        self,
        *,
        snapshots: CanonicalSnapshotRepository,
        universes: CanonicalUniverseRepository,
        label_specs: LabelSpecRepository,
        historical_source: CanonicalHistoricalLabelSource,
        engine: DeterministicForwardReturnLabelEngine,
        artifact_publisher: CanonicalJsonArtifactPublisher,
        label_publisher: CanonicalLabelPayloadPublisher,
    ) -> None:
        self._snapshots = snapshots
        self._universes = universes
        self._label_specs = label_specs
        self._historical_source = historical_source
        self._engine = engine
        self._artifact_publisher = artifact_publisher
        self._label_publisher = label_publisher

    def materialize(
        self,
        *,
        label_spec_id: str,
        snapshot_id: str,
        universe_version_id: str,
        max_payload_bytes: int,
    ) -> CanonicalLabelPayloadVersion:
        snapshot, universe = require_resolved_context(
            snapshots=self._snapshots,
            universes=self._universes,
            snapshot_id=snapshot_id,
            universe_version_id=universe_version_id,
        )
        label_spec = self._label_specs.get_label_spec(label_spec_id)
        if label_spec is None:
            raise ValueError("formal Label requires canonical LabelSpec owner resolution")
        instruments, observations, source_values, source_receipt = self._historical_source.resolve_label_source(
            snapshot=snapshot,
            universe=universe,
            label_spec=label_spec,
            max_bytes=max_payload_bytes,
        )
        if instruments != universe.instrument_ids:
            raise ValueError("canonical Label source Universe membership/order differs")
        context = label_payload_context_identity(
            snapshot_id=snapshot.snapshot_id,
            universe_version_id=universe.universe_version_id,
            membership_identity=universe.membership_identity,
            calendar_version_id=snapshot.calendar_version_id,
            knowledge_cutoff=_utc_time(snapshot.knowledge_cutoff),
            label_spec=label_spec,
        )
        values = self._engine.compute(
            label_spec=label_spec,
            instrument_ids=instruments,
            observation_ids=observations,
            source_values=source_values,
        )
        payload: dict[str, object] = {
            "schema_version": LABEL_SCHEMA_VERSION,
            "schema_fingerprint": LABEL_SCHEMA_FINGERPRINT,
            "context_identity": context,
            "label_spec_id": label_spec.label_spec_id,
            "snapshot_id": snapshot.snapshot_id,
            "universe_version_id": universe.universe_version_id,
            "calendar_version_id": snapshot.calendar_version_id,
            "knowledge_cutoff": _utc_time(snapshot.knowledge_cutoff),
            "horizon_observations": label_spec.horizon_observations,
            "instrument_ids": list(instruments),
            "observation_ids": list(observations),
            "shape": [len(instruments), len(observations)],
            "values": list(values),
        }
        descriptor = self._artifact_publisher.publish_canonical_json(
            payload,
            semantic_role=LABEL_PAYLOAD_ROLE,
            provenance_entity_id=source_receipt.receipt_identity,
            schema_fingerprint=LABEL_SCHEMA_FINGERPRINT,
        )
        truth = propagate_downstream_ceiling(
            snapshot.truth_admission,
            (
                UpstreamRequirement(snapshot.snapshot_id, snapshot.truth_admission),
                UpstreamRequirement(universe.membership_identity, universe.truth_admission),
            ),
        )
        identity = _label_owner_identity_payload(
            label_spec_id=label_spec.label_spec_id,
            snapshot_id=snapshot.snapshot_id,
            universe_version_id=universe.universe_version_id,
            calendar_version_id=snapshot.calendar_version_id,
            context_identity=context,
            source_receipt=source_receipt,
            engine_version=self._engine.version,
            artifact_id=descriptor.artifact_id,
            sha256=descriptor.sha256,
            byte_size=descriptor.byte_size,
            schema_fingerprint=LABEL_SCHEMA_FINGERPRINT,
            truth_admission=truth,
        )
        owner = CanonicalLabelPayloadVersion(
            "clp_sha256_" + canonical_sha256(identity),
            label_spec.label_spec_id,
            snapshot.snapshot_id,
            universe.universe_version_id,
            snapshot.calendar_version_id,
            context,
            source_receipt,
            self._engine.version,
            descriptor.artifact_id,
            descriptor.sha256,
            descriptor.byte_size,
            LABEL_SCHEMA_FINGERPRINT,
            truth,
        )
        return self._label_publisher.publish_label_payload(owner)


@dataclass(frozen=True, slots=True)
class FormalDatasetBuildRequest:
    feature_materialization_ids: tuple[str, ...]
    label_spec_id: str
    split_spec_id: str
    snapshot_id: str
    universe_version_id: str
    max_payload_bytes: int
    proposed_state: TruthAdmissionState

    def __post_init__(self) -> None:
        if not self.feature_materialization_ids or tuple(sorted(self.feature_materialization_ids)) != self.feature_materialization_ids:
            raise ValueError("feature_materialization_ids must be non-empty and canonically sorted")
        if len(set(self.feature_materialization_ids)) != len(self.feature_materialization_ids):
            raise ValueError("feature_materialization_ids must be unique")
        if not all(isinstance(value, str) and value for value in (*self.feature_materialization_ids, self.label_spec_id, self.split_spec_id, self.snapshot_id, self.universe_version_id)):
            raise ValueError("formal Dataset request identities are required")
        if not isinstance(self.max_payload_bytes, int) or isinstance(self.max_payload_bytes, bool) or self.max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be a positive integer")
        if not isinstance(self.proposed_state, TruthAdmissionState):
            raise TypeError("proposed_state must be typed")


@dataclass(frozen=True, slots=True)
class FormalDatasetVersion:
    dataset_version_id: str
    feature_materialization_ids: tuple[str, ...]
    feature_receipts: tuple[PayloadResolutionReceipt, ...]
    label_spec_id: str
    label_payload_id: str
    label_receipt: PayloadResolutionReceipt
    split_spec_id: str
    snapshot_id: str
    universe_version_id: str
    universe_membership_identity: str
    dataset_descriptor: ArtifactDescriptor
    dataset_schema_fingerprint: str
    sample_count: int
    truth_admission: TruthAdmissionState

    def __post_init__(self) -> None:
        if not self.feature_materialization_ids or tuple(sorted(self.feature_materialization_ids)) != self.feature_materialization_ids:
            raise ValueError("formal Dataset feature owners must be non-empty and sorted")
        if len(self.feature_receipts) != len(self.feature_materialization_ids) or not all(
            isinstance(value, PayloadResolutionReceipt) for value in self.feature_receipts
        ):
            raise ValueError("formal Dataset requires one typed P1 receipt per FeatureMaterialization")
        if not isinstance(self.label_receipt, PayloadResolutionReceipt):
            raise TypeError("formal Dataset requires a typed Label P1 receipt")
        if not isinstance(self.dataset_descriptor, ArtifactDescriptor):
            raise TypeError("formal Dataset requires a typed output Artifact")
        if self.dataset_schema_fingerprint != DATASET_SCHEMA_FINGERPRINT:
            raise ValueError("formal Dataset schema is not admitted")
        if not isinstance(self.sample_count, int) or isinstance(self.sample_count, bool) or self.sample_count < 0:
            raise ValueError("formal Dataset sample_count must be non-negative")
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("formal Dataset truth_admission must be typed")
        expected = "fdsv_sha256_" + canonical_sha256(_dataset_identity_payload(
            feature_materialization_ids=self.feature_materialization_ids,
            feature_receipts=self.feature_receipts,
            label_spec_id=self.label_spec_id,
            label_payload_id=self.label_payload_id,
            label_receipt=self.label_receipt,
            split_spec_id=self.split_spec_id,
            snapshot_id=self.snapshot_id,
            universe_version_id=self.universe_version_id,
            universe_membership_identity=self.universe_membership_identity,
            dataset_descriptor=self.dataset_descriptor,
            dataset_schema_fingerprint=self.dataset_schema_fingerprint,
            sample_count=self.sample_count,
            truth_admission=self.truth_admission,
        ))
        if self.dataset_version_id != expected:
            raise ValueError("formal Dataset identity does not match canonical owner content")

    def to_wire(self) -> dict[str, object]:
        return {
            "dataset_version_id": self.dataset_version_id,
            "feature_materialization_ids": list(self.feature_materialization_ids),
            "feature_receipt_ids": [value.receipt_identity for value in self.feature_receipts],
            "label_spec_id": self.label_spec_id,
            "label_payload_id": self.label_payload_id,
            "label_receipt_id": self.label_receipt.receipt_identity,
            "split_spec_id": self.split_spec_id,
            "snapshot_id": self.snapshot_id,
            "universe_version_id": self.universe_version_id,
            "universe_membership_identity": self.universe_membership_identity,
            "dataset_artifact": self.dataset_descriptor.to_artifact_ref(),
            "dataset_schema_fingerprint": self.dataset_schema_fingerprint,
            "sample_count": self.sample_count,
            "truth_admission": self.truth_admission.to_wire(),
        }


def _dataset_identity_payload(
    *,
    feature_materialization_ids: tuple[str, ...],
    feature_receipts: tuple[PayloadResolutionReceipt, ...],
    label_spec_id: str,
    label_payload_id: str,
    label_receipt: PayloadResolutionReceipt,
    split_spec_id: str,
    snapshot_id: str,
    universe_version_id: str,
    universe_membership_identity: str,
    dataset_descriptor: ArtifactDescriptor,
    dataset_schema_fingerprint: str,
    sample_count: int,
    truth_admission: TruthAdmissionState,
) -> dict[str, object]:
    return {
        "feature_materialization_ids": list(feature_materialization_ids),
        "feature_receipt_ids": [value.receipt_identity for value in feature_receipts],
        "label_spec_id": label_spec_id,
        "label_payload_id": label_payload_id,
        "label_receipt_id": label_receipt.receipt_identity,
        "split_spec_id": split_spec_id,
        "snapshot_id": snapshot_id,
        "universe_version_id": universe_version_id,
        "universe_membership_identity": universe_membership_identity,
        "dataset_artifact_id": dataset_descriptor.artifact_id,
        "dataset_sha256": dataset_descriptor.sha256,
        "dataset_byte_size": dataset_descriptor.byte_size,
        "dataset_schema_fingerprint": dataset_schema_fingerprint,
        "sample_count": sample_count,
        "truth_admission": truth_admission.to_wire(),
    }


def _decode_json(payload: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _decode_feature(
    payload: bytes,
    *,
    materialization: FormalFeatureMaterialization,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[float | int | bool | None, ...]]:
    root = _decode_json(payload, "Feature materialization")
    expected = {"schema_version", "schema_fingerprint", "factor_definition_version_id", "input_receipt_id", "context_identity", "instrument_ids", "observation_ids", "value_type", "shape", "values"}
    if set(root) != expected or root["schema_version"] != FACTOR_OUTPUT_SCHEMA_VERSION or root["schema_fingerprint"] != FACTOR_OUTPUT_SCHEMA_FINGERPRINT:
        raise ValueError("Feature materialization schema is not admitted")
    if root["factor_definition_version_id"] != materialization.factor_definition_version_id or root["input_receipt_id"] != materialization.input_receipt.receipt_identity:
        raise ValueError("Feature materialization payload provenance does not match owner object")
    if root["context_identity"] != materialization.input_receipt.context_identity:
        raise ValueError("Feature materialization payload context differs from its verified input receipt")
    instruments = tuple(root["instrument_ids"]) if isinstance(root["instrument_ids"], list) else ()
    observations = tuple(root["observation_ids"]) if isinstance(root["observation_ids"], list) else ()
    shape = [len(instruments), len(observations)]
    if not instruments or not observations or root["shape"] != shape or not isinstance(root["values"], list):
        raise ValueError("Feature materialization coordinates/shape are invalid")
    raw_values = tuple(root["values"])
    values: tuple[float | int | bool | None, ...]
    if root["value_type"] == "FLOAT_SERIES":
        values = tuple(_decimal_value(value, "feature") for value in raw_values)
    elif root["value_type"] == "BOOLEAN_SERIES":
        if any(value is not None and not isinstance(value, bool) for value in raw_values):
            raise ValueError("Boolean feature values must be bool or null")
        values = raw_values
    else:
        raise ValueError("Feature materialization value_type is unsupported")
    if len(values) != shape[0] * shape[1]:
        raise ValueError("Feature materialization value count differs from shape")
    return instruments, observations, values


def _decimal_value(value: object, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} values must be canonical decimal strings or null")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} contains an invalid decimal") from exc
    if not parsed.is_finite() or _decimal_wire(parsed) != value:
        raise ValueError(f"{field} contains a non-canonical or non-finite decimal")
    return float(parsed)


def _decimal_wire(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _number_wire(value: float | int | bool | None) -> str | bool | None:
    if value is None or isinstance(value, bool):
        return value
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("non-finite Dataset feature is forbidden")
    return _decimal_wire(parsed)


class FormalDatasetService:
    def __init__(
        self,
        *,
        snapshots: CanonicalSnapshotRepository,
        universes: CanonicalUniverseRepository,
        materializations: FormalFeatureMaterializationRepository,
        label_specs: LabelSpecRepository,
        split_specs: SplitSpecRepository,
        label_payloads: CanonicalLabelPayloadRepository,
        payload_resolver: CanonicalPayloadResolver,
        artifact_publisher: CanonicalJsonArtifactPublisher,
        dataset_publisher: FormalDatasetPublisher,
    ) -> None:
        self._snapshots = snapshots
        self._universes = universes
        self._materializations = materializations
        self._label_specs = label_specs
        self._split_specs = split_specs
        self._label_payloads = label_payloads
        self._resolver = payload_resolver
        self._publisher = artifact_publisher
        self._dataset_publisher = dataset_publisher

    def build(self, request: FormalDatasetBuildRequest) -> FormalDatasetVersion:
        if not isinstance(request, FormalDatasetBuildRequest):
            raise TypeError("formal Dataset construction requires FormalDatasetBuildRequest")
        snapshot, universe = require_resolved_context(
            snapshots=self._snapshots,
            universes=self._universes,
            snapshot_id=request.snapshot_id,
            universe_version_id=request.universe_version_id,
        )
        label_spec = self._label_specs.get_label_spec(request.label_spec_id)
        split_spec = self._split_specs.get_split_spec(request.split_spec_id)
        if label_spec is None or split_spec is None:
            raise ValueError("formal Dataset requires canonical LabelSpec and SplitSpec owner resolution")
        split_spec.validate_for_label(label_spec)
        materializations: list[FormalFeatureMaterialization] = []
        receipts: list[PayloadResolutionReceipt] = []
        feature_values: list[tuple[float | int | bool | None, ...]] = []
        coordinates: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        for identity in request.feature_materialization_ids:
            materialization = self._materializations.get_materialization(identity)
            if materialization is None:
                raise ValueError("formal Dataset requires canonical FeatureMaterialization owner resolution")
            if (
                materialization.snapshot_id != snapshot.snapshot_id
                or materialization.universe_version_id != universe.universe_version_id
                or materialization.universe_membership_identity != universe.membership_identity
                or materialization.knowledge_cutoff != _utc_time(snapshot.knowledge_cutoff)
            ):
                raise ValueError("FeatureMaterialization context differs from Dataset context")
            result = self._resolver.resolve(
                PayloadResolutionRequest(
                    owner_namespace="v3.factors.materialization",
                    owner_id=materialization.feature_materialization_id,
                    owner_version=materialization.feature_materialization_id,
                    payload_role=FEATURE_VALUES_PAYLOAD_ROLE,
                    context_identity=feature_output_context_identity(materialization),
                    max_bytes=request.max_payload_bytes,
                )
            )
            if result.verified_payload.schema_fingerprint != FACTOR_OUTPUT_SCHEMA_FINGERPRINT:
                raise ValueError("P1 binding does not admit Feature materialization schema")
            instruments, observations, values = _decode_feature(result.verified_payload.payload, materialization=materialization)
            if instruments != universe.instrument_ids:
                raise ValueError("Feature materialization Universe membership/order differs")
            observed_coordinates = (instruments, observations)
            if coordinates is not None and observed_coordinates != coordinates:
                raise ValueError("Feature materializations use different sample coordinates")
            coordinates = observed_coordinates
            materializations.append(materialization)
            receipts.append(result.receipt)
            feature_values.append(values)
        assert coordinates is not None
        knowledge = _utc_time(snapshot.knowledge_cutoff)
        label_context = label_payload_context_identity(
            snapshot_id=snapshot.snapshot_id,
            universe_version_id=universe.universe_version_id,
            membership_identity=universe.membership_identity,
            calendar_version_id=snapshot.calendar_version_id,
            knowledge_cutoff=knowledge,
            label_spec=label_spec,
        )
        label_owner = self._label_payloads.get_label_payload(label_spec.label_spec_id, label_context)
        if label_owner is None or label_owner.context_identity != label_context:
            raise ValueError("formal Dataset requires canonical Label payload owner resolution")
        label_result = self._resolver.resolve(
            PayloadResolutionRequest(
                owner_namespace="v3.data_truth.labels",
                owner_id=label_spec.label_spec_id,
                owner_version=label_owner.label_payload_id,
                payload_role=LABEL_PAYLOAD_ROLE,
                context_identity=label_context,
                max_bytes=request.max_payload_bytes,
            )
        )
        if label_result.verified_payload.schema_fingerprint != LABEL_SCHEMA_FINGERPRINT:
            raise ValueError("P1 binding does not admit Label payload schema")
        labels = _decode_json(label_result.verified_payload.payload, "Label payload")
        expected_label_keys = {
            "schema_version", "schema_fingerprint", "context_identity", "label_spec_id",
            "snapshot_id", "universe_version_id", "calendar_version_id", "knowledge_cutoff",
            "horizon_observations", "instrument_ids", "observation_ids", "shape", "values",
        }
        instruments, observations = coordinates
        if set(labels) != expected_label_keys or labels["schema_version"] != LABEL_SCHEMA_VERSION or labels["schema_fingerprint"] != LABEL_SCHEMA_FINGERPRINT:
            raise ValueError("Label payload schema is not admitted")
        if labels["context_identity"] != label_context or labels["label_spec_id"] != label_spec.label_spec_id or labels["horizon_observations"] != label_spec.horizon_observations:
            raise ValueError("Label payload spec/horizon/context mismatch")
        if (
            labels["snapshot_id"] != snapshot.snapshot_id
            or labels["universe_version_id"] != universe.universe_version_id
            or labels["calendar_version_id"] != snapshot.calendar_version_id
            or labels["knowledge_cutoff"] != knowledge
        ):
            raise ValueError("Label payload canonical owner context mismatch")
        if labels["instrument_ids"] != list(instruments) or labels["observation_ids"] != list(observations) or labels["shape"] != [len(instruments), len(observations)] or not isinstance(labels["values"], list):
            raise ValueError("Label payload coordinates/shape mismatch")
        label_values = tuple(labels["values"])
        if len(label_values) != len(instruments) * len(observations):
            raise ValueError("Label value count differs from shape")
        samples: list[dict[str, object]] = []
        for instrument_index, instrument_id in enumerate(instruments):
            for observation_index, observation_id in enumerate(observations):
                flat = instrument_index * len(observations) + observation_index
                label_value = label_values[flat]
                if label_value is None:
                    continue
                _decimal_value(label_value, "label")
                split = _split_for_ordinal(split_spec, observation_index)
                if split is None:
                    continue
                row = [values[flat] for values in feature_values]
                samples.append(
                    {
                        "sample_id": "smp_sha256_" + canonical_sha256({"instrument_id": instrument_id, "observation_id": observation_id, "label_spec_id": label_spec.label_spec_id}),
                        "instrument_id": instrument_id,
                        "observation_id": observation_id,
                        "split": split,
                        "features": [_number_wire(value) for value in row],
                        "label": label_value,
                    }
                )
        payload: dict[str, object] = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "schema_fingerprint": DATASET_SCHEMA_FINGERPRINT,
            "snapshot_id": snapshot.snapshot_id,
            "universe_version_id": universe.universe_version_id,
            "universe_membership_identity": universe.membership_identity,
            "knowledge_cutoff": knowledge,
            "feature_materialization_ids": list(request.feature_materialization_ids),
            "feature_receipt_ids": [value.receipt_identity for value in receipts],
            "label_spec_id": label_spec.label_spec_id,
            "label_payload_id": label_owner.label_payload_id,
            "label_receipt_id": label_result.receipt.receipt_identity,
            "split_spec_id": split_spec.split_spec_id,
            "feature_order": list(request.feature_materialization_ids),
            "samples": samples,
        }
        descriptor = self._publisher.publish_canonical_json(
            payload,
            semantic_role=DATASET_ARTIFACT_ROLE,
            provenance_entity_id=label_result.receipt.receipt_identity,
            schema_fingerprint=DATASET_SCHEMA_FINGERPRINT,
        )
        upstreams = [
            UpstreamRequirement(snapshot.snapshot_id, snapshot.truth_admission),
            UpstreamRequirement(universe.membership_identity, universe.truth_admission),
            *(UpstreamRequirement(value.feature_materialization_id, value.truth_admission) for value in materializations),
            UpstreamRequirement(label_owner.label_payload_id, label_owner.truth_admission),
        ]
        truth = propagate_downstream_ceiling(request.proposed_state, upstreams)
        identity = _dataset_identity_payload(
            feature_materialization_ids=request.feature_materialization_ids,
            feature_receipts=tuple(receipts),
            label_spec_id=label_spec.label_spec_id,
            label_payload_id=label_owner.label_payload_id,
            label_receipt=label_result.receipt,
            split_spec_id=split_spec.split_spec_id,
            snapshot_id=snapshot.snapshot_id,
            universe_version_id=universe.universe_version_id,
            universe_membership_identity=universe.membership_identity,
            dataset_descriptor=descriptor,
            dataset_schema_fingerprint=DATASET_SCHEMA_FINGERPRINT,
            sample_count=len(samples),
            truth_admission=truth,
        )
        dataset = FormalDatasetVersion(
            "fdsv_sha256_" + canonical_sha256(identity),
            request.feature_materialization_ids,
            tuple(receipts),
            label_spec.label_spec_id,
            label_owner.label_payload_id,
            label_result.receipt,
            split_spec.split_spec_id,
            snapshot.snapshot_id,
            universe.universe_version_id,
            universe.membership_identity,
            descriptor,
            DATASET_SCHEMA_FINGERPRINT,
            len(samples),
            truth,
        )
        return self._dataset_publisher.publish_dataset(dataset)


def _split_for_ordinal(split: SplitSpec, ordinal: int) -> str | None:
    if split.train_start <= ordinal <= split.train_end:
        return "TRAIN"
    if split.validation_start <= ordinal <= split.validation_end:
        return "VALIDATION"
    if split.test_start <= ordinal <= split.test_end:
        return "TEST"
    return None


__all__ = [
    "CanonicalHistoricalLabelSource",
    "CanonicalLabelPayloadPublisher",
    "CanonicalLabelPayloadRepository",
    "CanonicalLabelPayloadVersion",
    "DATASET_ARTIFACT_ROLE",
    "DATASET_SCHEMA_FINGERPRINT",
    "DATASET_SCHEMA_VERSION",
    "FEATURE_VALUES_PAYLOAD_ROLE",
    "FormalDatasetBuildRequest",
    "FormalDatasetPublisher",
    "FormalDatasetRepository",
    "FormalDatasetService",
    "FormalDatasetVersion",
    "FormalFeatureMaterializationRepository",
    "FormalLabelService",
    "LABEL_SOURCE_PAYLOAD_ROLE",
    "LABEL_PAYLOAD_ROLE",
    "LABEL_SCHEMA_FINGERPRINT",
    "LABEL_SCHEMA_VERSION",
    "LabelSpecRepository",
    "SplitSpecRepository",
    "DeterministicForwardReturnLabelEngine",
    "feature_output_context_identity",
    "label_payload_context_identity",
    "label_source_payload_context_identity",
]
