"""A1 formal Factor boundary: owner refs -> P1 verified bytes -> pure evaluator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Protocol

from v3_backend.contracts.common.truth_admission import (
    TruthAdmissionState,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.data_truth.formal import (
    CanonicalSnapshotRepository,
    CanonicalUniverseRepository,
    CanonicalSnapshotVersion,
    CanonicalUniverseVersion,
    require_resolved_context,
)
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadResolutionReceipt,
    PayloadResolutionRequest,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

from .evaluator import DeterministicReferenceEvaluator, EvaluationResult
from .ir import FactorDefinitionVersion, ValueType


FACTOR_INPUT_SCHEMA_VERSION = "v3.factor-input-payload/1.0.0"
FACTOR_OUTPUT_SCHEMA_VERSION = "v3.feature-materialization-payload/1.0.0"
FACTOR_INPUT_PAYLOAD_ROLE = "FACTOR_INPUT"
FACTOR_OUTPUT_ARTIFACT_ROLE = "FEATURE_MATERIALIZATION"
_SCHEMA_FINGERPRINT = "sch_sha256_" + canonical_sha256(
    {
        "schema_version": FACTOR_INPUT_SCHEMA_VERSION,
        "coordinates": ["instrument_ids", "observation_ids"],
        "field": ["name", "value_type", "shape", "values"],
        "missing": "JSON_NULL",
        "numeric_wire": "CANONICAL_DECIMAL_STRING",
        "order": "instrument-major-observation-minor",
    }
)
FACTOR_INPUT_SCHEMA_FINGERPRINT = _SCHEMA_FINGERPRINT
FACTOR_OUTPUT_SCHEMA_FINGERPRINT = "sch_sha256_" + canonical_sha256(
    {
        "schema_version": FACTOR_OUTPUT_SCHEMA_VERSION,
        "coordinates": ["instrument_ids", "observation_ids"],
        "field": ["factor_definition_version_id", "value_type", "shape", "values"],
        "missing": "JSON_NULL",
        "numeric_wire": "CANONICAL_DECIMAL_STRING",
        "order": "instrument-major-observation-minor",
    }
)


def _object(value: object, *, keys: set[str], field: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{field} keys must be exactly {sorted(keys)}")
    return value


def _utc_time(value) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _texts(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    result = tuple(value)
    if any(not isinstance(item, str) or not item or item != item.strip() for item in result):
        raise ValueError(f"{field} entries must be non-empty strings")
    if len(set(result)) != len(result):
        raise ValueError(f"{field} entries must be unique")
    return result


def _decode_float_wire(value: object, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} FLOAT_SERIES values must be canonical decimal strings or null")
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


def _float_wire(value: float | int | None) -> str | None:
    if value is None:
        return None
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("non-finite Factor output is forbidden")
    return _decimal_wire(parsed)


class FactorDefinitionRepository(Protocol):
    def get_definition(self, factor_definition_version_id: str) -> FactorDefinitionVersion | None: ...


class FactorPayloadContextRepository(Protocol):
    def get_factor_context(
        self, context_identity: str
    ) -> tuple[CanonicalSnapshotVersion, CanonicalUniverseVersion, FactorDefinitionVersion] | None: ...


class CanonicalJsonArtifactPublisher(Protocol):
    def publish_canonical_json(
        self,
        payload: Mapping[str, object],
        *,
        semantic_role: str,
        provenance_entity_id: str,
        schema_fingerprint: str,
    ) -> ArtifactDescriptor: ...


class FormalFeatureMaterializationPublisher(Protocol):
    def publish_materialization(
        self, materialization: "FormalFeatureMaterialization"
    ) -> "FormalFeatureMaterialization": ...


@dataclass(frozen=True, slots=True)
class FactorInputPayload:
    snapshot_id: str
    universe_version_id: str
    membership_identity: str
    source_data_truth_id: str
    as_of: str
    knowledge_cutoff: str
    instrument_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    features: Mapping[str, tuple[float | int | bool | None, ...]]
    feature_types: Mapping[str, ValueType]

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.instrument_ids), len(self.observation_ids)

    @classmethod
    def decode_verified(
        cls,
        payload: bytes,
        *,
        snapshot: CanonicalSnapshotVersion,
        universe: CanonicalUniverseVersion,
        definition: FactorDefinitionVersion,
    ) -> "FactorInputPayload":
        return cls._decode_verified_with_types(
            payload,
            snapshot=snapshot,
            universe=universe,
            expected_types=DeterministicReferenceEvaluator._feature_types(definition.root),
        )

    @classmethod
    def decode_verified_source_field(
        cls,
        payload: bytes,
        *,
        snapshot: CanonicalSnapshotVersion,
        universe: CanonicalUniverseVersion,
        source_field: str,
    ) -> "FactorInputPayload":
        if not isinstance(source_field, str) or not source_field:
            raise ValueError("canonical source_field is required")
        return cls._decode_verified_with_types(
            payload,
            snapshot=snapshot,
            universe=universe,
            expected_types={source_field: ValueType.FLOAT_SERIES},
        )

    @classmethod
    def _decode_verified_with_types(
        cls,
        payload: bytes,
        *,
        snapshot: CanonicalSnapshotVersion,
        universe: CanonicalUniverseVersion,
        expected_types: Mapping[str, ValueType],
    ) -> "FactorInputPayload":
        if not expected_types:
            raise ValueError("verified Factor input requires at least one exact field")
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Factor input must be UTF-8 JSON") from exc
        root = _object(
            raw,
            keys={"schema_version", "schema_fingerprint", "context", "instrument_ids", "observation_ids", "fields"},
            field="Factor input",
        )
        if root["schema_version"] != FACTOR_INPUT_SCHEMA_VERSION or root["schema_fingerprint"] != FACTOR_INPUT_SCHEMA_FINGERPRINT:
            raise ValueError("unsupported Factor input payload schema")
        context = _object(
            root["context"],
            keys={"snapshot_id", "universe_version_id", "membership_identity", "source_data_truth_id", "as_of", "knowledge_cutoff"},
            field="Factor input context",
        )
        expected_context = {
            "snapshot_id": snapshot.snapshot_id,
            "universe_version_id": universe.universe_version_id,
            "membership_identity": universe.membership_identity,
            "source_data_truth_id": snapshot.source_data_truth_id,
            "as_of": snapshot.as_of.isoformat(),
            "knowledge_cutoff": _utc_time(snapshot.knowledge_cutoff),
        }
        if context != expected_context:
            raise ValueError("Factor input payload context does not match canonical Snapshot/Universe")
        instruments = _texts(root["instrument_ids"], "instrument_ids")
        observations = _texts(root["observation_ids"], "observation_ids")
        if instruments != universe.instrument_ids:
            raise ValueError("Factor input instrument order/membership does not match Universe")
        if not isinstance(root["fields"], list) or not root["fields"]:
            raise ValueError("fields must be a non-empty array")
        values: dict[str, tuple[float | int | bool | None, ...]] = {}
        types: dict[str, ValueType] = {}
        expected_shape = [len(instruments), len(observations)]
        for index, item in enumerate(root["fields"]):
            field = _object(item, keys={"name", "value_type", "shape", "values"}, field=f"fields[{index}]")
            name = field["name"]
            if not isinstance(name, str) or name in values:
                raise ValueError("field names must be unique strings")
            expected_type = expected_types.get(name)
            if expected_type is None or field["value_type"] != expected_type.value:
                raise ValueError("Factor input fields/types must exactly match FactorDefinitionVersion")
            if field["shape"] != expected_shape or not isinstance(field["values"], list):
                raise ValueError("Factor input field shape is invalid")
            flattened = tuple(field["values"])
            if len(flattened) != expected_shape[0] * expected_shape[1]:
                raise ValueError("Factor input value count does not match declared shape")
            if expected_type is ValueType.FLOAT_SERIES:
                values[name] = tuple(_decode_float_wire(value, name) for value in flattened)
            else:
                if any(value is not None and not isinstance(value, bool) for value in flattened):
                    raise ValueError(f"{name} BOOLEAN_SERIES values must be bool or null")
                values[name] = flattened
            types[name] = expected_type
        if set(values) != set(expected_types):
            raise ValueError("Factor input fields must exactly match FactorDefinitionVersion")
        return cls(
            snapshot.snapshot_id,
            universe.universe_version_id,
            universe.membership_identity,
            snapshot.source_data_truth_id,
            snapshot.as_of.isoformat(),
            expected_context["knowledge_cutoff"],
            instruments,
            observations,
            values,
            types,
        )


def factor_payload_context_identity(
    *,
    snapshot: CanonicalSnapshotVersion,
    universe: CanonicalUniverseVersion,
    definition: FactorDefinitionVersion,
) -> str:
    return "fctx_sha256_" + canonical_sha256(
        {
            "snapshot": snapshot.to_context_wire(),
            "universe": universe.to_context_wire(),
            "factor_definition_version_id": definition.factor_definition_version_id,
            "required_fields": list(definition.metadata.input_features),
            "payload_schema_fingerprint": FACTOR_INPUT_SCHEMA_FINGERPRINT,
        }
    )


@dataclass(frozen=True, slots=True)
class FormalFactorEvaluationRequest:
    factor_definition_version_id: str
    snapshot_id: str
    universe_version_id: str
    max_input_bytes: int
    proposed_state: TruthAdmissionState

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.factor_definition_version_id, self.snapshot_id, self.universe_version_id)):
            raise ValueError("formal Factor request identities are required")
        if not isinstance(self.max_input_bytes, int) or isinstance(self.max_input_bytes, bool) or self.max_input_bytes <= 0:
            raise ValueError("max_input_bytes must be a positive integer")
        if not isinstance(self.proposed_state, TruthAdmissionState):
            raise TypeError("proposed_state must be typed")


def _feature_materialization_identity_payload(
    *,
    factor_definition_version_id: str,
    snapshot_id: str,
    universe_version_id: str,
    universe_membership_identity: str,
    knowledge_cutoff: str,
    evaluator_version: str,
    input_receipt: PayloadResolutionReceipt,
    output_descriptor: ArtifactDescriptor,
    output_schema_fingerprint: str,
    truth_admission: TruthAdmissionState,
) -> dict[str, object]:
    return {
        "factor_definition_version_id": factor_definition_version_id,
        "snapshot_id": snapshot_id,
        "universe_version_id": universe_version_id,
        "universe_membership_identity": universe_membership_identity,
        "knowledge_cutoff": knowledge_cutoff,
        "evaluator_version": evaluator_version,
        "input_receipt_id": input_receipt.receipt_identity,
        "output_artifact_id": output_descriptor.artifact_id,
        "output_sha256": output_descriptor.sha256,
        "output_byte_size": output_descriptor.byte_size,
        "output_schema_fingerprint": output_schema_fingerprint,
        "truth_admission": truth_admission.to_wire(),
    }


@dataclass(frozen=True, slots=True)
class FormalFeatureMaterialization:
    feature_materialization_id: str
    factor_definition_version_id: str
    snapshot_id: str
    universe_version_id: str
    universe_membership_identity: str
    knowledge_cutoff: str
    evaluator_version: str
    input_receipt: PayloadResolutionReceipt
    output_descriptor: ArtifactDescriptor
    output_schema_fingerprint: str
    row_count: int
    missing_count: int
    truth_admission: TruthAdmissionState

    def __post_init__(self) -> None:
        if not isinstance(self.input_receipt, PayloadResolutionReceipt):
            raise TypeError("FeatureMaterialization requires a typed P1 input receipt")
        if not isinstance(self.output_descriptor, ArtifactDescriptor):
            raise TypeError("FeatureMaterialization requires a typed output Artifact")
        if self.output_schema_fingerprint != FACTOR_OUTPUT_SCHEMA_FINGERPRINT:
            raise ValueError("FeatureMaterialization output schema is not admitted")
        if not isinstance(self.row_count, int) or isinstance(self.row_count, bool) or self.row_count < 0:
            raise ValueError("FeatureMaterialization row_count must be non-negative")
        if not isinstance(self.missing_count, int) or isinstance(self.missing_count, bool) or not 0 <= self.missing_count <= self.row_count:
            raise ValueError("FeatureMaterialization missing_count is invalid")
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("FeatureMaterialization truth_admission must be typed")
        expected = "ffm_sha256_" + canonical_sha256(
            _feature_materialization_identity_payload(
                factor_definition_version_id=self.factor_definition_version_id,
                snapshot_id=self.snapshot_id,
                universe_version_id=self.universe_version_id,
                universe_membership_identity=self.universe_membership_identity,
                knowledge_cutoff=self.knowledge_cutoff,
                evaluator_version=self.evaluator_version,
                input_receipt=self.input_receipt,
                output_descriptor=self.output_descriptor,
                output_schema_fingerprint=self.output_schema_fingerprint,
                truth_admission=self.truth_admission,
            )
        )
        if self.feature_materialization_id != expected:
            raise ValueError("FeatureMaterialization identity does not match canonical owner content")

    def to_wire(self) -> dict[str, object]:
        return {
            "feature_materialization_id": self.feature_materialization_id,
            "factor_definition_version_id": self.factor_definition_version_id,
            "snapshot_id": self.snapshot_id,
            "universe_version_id": self.universe_version_id,
            "universe_membership_identity": self.universe_membership_identity,
            "knowledge_cutoff": self.knowledge_cutoff,
            "evaluator_version": self.evaluator_version,
            "input_receipt_id": self.input_receipt.receipt_identity,
            "input_artifact_id": self.input_receipt.artifact_id,
            "output_artifact": self.output_descriptor.to_artifact_ref(),
            "output_schema_fingerprint": self.output_schema_fingerprint,
            "row_count": self.row_count,
            "missing_count": self.missing_count,
            "truth_admission": self.truth_admission.to_wire(),
        }


class FormalFactorEvaluationService:
    def __init__(
        self,
        *,
        snapshots: CanonicalSnapshotRepository,
        universes: CanonicalUniverseRepository,
        definitions: FactorDefinitionRepository,
        payload_resolver: CanonicalPayloadResolver,
        evaluator: DeterministicReferenceEvaluator,
        artifact_publisher: CanonicalJsonArtifactPublisher,
        materialization_publisher: FormalFeatureMaterializationPublisher,
    ) -> None:
        self._snapshots = snapshots
        self._universes = universes
        self._definitions = definitions
        self._resolver = payload_resolver
        self._evaluator = evaluator
        self._publisher = artifact_publisher
        self._materialization_publisher = materialization_publisher

    def evaluate(self, request: FormalFactorEvaluationRequest) -> FormalFeatureMaterialization:
        if not isinstance(request, FormalFactorEvaluationRequest):
            raise TypeError("formal Factor execution requires FormalFactorEvaluationRequest")
        snapshot, universe = require_resolved_context(
            snapshots=self._snapshots,
            universes=self._universes,
            snapshot_id=request.snapshot_id,
            universe_version_id=request.universe_version_id,
        )
        definition = self._definitions.get_definition(request.factor_definition_version_id)
        if definition is None:
            raise ValueError("formal path requires canonical FactorDefinitionVersion owner resolution")
        context_identity = factor_payload_context_identity(snapshot=snapshot, universe=universe, definition=definition)
        resolution = self._resolver.resolve(
            PayloadResolutionRequest(
                owner_namespace="v3.data_truth.snapshot",
                owner_id=snapshot.snapshot_id,
                owner_version=snapshot.snapshot_id,
                payload_role=FACTOR_INPUT_PAYLOAD_ROLE,
                context_identity=context_identity,
                max_bytes=request.max_input_bytes,
            )
        )
        verified = resolution.verified_payload
        if verified.schema_fingerprint != FACTOR_INPUT_SCHEMA_FINGERPRINT:
            raise ValueError("P1 binding does not admit the Factor input schema")
        decoded = FactorInputPayload.decode_verified(
            verified.payload,
            snapshot=snapshot,
            universe=universe,
            definition=definition,
        )
        result: EvaluationResult = self._evaluator.evaluate(definition, decoded.features)
        output_payload: dict[str, object] = {
            "schema_version": FACTOR_OUTPUT_SCHEMA_VERSION,
            "schema_fingerprint": FACTOR_OUTPUT_SCHEMA_FINGERPRINT,
            "factor_definition_version_id": definition.factor_definition_version_id,
            "input_receipt_id": resolution.receipt.receipt_identity,
            "context_identity": context_identity,
            "instrument_ids": list(decoded.instrument_ids),
            "observation_ids": list(decoded.observation_ids),
            "value_type": result.output_type.value,
            "shape": list(decoded.shape),
            "values": [
                _float_wire(value) if result.output_type is ValueType.FLOAT_SERIES else value
                for value in result.values
            ],
        }
        descriptor = self._publisher.publish_canonical_json(
            output_payload,
            semantic_role=FACTOR_OUTPUT_ARTIFACT_ROLE,
            provenance_entity_id=definition.factor_definition_version_id,
            schema_fingerprint=FACTOR_OUTPUT_SCHEMA_FINGERPRINT,
        )
        truth = propagate_downstream_ceiling(
            request.proposed_state,
            (
                UpstreamRequirement(snapshot.snapshot_id, snapshot.truth_admission),
                UpstreamRequirement(universe.membership_identity, universe.truth_admission),
            ),
        )
        identity_payload = _feature_materialization_identity_payload(
            factor_definition_version_id=definition.factor_definition_version_id,
            snapshot_id=snapshot.snapshot_id,
            universe_version_id=universe.universe_version_id,
            universe_membership_identity=universe.membership_identity,
            knowledge_cutoff=decoded.knowledge_cutoff,
            evaluator_version=result.evaluator_version,
            input_receipt=resolution.receipt,
            output_descriptor=descriptor,
            output_schema_fingerprint=FACTOR_OUTPUT_SCHEMA_FINGERPRINT,
            truth_admission=truth,
        )
        materialization = FormalFeatureMaterialization(
            "ffm_sha256_" + canonical_sha256(identity_payload),
            definition.factor_definition_version_id,
            snapshot.snapshot_id,
            universe.universe_version_id,
            universe.membership_identity,
            decoded.knowledge_cutoff,
            result.evaluator_version,
            resolution.receipt,
            descriptor,
            FACTOR_OUTPUT_SCHEMA_FINGERPRINT,
            len(result.values),
            sum(value is None for value in result.values),
            truth,
        )
        return self._materialization_publisher.publish_materialization(materialization)


__all__ = [
    "CanonicalJsonArtifactPublisher",
    "FACTOR_INPUT_PAYLOAD_ROLE",
    "FACTOR_INPUT_SCHEMA_FINGERPRINT",
    "FACTOR_INPUT_SCHEMA_VERSION",
    "FACTOR_OUTPUT_ARTIFACT_ROLE",
    "FACTOR_OUTPUT_SCHEMA_FINGERPRINT",
    "FACTOR_OUTPUT_SCHEMA_VERSION",
    "FactorDefinitionRepository",
    "FactorPayloadContextRepository",
    "FactorInputPayload",
    "FormalFactorEvaluationRequest",
    "FormalFactorEvaluationService",
    "FormalFeatureMaterialization",
    "FormalFeatureMaterializationPublisher",
    "factor_payload_context_identity",
]
