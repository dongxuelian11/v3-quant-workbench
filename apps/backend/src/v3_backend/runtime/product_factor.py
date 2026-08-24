"""V1.1 Factor application seams over verified local Snapshot partitions."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from v3_backend.adapters.tdx_formula import (
    TdxTranslator,
    registered_tdx_data_semantic_profile,
)
from v3_backend.domain.factors import (
    DeterministicPanelEvaluator,
    FactorDefinitionVersion,
    PanelInputRow,
    PanelValueRow,
    ValueType,
    panel_operator_registry,
)
from v3_backend.domain.factors.analysis import FactorAnalysisService, FactorAnalysisSpecV1
from v3_backend.domain.artifacts.exceptions import ArtifactError
from v3_backend.errors.exceptions import (
    CapabilityUnavailableError,
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256

from .product_data import (
    LOCAL_DATASET,
    LOCAL_VALIDATION_CHECKS,
    PARTITION_MANIFEST_ROLE,
    PARTITION_ROLE,
)
from .product_runtime import (
    _accept_outcome_json,
    _canonical_request_hash,
    classify_execution_error,
    connect_catalog,
    wire_time,
)

if TYPE_CHECKING:
    from .product_runtime import ProductRuntime


_MANIFEST_SCHEMA = "v3.local-a-share-eod-manifest/1.0.0"
_PARTITION_SCHEMA = "v3.local-a-share-eod-partition/1.0.0"
_DATA_SCHEMA = "v3.local-a-share-eod/1.0.0"
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_PARTITION_BYTES = 8 * 1024 * 1024
_FACTOR_FORMULA_ROLE = "FACTOR_FORMULA_DOCUMENT"
_FACTOR_DEFINITION_ROLE = "FACTOR_DEFINITION"
_FACTOR_PARTITION_ROLE = "FACTOR_MATERIALIZATION_PARTITION"
_FACTOR_MATERIALIZATION_ROLE = "FACTOR_MATERIALIZATION"
_FACTOR_ANALYSIS_ROLE = "FACTOR_ANALYSIS"
_FACTOR_READ_MODEL_ROLE = "PRODUCT_FACTOR_STUDY_READ_MODEL"
_FACTOR_READ_MODEL_SCHEMA = "v3.product-factor-study-read-model/1.0.0"
_FACTOR_MATERIALIZATION_SCHEMA = "v3.factor-materialization-manifest/1.0.0"
_FACTOR_PARTITION_SCHEMA = "v3.factor-materialization-partition/1.0.0"
_PREVIEW_ROW_LIMIT = 5_000
PRODUCT_FACTOR_STUDY_OPERATION = "ProductEntryService.v1.submitFactorStudy"
_FACTOR_CONTEXT_SCHEMA = "v3.product-factor-study-context/1.1.0"


@dataclass(frozen=True, slots=True)
class ResolvedLocalSnapshotPanel:
    project_id: str
    snapshot_id: str
    universe_version_id: str
    manifest_artifact_id: str
    manifest_sha256: str
    membership: tuple[str, ...]
    rows: tuple[PanelInputRow, ...]


def _closed(value: object, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise TruthPreconditionFailedError(f"{label} does not match the closed canonical shape")
    return value


def _finite_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise TruthPreconditionFailedError(f"{label} is not canonical numeric text")
    try:
        normalized = float(value)
    except ValueError as error:
        raise TruthPreconditionFailedError(f"{label} is not canonical numeric text") from error
    if not math.isfinite(normalized):
        raise TruthPreconditionFailedError(f"{label} is non-finite")
    return normalized


class ManifestAwareLocalSnapshotReader:
    """Resolve exact manifest, partition and Universe bytes before Factor math."""

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def resolve(
        self,
        *,
        project_id: str,
        snapshot_id: str,
        universe_version_id: str,
    ) -> ResolvedLocalSnapshotPanel:
        self.product.require_project(project_id)
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            owner = connection.execute(
                """
                SELECT s.manifest_artifact_id,s.content_hash,s.state,
                       u.membership_artifact_id,u.state,d.project_id
                FROM data_snapshot AS s
                JOIN universe_version AS u ON u.snapshot_id=s.snapshot_id
                JOIN universe_definition AS d
                  ON d.universe_definition_id=u.universe_definition_id
                WHERE s.snapshot_id=? AND u.universe_version_id=?
                """,
                (snapshot_id, universe_version_id),
            ).fetchone()
            if owner is None or str(owner[5]) != project_id:
                raise NotFoundError("Snapshot/Universe is not reachable from the project")
            if str(owner[2]) != "PUBLISHED" or str(owner[4]) != "PUBLISHED":
                raise TruthPreconditionFailedError("Snapshot and Universe must both be PUBLISHED")
            validations = connection.execute(
                """
                SELECT check_code,state,severity FROM snapshot_validation
                WHERE snapshot_id=? ORDER BY check_code
                """,
                (snapshot_id,),
            ).fetchall()
            observed_validations = {
                str(row[0]): (str(row[1]), str(row[2])) for row in validations
            }
            expected_validations = {
                code: ("PASS", "BLOCKING") for code in LOCAL_VALIDATION_CHECKS
            }
            if observed_validations != expected_validations:
                raise TruthPreconditionFailedError("Snapshot blocking validations are incomplete")
            partition_rows = connection.execute(
                """
                SELECT partition_key,parquet_artifact_id,row_count,
                       min_effective_time,max_effective_time
                FROM snapshot_partition
                WHERE snapshot_id=? AND logical_dataset=?
                ORDER BY partition_key
                """,
                (snapshot_id, LOCAL_DATASET),
            ).fetchall()
            reachable_artifacts = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT artifact_id FROM artifact_reference
                    WHERE owner_type='Project' AND owner_id=? AND state='ACTIVE'
                    """,
                    (project_id,),
                ).fetchall()
            }
        finally:
            connection.close()

        manifest_artifact_id = str(owner[0])
        manifest_hash = str(owner[1])
        if manifest_artifact_id not in reachable_artifacts:
            raise TruthPreconditionFailedError("Snapshot manifest is not project-reachable")
        manifest_descriptor = self.product.require_published_artifact(manifest_artifact_id)
        if (
            manifest_descriptor["semantic_role"] != PARTITION_MANIFEST_ROLE
            or manifest_descriptor["sha256"] != manifest_hash
            or manifest_artifact_id != "art_sha256_" + manifest_hash
        ):
            raise TruthPreconditionFailedError("Snapshot manifest descriptor binding mismatch")
        manifest = self._read_json(manifest_artifact_id, _MAX_MANIFEST_BYTES, "Snapshot manifest")
        manifest = _closed(
            manifest,
            {
                "schema_version", "data_schema_version", "adjustment", "amount_unit",
                "timezone", "volume_unit", "row_count", "instrument_count", "partitions",
            },
            "Snapshot manifest",
        )
        if (
            manifest["schema_version"] != _MANIFEST_SCHEMA
            or manifest["data_schema_version"] != _DATA_SCHEMA
            or manifest["adjustment"] != "UNADJUSTED"
            or manifest["amount_unit"] != "CNY"
            or manifest["timezone"] != "Asia/Shanghai"
            or manifest["volume_unit"] != "SHARES"
        ):
            raise TruthPreconditionFailedError("Snapshot manifest semantics are not admitted")

        membership_artifact_id = str(owner[3])
        if membership_artifact_id not in reachable_artifacts:
            raise TruthPreconditionFailedError("Universe membership is not project-reachable")
        membership = _closed(
            self._read_json(membership_artifact_id, _MAX_MANIFEST_BYTES, "Universe membership"),
            {"schema_version", "snapshot_id", "role", "instrument_ids"},
            "Universe membership",
        )
        if (
            membership["schema_version"] != "v3.user-defined-static-universe/1.0.0"
            or membership["snapshot_id"] != snapshot_id
            or membership["role"] != "USER_DEFINED_STATIC"
            or not isinstance(membership["instrument_ids"], list)
        ):
            raise TruthPreconditionFailedError("Universe membership binding mismatch")
        members = tuple(membership["instrument_ids"])
        if not members or any(not isinstance(value, str) for value in members):
            raise TruthPreconditionFailedError("Universe membership is invalid")

        declared = manifest["partitions"]
        if not isinstance(declared, list) or len(declared) != len(partition_rows):
            raise TruthPreconditionFailedError("Snapshot partition count differs from manifest")
        resolved: list[PanelInputRow] = []
        for ordinal, (declared_item, persisted) in enumerate(zip(declared, partition_rows, strict=True)):
            declaration = _closed(
                declared_item,
                {"partition_key", "content_hash", "row_count", "min_session_date", "max_session_date"},
                "Snapshot partition declaration",
            )
            partition_key = f"{ordinal:08d}"
            artifact_id = str(persisted[1])
            partition_hash = str(declaration["content_hash"])
            if (
                declaration["partition_key"] != partition_key
                or str(persisted[0]) != partition_key
                or int(persisted[2]) != declaration["row_count"]
                or artifact_id != "art_sha256_" + partition_hash
                or artifact_id not in reachable_artifacts
            ):
                raise TruthPreconditionFailedError("Snapshot partition persistence/manifest mismatch")
            descriptor = self.product.require_published_artifact(artifact_id)
            if (
                descriptor["semantic_role"] != PARTITION_ROLE
                or descriptor["sha256"] != partition_hash
                or int(descriptor["byte_size"]) > _MAX_PARTITION_BYTES
            ):
                raise TruthPreconditionFailedError("Snapshot partition descriptor mismatch")
            partition = _closed(
                self._read_json(artifact_id, _MAX_PARTITION_BYTES, "Snapshot partition"),
                {
                    "schema_version", "data_schema_version", "partition_key", "adjustment",
                    "amount_unit", "timezone", "volume_unit", "rows",
                },
                "Snapshot partition",
            )
            if (
                partition["schema_version"] != _PARTITION_SCHEMA
                or partition["data_schema_version"] != _DATA_SCHEMA
                or partition["partition_key"] != partition_key
                or partition["adjustment"] != "UNADJUSTED"
                or partition["amount_unit"] != "CNY"
                or partition["timezone"] != "Asia/Shanghai"
                or partition["volume_unit"] != "SHARES"
                or not isinstance(partition["rows"], list)
                or len(partition["rows"]) != int(persisted[2])
            ):
                raise TruthPreconditionFailedError("Snapshot partition semantics mismatch")
            resolved.extend(
                self._row(value, artifact_id=artifact_id, partition_hash=partition_hash)
                for value in partition["rows"]
            )

        keys = tuple((row.session_date, row.instrument_id) for row in resolved)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise TruthPreconditionFailedError("Snapshot rows are not canonical and unique")
        if set(row.instrument_id for row in resolved) != set(members):
            raise TruthPreconditionFailedError("Snapshot rows do not equal exact Universe membership")
        if len(resolved) != manifest["row_count"]:
            raise TruthPreconditionFailedError("Snapshot manifest row_count mismatch")
        return ResolvedLocalSnapshotPanel(
            project_id,
            snapshot_id,
            universe_version_id,
            manifest_artifact_id,
            manifest_hash,
            tuple(members),
            tuple(resolved),
        )

    def _read_json(self, artifact_id: str, max_bytes: int, label: str) -> object:
        try:
            payload = self.product.artifact_store.read_bytes(artifact_id, max_bytes=max_bytes)
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(f"{label} bytes are invalid") from error

    @staticmethod
    def _row(
        value: object,
        *,
        artifact_id: str,
        partition_hash: str,
    ) -> PanelInputRow:
        row = _closed(
            value,
            {
                "instrument_id", "symbol", "session_date", "open", "high", "low", "close",
                "volume_shares", "amount_cny", "available_time", "is_suspended", "is_st",
                "tradable", "price_limit_up", "price_limit_down", "no_price_limit_session",
                "corporate_action_ref", "missing_reason",
            },
            "Snapshot row",
        )
        try:
            session_date = date.fromisoformat(str(row["session_date"]))
        except ValueError as error:
            raise TruthPreconditionFailedError("Snapshot row session_date is invalid") from error
        instrument_id = row["instrument_id"]
        if not isinstance(instrument_id, str):
            raise TruthPreconditionFailedError("Snapshot row instrument_id is invalid")
        missing = row["missing_reason"]
        if not isinstance(missing, dict) or any(
            not isinstance(key, str) or not isinstance(reason, str)
            for key, reason in missing.items()
        ):
            raise TruthPreconditionFailedError("Snapshot row missing_reason is invalid")
        volume = row["volume_shares"]
        if volume is not None and (
            not isinstance(volume, int) or isinstance(volume, bool) or volume < 0
        ):
            raise TruthPreconditionFailedError("Snapshot row volume_shares is invalid")
        features = {
            "open": _finite_number(row["open"], "open"),
            "high": _finite_number(row["high"], "high"),
            "low": _finite_number(row["low"], "low"),
            "close": _finite_number(row["close"], "close"),
            "volume": None if volume is None else float(volume),
            "amount": _finite_number(row["amount_cny"], "amount_cny"),
        }
        missing_reasons = {
            "volume": missing.get("volume_shares", "SOURCE_VALUE_MISSING"),
            "amount": missing.get("amount_cny", "SOURCE_VALUE_MISSING"),
        }
        return PanelInputRow(
            session_date=session_date,
            instrument_id=instrument_id,
            features=features,
            missing_reasons=missing_reasons,
            source_partition_artifact_id=artifact_id,
            source_partition_sha256=partition_hash,
        )


def _schema_fingerprint(schema_version: str) -> str:
    return canonical_sha256({"schema_version": schema_version})


def _formula_wire(translation: Any) -> dict[str, object]:
    document = translation.document
    return {
        "schema_version": "v3.formula-document-version/1.0.0",
        "formula_document_version_id": document.formula_document_version_id,
        "language": document.language,
        "source_text": document.source_text,
        "source_sha256": document.source_sha256,
        "compatibility_profile_id": document.compatibility_profile_id,
        "parse_status": document.parse_status.value,
        "ast_digest": document.ast_digest,
        "named_outputs": document.named_outputs,
        "provenance_ref": document.provenance_ref,
        "translator_version": translation.translator_version,
        "static_analysis": {
            "input_data_dependencies": translation.static_analysis.input_data_dependencies,
            "operator_dependencies": translation.static_analysis.operator_dependencies,
            "max_lookback": translation.static_analysis.max_lookback,
            "named_outputs": tuple(
                (name, value_type.value)
                for name, value_type in translation.static_analysis.named_outputs
            ),
            "unsupported_functions": translation.static_analysis.unsupported_functions,
            "data_semantic_profile_id": translation.static_analysis.data_semantic_profile_id,
        },
    }


def _value_wire(row: PanelValueRow) -> dict[str, object]:
    return {
        "session_date": row.session_date.isoformat(),
        "instrument_id": row.instrument_id,
        "value": row.value,
        "missing_reason": row.missing_reason,
        "source_partition_artifact_id": row.source_partition_artifact_id,
        "source_partition_sha256": row.source_partition_sha256,
    }


def _chunk_factor_rows(
    *,
    snapshot_id: str,
    universe_version_id: str,
    definition: FactorDefinitionVersion,
    rows: tuple[PanelValueRow, ...],
) -> tuple[tuple[bytes, int, str, str], ...]:
    """Serialize every value row into deterministic partitions below the artifact ceiling."""
    output: list[tuple[bytes, int, str, str]] = []
    cursor = 0
    ordinal = 0
    while cursor < len(rows):
        take = min(20_000, len(rows) - cursor)
        while True:
            selected = rows[cursor : cursor + take]
            wire = {
                "schema_version": _FACTOR_PARTITION_SCHEMA,
                "snapshot_id": snapshot_id,
                "universe_version_id": universe_version_id,
                "factor_definition_version_id": definition.factor_definition_version_id,
                "partition_key": f"{ordinal:08d}",
                "rows": tuple(_value_wire(row) for row in selected),
            }
            payload = canonical_json_bytes(wire)
            if len(payload) <= _MAX_PARTITION_BYTES:
                break
            if take == 1:
                raise TruthPreconditionFailedError("one Factor row exceeds the artifact ceiling")
            take = max(1, take // 2)
        output.append(
            (
                payload,
                len(selected),
                selected[0].session_date.isoformat(),
                selected[-1].session_date.isoformat(),
            )
        )
        cursor += take
        ordinal += 1
    return tuple(output)


class ProductFactorStudyService:
    """Canonical V1.1 local Factor study owner with durable artifact/read-model recovery."""

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def _publish_json(
        self,
        *,
        project_id: str,
        role: str,
        schema_version: str,
        provenance: str,
        wire: Mapping[str, object],
    ) -> Any:
        payload = canonical_json_bytes(wire)
        return self.product.execution._publish_artifact_batch(
            payloads=((provenance, payload, role, _schema_fingerprint(schema_version)),),
            references=((project_id, role, 0),),
        )[0].descriptor

    def _persist_catalog_rows(
        self,
        *,
        project_id: str,
        definitions: tuple[tuple[FactorDefinitionVersion, Any], ...],
    ) -> None:
        now = wire_time(datetime.now(timezone.utc))
        connection = connect_catalog(self.product.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for definition, artifact in definitions:
                definition_wire = definition.to_wire()
                definition_id = "fad_sha256_" + canonical_sha256(
                    {"project_id": project_id, "stable_name": definition.logical_name}
                )
                version_id = "fav_sha256_" + canonical_sha256(
                    {
                        "factor_definition_id": definition_id,
                        "factor_definition_version_id": definition.factor_definition_version_id,
                        "code_artifact_id": artifact.artifact_id,
                        "code_hash": artifact.sha256,
                    }
                )
                definition_json = canonical_json_bytes(definition_wire).decode("utf-8")
                availability_json = canonical_json_bytes(
                    {
                        "schema_version": "v3.factor-availability-policy/1.0.0",
                        "availability_semantics": "AFTER_SESSION_CLOSE",
                        "truth": "NOT_FORMAL",
                        "admission": "PRE_ALPHA",
                    }
                ).decode("utf-8")
                existing_definition = connection.execute(
                    "SELECT project_id,stable_name,definition_json FROM factor_definition WHERE factor_definition_id=?",
                    (definition_id,),
                ).fetchone()
                expected_definition = (project_id, definition.logical_name, definition_json)
                if existing_definition is None:
                    connection.execute(
                        "INSERT INTO factor_definition(factor_definition_id,project_id,stable_name,definition_json,created_at) VALUES(?,?,?,?,?)",
                        (definition_id, project_id, definition.logical_name, definition_json, now),
                    )
                elif tuple(existing_definition) != expected_definition:
                    raise TruthPreconditionFailedError("FactorDefinition catalog identity conflict")
                existing_version = connection.execute(
                    "SELECT factor_definition_id,semantic_version,code_artifact_id,code_hash,availability_policy_json,state FROM factor_version WHERE factor_version_id=?",
                    (version_id,),
                ).fetchone()
                expected_version = (
                    definition_id,
                    "1.0.0",
                    artifact.artifact_id,
                    artifact.sha256,
                    availability_json,
                    "PUBLISHED",
                )
                if existing_version is None:
                    connection.execute(
                        "INSERT INTO factor_version(factor_version_id,factor_definition_id,semantic_version,code_artifact_id,code_hash,availability_policy_json,state,published_at) VALUES(?,?,?,?,?,?,?,?)",
                        (version_id, *expected_version, now),
                    )
                elif tuple(existing_version) != expected_version:
                    raise TruthPreconditionFailedError("FactorVersion catalog identity conflict")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def run_factor_study(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        formula_source: str,
        analysis_output_name: str,
    ) -> dict[str, Any]:
        context = self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        current = self.product.current_revision(project_id)
        if current["project_context_revision_id"] != project_context_revision_id:
            raise TruthPreconditionFailedError("Factor study requires the current ProjectContextRevision")
        snapshot_id = context.get("snapshot_id")
        universe_version_id = context.get("universe_version_id")
        if not isinstance(snapshot_id, str) or not isinstance(universe_version_id, str):
            raise TruthPreconditionFailedError("ProjectContextRevision lacks exact Snapshot/Universe")

        panel = ManifestAwareLocalSnapshotReader(self.product).resolve(
            project_id=project_id,
            snapshot_id=snapshot_id,
            universe_version_id=universe_version_id,
        )
        registry = panel_operator_registry()
        translation = TdxTranslator(registry).translate(
            formula_source,
            data_profile=registered_tdx_data_semantic_profile(volume_in_hands=False),
            provenance_ref=(
                f"ProjectContextRevision:{project_context_revision_id}:"
                f"Snapshot:{snapshot_id}:UniverseVersion:{universe_version_id}"
            ),
        )
        formula_descriptor = self._publish_json(
            project_id=project_id,
            role=_FACTOR_FORMULA_ROLE,
            schema_version="v3.formula-document-version/1.0.0",
            provenance=translation.document.formula_document_version_id,
            wire=_formula_wire(translation),
        )

        evaluator = DeterministicPanelEvaluator(registry)
        outputs: dict[str, dict[str, object]] = {}
        evaluated: dict[str, tuple[PanelValueRow, ...]] = {}
        definition_descriptors: list[tuple[FactorDefinitionVersion, Any]] = []
        for translated in translation.outputs:
            definition = translated.definition
            definition_descriptor = self._publish_json(
                project_id=project_id,
                role=_FACTOR_DEFINITION_ROLE,
                schema_version="v3.factor-definition-version/1.0.0",
                provenance=definition.factor_definition_version_id,
                wire={
                    "schema_version": "v3.factor-definition-version/1.0.0",
                    **definition.to_wire(),
                    "formula_document_version_id": translation.document.formula_document_version_id,
                    "formula_output_binding_id": translated.binding.binding_id,
                },
            )
            definition_descriptors.append((definition, definition_descriptor))
            result = evaluator.evaluate(definition, panel.rows)
            evaluated[translated.output_name] = result.rows
            chunk_descriptors: list[dict[str, object]] = []
            for ordinal, (payload, row_count, minimum_date, maximum_date) in enumerate(
                _chunk_factor_rows(
                    snapshot_id=snapshot_id,
                    universe_version_id=universe_version_id,
                    definition=definition,
                    rows=result.rows,
                )
            ):
                descriptor = self.product.execution._publish_artifact_batch(
                    payloads=((
                        definition.factor_definition_version_id,
                        payload,
                        _FACTOR_PARTITION_ROLE,
                        _schema_fingerprint(_FACTOR_PARTITION_SCHEMA),
                    ),),
                    references=((project_id, _FACTOR_PARTITION_ROLE, 0),),
                )[0].descriptor
                chunk_descriptors.append(
                    {
                        "partition_key": f"{ordinal:08d}",
                        "artifact_id": descriptor.artifact_id,
                        "sha256": descriptor.sha256,
                        "byte_size": descriptor.byte_size,
                        "row_count": row_count,
                        "min_session_date": minimum_date,
                        "max_session_date": maximum_date,
                    }
                )
            materialization_identity = {
                "schema_version": _FACTOR_MATERIALIZATION_SCHEMA,
                "snapshot_id": snapshot_id,
                "universe_version_id": universe_version_id,
                "factor_definition_version_id": definition.factor_definition_version_id,
                "evaluator_version": result.evaluator_version,
                "output_type": result.output_type.value,
                "row_count": len(result.rows),
                "partitions": tuple(chunk_descriptors),
            }
            materialization_id = "fmt_sha256_" + canonical_sha256(materialization_identity)
            materialization_descriptor = self._publish_json(
                project_id=project_id,
                role=_FACTOR_MATERIALIZATION_ROLE,
                schema_version=_FACTOR_MATERIALIZATION_SCHEMA,
                provenance=materialization_id,
                wire={"materialization_id": materialization_id, **materialization_identity},
            )
            outputs[translated.output_name] = {
                "factor_definition_version_id": definition.factor_definition_version_id,
                "factor_definition_artifact_id": definition_descriptor.artifact_id,
                "materialization_id": materialization_id,
                "materialization_artifact_id": materialization_descriptor.artifact_id,
                "output_type": result.output_type.value,
                "row_count": len(result.rows),
            }

        try:
            analysis_rows = evaluated[analysis_output_name]
            analysis_definition = next(
                value.definition
                for value in translation.outputs
                if value.output_name == analysis_output_name
            )
        except (KeyError, StopIteration) as error:
            raise TruthPreconditionFailedError("analysis output is not a translated named output") from error
        if analysis_definition.metadata.output_type is not ValueType.FLOAT_SERIES:
            raise TruthPreconditionFailedError("Factor analysis requires a numeric named output")
        analysis = FactorAnalysisService().analyze(
            snapshot_id=snapshot_id,
            universe_version_id=universe_version_id,
            membership=panel.membership,
            factor_rows=analysis_rows,
            market_rows=panel.rows,
            spec=FactorAnalysisSpecV1(),
        )
        analysis_wire = analysis.to_wire()
        analysis_descriptor = self._publish_json(
            project_id=project_id,
            role=_FACTOR_ANALYSIS_ROLE,
            schema_version="v3.factor-analysis-result/1.0.0",
            provenance=analysis.factor_analysis_result_id,
            wire={"schema_version": "v3.factor-analysis-result/1.0.0", **analysis_wire},
        )
        self._persist_catalog_rows(
            project_id=project_id,
            definitions=tuple(definition_descriptors),
        )

        visual_preview: list[dict[str, object]] = []
        for index, market_row in enumerate(panel.rows[:_PREVIEW_ROW_LIMIT]):
            row: dict[str, object] = {
                "session_date": market_row.session_date.isoformat(),
                "instrument_id": market_row.instrument_id,
                "open": market_row.features.get("open"),
                "high": market_row.features.get("high"),
                "low": market_row.features.get("low"),
                "close": market_row.features.get("close"),
                "volume_shares": market_row.features.get("volume"),
                "amount_cny": market_row.features.get("amount"),
            }
            for name, values in evaluated.items():
                row[name] = values[index].value
            visual_preview.append(row)
        study: dict[str, Any] = {
            "schema_version": _FACTOR_READ_MODEL_SCHEMA,
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "snapshot_id": snapshot_id,
            "universe_version_id": universe_version_id,
            "source_manifest_artifact_id": panel.manifest_artifact_id,
            "source_manifest_sha256": panel.manifest_sha256,
            "formula_document_version_id": translation.document.formula_document_version_id,
            "formula_document_artifact_id": formula_descriptor.artifact_id,
            "outputs": outputs,
            "analysis_output_name": analysis_output_name,
            "analysis": analysis_wire,
            "analysis_artifact_id": analysis_descriptor.artifact_id,
            "visual_preview": tuple(visual_preview),
        }
        read_model_payload = canonical_json_bytes(study)
        if len(read_model_payload) > _MAX_PARTITION_BYTES:
            raise TruthPreconditionFailedError("Factor study read model exceeds the bounded ceiling")
        read_model_descriptor = self.product.execution._publish_artifact_batch(
            payloads=((
                (
                    f"{translation.document.formula_document_version_id}:"
                    f"{snapshot_id}:{universe_version_id}"
                ),
                read_model_payload,
                _FACTOR_READ_MODEL_ROLE,
                _schema_fingerprint(_FACTOR_READ_MODEL_SCHEMA),
            ),),
            references=((project_id, _FACTOR_READ_MODEL_ROLE, 0),),
        )[0].descriptor
        if read_model_descriptor.byte_size != len(read_model_payload):
            raise TruthPreconditionFailedError("Factor study read model byte identity drifted")
        # Normalize tuples to the durable JSON value model while preserving the
        # formula's declared output order for the live product response.
        return json.loads(json.dumps(study, ensure_ascii=False, allow_nan=False))

    def get_latest_factor_study(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        snapshot_id: str,
    ) -> dict[str, Any]:
        self.product.require_project(project_id)
        self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT a.artifact_id,a.sha256,a.byte_size
                FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=? AND r.role=?
                  AND r.state='ACTIVE' AND a.state='PUBLISHED'
                ORDER BY r.created_at DESC,r.artifact_reference_id DESC
                """,
                (project_id, _FACTOR_READ_MODEL_ROLE),
            ).fetchall()
            reachable_rows = connection.execute(
                """
                SELECT a.artifact_id,a.sha256,a.byte_size,a.semantic_role,a.state,r.role
                FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=? AND r.state='ACTIVE'
                """,
                (project_id,),
            ).fetchall()
        finally:
            connection.close()
        reachable: dict[str, tuple[tuple[str, int, str, str, str], ...]] = {}
        for artifact_id, sha256, byte_size, semantic_role, state, reference_role in reachable_rows:
            key = str(artifact_id)
            reachable[key] = (
                *reachable.get(key, ()),
                (
                    str(sha256),
                    int(byte_size),
                    str(semantic_role),
                    str(state),
                    str(reference_role),
                ),
            )
        for artifact_id, sha256, byte_size in rows:
            if int(byte_size) > _MAX_PARTITION_BYTES or str(artifact_id) != "art_sha256_" + str(sha256):
                raise TruthPreconditionFailedError("Factor study read-model descriptor is invalid")
            try:
                raw = self.product.artifact_store.read_bytes(
                    str(artifact_id), max_bytes=_MAX_PARTITION_BYTES
                )
                if len(raw) != int(byte_size):
                    raise TruthPreconditionFailedError(
                        "Factor study read-model byte size drifted"
                    )
                payload = json.loads(raw.decode("utf-8"))
            except TruthPreconditionFailedError:
                raise
            except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError, ArtifactError) as error:
                raise TruthPreconditionFailedError("Factor study read-model bytes are invalid") from error
            if (
                isinstance(payload, dict)
                and payload.get("schema_version") == _FACTOR_READ_MODEL_SCHEMA
                and payload.get("project_id") == project_id
                and payload.get("project_context_revision_id")
                == project_context_revision_id
                and payload.get("snapshot_id") == snapshot_id
            ):
                self._verify_recovered_study_links(
                    payload=payload,
                    reachable=reachable,
                )
                return payload
        raise NotFoundError("Factor study read model is unavailable")

    def _verify_recovered_study_links(
        self,
        *,
        payload: Mapping[str, Any],
        reachable: Mapping[str, tuple[tuple[str, int, str, str, str], ...]],
    ) -> None:
        expected_keys = {
            "schema_version", "truth", "admission", "project_id",
            "project_context_revision_id", "snapshot_id", "universe_version_id",
            "source_manifest_artifact_id", "source_manifest_sha256",
            "formula_document_version_id", "formula_document_artifact_id", "outputs",
            "analysis_output_name", "analysis", "analysis_artifact_id", "visual_preview",
        }
        if set(payload) != expected_keys or payload.get("truth") != "NOT_FORMAL" or payload.get("admission") != "PRE_ALPHA":
            raise TruthPreconditionFailedError("Factor study read model shape or truth drifted")

        source_manifest_raw = self._verify_reachable_artifact(
            reachable,
            str(payload["source_manifest_artifact_id"]),
            PARTITION_MANIFEST_ROLE,
            expected_sha256=str(payload["source_manifest_sha256"]),
        )
        try:
            source_manifest = json.loads(source_manifest_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TruthPreconditionFailedError("Factor source manifest bytes are invalid") from error
        if not isinstance(source_manifest, dict) or source_manifest.get("schema_version") != _MANIFEST_SCHEMA:
            raise TruthPreconditionFailedError("Factor source manifest schema drifted")

        formula_raw = self._verify_reachable_artifact(
            reachable,
            str(payload["formula_document_artifact_id"]),
            _FACTOR_FORMULA_ROLE,
        )
        analysis_raw = self._verify_reachable_artifact(
            reachable,
            str(payload["analysis_artifact_id"]),
            _FACTOR_ANALYSIS_ROLE,
        )
        try:
            formula = json.loads(formula_raw.decode("utf-8"))
            analysis_artifact = json.loads(analysis_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TruthPreconditionFailedError("Factor owner artifact bytes are invalid") from error
        if (
            not isinstance(formula, dict)
            or formula.get("schema_version") != "v3.formula-document-version/1.0.0"
            or formula.get("formula_document_version_id")
            != payload["formula_document_version_id"]
            or not isinstance(analysis_artifact, dict)
            or analysis_artifact.get("schema_version")
            != "v3.factor-analysis-result/1.0.0"
            or {
                key: value
                for key, value in analysis_artifact.items()
                if key != "schema_version"
            }
            != payload.get("analysis")
        ):
            raise TruthPreconditionFailedError("Factor owner artifact binding drifted")

        outputs = payload.get("outputs")
        if not isinstance(outputs, dict) or not outputs or len(outputs) > 64:
            raise TruthPreconditionFailedError("Factor study outputs are invalid")
        for output_name, raw_output in outputs.items():
            output = _closed(
                raw_output,
                {
                    "factor_definition_version_id", "factor_definition_artifact_id",
                    "materialization_id", "materialization_artifact_id", "output_type",
                    "row_count",
                },
                "Factor study output",
            )
            if not isinstance(output_name, str) or not output_name:
                raise TruthPreconditionFailedError("Factor output name is invalid")
            if (
                not isinstance(output["row_count"], int)
                or isinstance(output["row_count"], bool)
                or output["row_count"] < 1
            ):
                raise TruthPreconditionFailedError("Factor output row_count is invalid")
            definition_raw = self._verify_reachable_artifact(
                reachable,
                str(output["factor_definition_artifact_id"]),
                _FACTOR_DEFINITION_ROLE,
            )
            try:
                definition = json.loads(definition_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise TruthPreconditionFailedError(
                    "Factor definition artifact bytes are invalid"
                ) from error
            if (
                not isinstance(definition, dict)
                or definition.get("schema_version")
                != "v3.factor-definition-version/1.0.0"
                or definition.get("factor_definition_version_id")
                != output["factor_definition_version_id"]
                or definition.get("formula_document_version_id")
                != payload["formula_document_version_id"]
            ):
                raise TruthPreconditionFailedError(
                    "Factor definition artifact binding drifted"
                )
            materialization_raw = self._verify_reachable_artifact(
                reachable,
                str(output["materialization_artifact_id"]),
                _FACTOR_MATERIALIZATION_ROLE,
            )
            try:
                materialization = json.loads(materialization_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise TruthPreconditionFailedError(
                    "Factor materialization manifest bytes are invalid"
                ) from error
            manifest = _closed(
                materialization,
                {
                    "materialization_id", "schema_version", "snapshot_id",
                    "universe_version_id", "factor_definition_version_id",
                    "evaluator_version", "output_type", "row_count", "partitions",
                },
                "Factor materialization manifest",
            )
            if (
                manifest["schema_version"] != _FACTOR_MATERIALIZATION_SCHEMA
                or manifest["materialization_id"] != output["materialization_id"]
                or manifest["snapshot_id"] != payload["snapshot_id"]
                or manifest["universe_version_id"] != payload["universe_version_id"]
                or manifest["factor_definition_version_id"]
                != output["factor_definition_version_id"]
                or manifest["output_type"] != output["output_type"]
                or manifest["row_count"] != output["row_count"]
                or not isinstance(manifest["partitions"], list)
            ):
                raise TruthPreconditionFailedError(
                    "Factor materialization manifest binding drifted"
                )
            for raw_partition in manifest["partitions"]:
                partition = _closed(
                    raw_partition,
                    {
                        "partition_key", "artifact_id", "sha256", "byte_size",
                        "row_count", "min_session_date", "max_session_date",
                    },
                    "Factor materialization partition descriptor",
                )
                if (
                    not isinstance(partition["byte_size"], int)
                    or isinstance(partition["byte_size"], bool)
                    or partition["byte_size"] < 1
                    or not isinstance(partition["row_count"], int)
                    or isinstance(partition["row_count"], bool)
                    or partition["row_count"] < 1
                ):
                    raise TruthPreconditionFailedError(
                        "Factor materialization partition bounds are invalid"
                    )
                self._verify_reachable_artifact(
                    reachable,
                    str(partition["artifact_id"]),
                    _FACTOR_PARTITION_ROLE,
                    expected_sha256=str(partition["sha256"]),
                    expected_byte_size=partition["byte_size"],
                    verify_bytes=False,
                )
        analysis_output_name = payload.get("analysis_output_name")
        analysis = payload.get("analysis")
        if (
            not isinstance(analysis_output_name, str)
            or analysis_output_name not in outputs
            or not isinstance(analysis, dict)
            or analysis.get("snapshot_id") != payload["snapshot_id"]
            or analysis.get("universe_version_id") != payload["universe_version_id"]
            or analysis.get("factor_definition_version_id")
            != outputs[analysis_output_name]["factor_definition_version_id"]
            or not isinstance(payload.get("visual_preview"), list)
            or len(payload["visual_preview"]) > _PREVIEW_ROW_LIMIT
        ):
            raise TruthPreconditionFailedError("Factor analysis/read-model binding drifted")

    def _verify_reachable_artifact(
        self,
        reachable: Mapping[str, tuple[tuple[str, int, str, str, str], ...]],
        artifact_id: str,
        role: str,
        *,
        expected_sha256: str | None = None,
        expected_byte_size: int | None = None,
        verify_bytes: bool = True,
    ) -> bytes:
        candidates = reachable.get(artifact_id, ())
        matched = next(
            (
                candidate
                for candidate in candidates
                if candidate[2] == role
                and candidate[3] == "PUBLISHED"
                and candidate[4] == role
            ),
            None,
        )
        if matched is None:
            raise TruthPreconditionFailedError(
                f"Factor artifact {role} is not project-reachable and PUBLISHED"
            )
        sha256, byte_size, _, _, _ = matched
        if (
            artifact_id != "art_sha256_" + sha256
            or (expected_sha256 is not None and sha256 != expected_sha256)
            or (expected_byte_size is not None and byte_size != expected_byte_size)
            or byte_size > _MAX_PARTITION_BYTES
        ):
            raise TruthPreconditionFailedError(f"Factor artifact {role} descriptor drifted")
        if not verify_bytes:
            return b""
        try:
            with self.product.artifact_store.open_verified(
                artifact_id,
                expected_sha256=sha256,
                expected_byte_size=byte_size,
                max_bytes=_MAX_PARTITION_BYTES,
            ) as handle:
                return handle.read()
        except (OSError, ValueError, ArtifactError) as error:
            raise TruthPreconditionFailedError(
                f"Factor artifact {role} bytes are unavailable"
            ) from error

    def _prepare_submission(
        self,
        submission: ProductFactorStudySubmission,
    ) -> _PreparedFactorStudyRequest:
        context = self.product.require_project_context_ownership(
            submission.project_id, submission.project_context_revision_id
        )
        current = self.product.current_revision(submission.project_id)
        if current["project_context_revision_id"] != context["project_context_revision_id"]:
            raise ConflictError("Factor study requires the current project context revision")
        source = submission.formula_source
        if (
            not isinstance(source, str)
            or not source.strip()
            or len(source) > 65_536
            or len(source.encode("utf-8")) > 262_144
        ):
            raise InvalidArgumentError("formula_source is required and bounded")
        output_name = submission.analysis_output_name
        if (
            not isinstance(output_name, str)
            or not output_name
            or len(output_name) > 64
            or not (output_name[0].isalpha() or output_name[0] == "_")
            or any(not (value.isalnum() or value == "_") for value in output_name)
        ):
            raise InvalidArgumentError("analysis_output_name is invalid")
        if not isinstance(submission.idempotency_key, str) or not submission.idempotency_key.strip():
            raise InvalidArgumentError("idempotency_key is required")
        snapshot_id = context.get("snapshot_id")
        universe_version_id = context.get("universe_version_id")
        if not isinstance(snapshot_id, str) or not isinstance(universe_version_id, str):
            raise TruthPreconditionFailedError("Factor study requires exact Snapshot/Universe refs")
        provenance = (
            f"ProjectContextRevision:{submission.project_context_revision_id}:"
            f"Snapshot:{snapshot_id}:UniverseVersion:{universe_version_id}"
        )
        translation = TdxTranslator(panel_operator_registry()).translate(
            source,
            data_profile=registered_tdx_data_semantic_profile(volume_in_hands=False),
            provenance_ref=provenance,
        )
        try:
            selected = translation.output(output_name)
        except KeyError as error:
            raise InvalidArgumentError("analysis_output_name is not a translated output") from error
        if selected.definition.metadata.output_type is not ValueType.FLOAT_SERIES:
            raise InvalidArgumentError("analysis_output_name must select a numeric output")
        semantic = {
            "project_id": submission.project_id,
            "project_context_revision_id": submission.project_context_revision_id,
            "snapshot_id": snapshot_id,
            "universe_version_id": universe_version_id,
            "formula_source": source,
            "analysis_output_name": output_name,
            "formula_document_version_id": translation.document.formula_document_version_id,
        }
        request_hash = _canonical_request_hash(PRODUCT_FACTOR_STUDY_OPERATION, semantic)
        return _PreparedFactorStudyRequest(
            project_id=submission.project_id,
            project_context_revision_id=submission.project_context_revision_id,
            snapshot_id=snapshot_id,
            universe_version_id=universe_version_id,
            formula_source=source,
            analysis_output_name=output_name,
            formula_document_version_id=translation.document.formula_document_version_id,
            semantic=semantic,
            request_hash=request_hash,
            scope=self.product.idempotency.scope_key(
                PRODUCT_FACTOR_STUDY_OPERATION,
                submission.project_id,
                submission.idempotency_key,
            ),
            execution_deadline_at=submission.execution_deadline_at,
        )

    @staticmethod
    def _accepted_outcome(
        task_id: str,
        run_id: str,
        request: _PreparedFactorStudyRequest,
        *,
        event_cursor: int | None = None,
    ) -> dict[str, Any]:
        outcome: dict[str, Any] = {
            "task_id": task_id,
            "run_id": run_id,
            "accepted_state": "QUEUED",
            "maturity": "PRODUCT_CONNECTED",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "checkpoint_resume": "UNAVAILABLE",
            "retry": "NEW_ATTEMPT_SAME_RUN_FROM_START",
            "formula_document_version_id": request.formula_document_version_id,
            "analysis_output_name": request.analysis_output_name,
        }
        if event_cursor is not None:
            outcome["event_cursor"] = event_cursor
        return outcome

    def _accept_request(self, request: _PreparedFactorStudyRequest) -> _FactorTaskHandles:
        context_artifact_id = self.product.execution._persist_context_artifact(
            {
                "schema_version": _FACTOR_CONTEXT_SCHEMA,
                "context_kind": "PRODUCT_FACTOR_STUDY",
                **request.semantic,
                "truth": "NOT_FORMAL",
                "admission": "PRE_ALPHA",
                "execution_state": "QUEUED_BEFORE_FACTOR_PUBLICATION",
            },
            provenance="prv_product_factor_intent_" + request.request_hash,
        )
        return _FactorTaskHandles(
            *self.product.execution._create_task(
                operation_id=PRODUCT_FACTOR_STUDY_OPERATION,
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                normalized_input_hash=canonical_sha256(request.semantic),
                context_artifact_id=context_artifact_id,
                idempotency=(request.scope, request.request_hash, _accept_outcome_json),
                execution_deadline_at=request.execution_deadline_at,
                inline_worker=False,
                service_contract_version="1.1.0",
            )
        )

    def submit(self, submission: ProductFactorStudySubmission) -> dict[str, Any]:
        request = self._prepare_submission(submission)
        existing = self.product.idempotency.lookup(
            self.product, request.scope, request.request_hash
        )
        if existing is not None:
            return self._accepted_outcome(
                str(existing["task_id"]), str(existing["run_id"]), request
            )
        workers = getattr(self.product, "product_workers", None)
        if workers is None:
            raise CapabilityUnavailableError(
                "isolated Product worker is unavailable for Factor study",
                details={"reason_code": "PRODUCT_WORKER_NOT_AVAILABLE"},
            )
        reservation = workers.reserve_capacity()
        handles: _FactorTaskHandles | None = None
        try:
            handles = self._accept_request(request)
            workers.start(
                request,
                handles,
                reservation_token=reservation,
                operation_id=PRODUCT_FACTOR_STUDY_OPERATION,
                work_kind="FACTOR_STUDY",
                resource_class="PRODUCT_FACTOR_CPU",
            )
        except Exception as error:
            workers.release_capacity(reservation)
            if handles is not None:
                self.product.execution._finish_failure(
                    handles.task,
                    handles.run,
                    handles.attempt,
                    error=error,
                    category=classify_execution_error(error),
                )
            raise
        return self._accepted_outcome(
            handles.task.task_id,
            handles.run.run_id,
            request,
            event_cursor=self.product.latest_event_sequence(request.project_id),
        )

    def execute_accepted(
        self,
        request: _PreparedFactorStudyRequest,
        handles: _FactorTaskHandles,
    ) -> dict[str, Any]:
        try:
            study = self.run_factor_study(
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                formula_source=request.formula_source,
                analysis_output_name=request.analysis_output_name,
            )
            if study["formula_document_version_id"] != request.formula_document_version_id:
                raise TruthPreconditionFailedError("queued FormulaDocument identity drifted")
            self.product.execution._finish_success(
                handles.task,
                handles.run,
                handles.attempt,
                outputs={
                    "snapshot_id": study["snapshot_id"],
                    "universe_version_id": study["universe_version_id"],
                    "formula_document_version_id": study["formula_document_version_id"],
                    "factor_analysis_result_id": study["analysis"][
                        "factor_analysis_result_id"
                    ],
                    "analysis_artifact_id": study["analysis_artifact_id"],
                },
            )
            return study
        except Exception as error:
            self.product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=error,
                category=classify_execution_error(error),
            )
            raise


@dataclass(frozen=True, slots=True)
class ProductFactorStudySubmission:
    project_id: str
    project_context_revision_id: str
    formula_source: str
    analysis_output_name: str
    idempotency_key: str
    execution_deadline_at: str | None = None


@dataclass(frozen=True, slots=True)
class _PreparedFactorStudyRequest:
    project_id: str
    project_context_revision_id: str
    snapshot_id: str
    universe_version_id: str
    formula_source: str
    analysis_output_name: str
    formula_document_version_id: str
    semantic: dict[str, Any]
    request_hash: str
    scope: str
    execution_deadline_at: str | None


@dataclass(frozen=True, slots=True)
class _FactorTaskHandles:
    task: Any
    run: Any
    attempt: Any


__all__ = (
    "ManifestAwareLocalSnapshotReader",
    "PRODUCT_FACTOR_STUDY_OPERATION",
    "ProductFactorStudySubmission",
    "ProductFactorStudyService",
    "ResolvedLocalSnapshotPanel",
)
