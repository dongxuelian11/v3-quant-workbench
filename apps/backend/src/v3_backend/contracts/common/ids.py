from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from types import MappingProxyType


_ULID_RE = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class IdentitySpec:
    object_type: str
    identity: str
    prefix: str
    algorithm: str


_IDENTITY_ROWS = (('Project', 'prj_ ULID', 'prj_', 'ULID'),
 ('ProjectContextRevision', 'pcr_ ULID', 'pcr_', 'ULID'),
 ('Session', 'ses_ UUIDv7', 'ses_', 'UUIDv7'),
 ('Connector', 'con_ ULID', 'con_', 'ULID'),
 ('ConnectorVersion', 'cov_ ULID', 'cov_', 'ULID'),
 ('ConnectorAdmission', 'cad_ ULID', 'cad_', 'ULID'),
 ('CredentialReference', 'crf_ ULID', 'crf_', 'ULID'),
 ('Instrument', 'ins_ ULID', 'ins_', 'ULID'),
 ('InstrumentAlias', 'ial_ ULID', 'ial_', 'ULID'),
 ('RawCapture', 'raw_ ULID', 'raw_', 'ULID'),
 ('DataSnapshotVersion', 'snp_ ULID', 'snp_', 'ULID'),
 ('IndustryTaxonomyVersion', 'itx_ ULID', 'itx_', 'ULID'),
 ('UniverseDefinition', 'und_ ULID', 'und_', 'ULID'),
 ('UniverseVersion', 'unv_ ULID', 'unv_', 'ULID'),
 ('FactorDefinition', 'fad_ ULID', 'fad_', 'ULID'),
 ('FactorVersion', 'fav_ ULID', 'fav_', 'ULID'),
 ('DatasetSpec', 'dss_ ULID', 'dss_', 'ULID'),
 ('DatasetVersion', 'dsv_ ULID', 'dsv_', 'ULID'),
 ('StrategyDraft', 'std_ ULID', 'std_', 'ULID'),
 ('StrategyVersion', 'stv_ ULID', 'stv_', 'ULID'),
 ('ModelSpec', 'mds_ ULID', 'mds_', 'ULID'),
 ('ModelVersion', 'mdv_ ULID', 'mdv_', 'ULID'),
 ('PredictionSignalVersion', 'sgv_ ULID', 'sgv_', 'ULID'),
 ('Study', 'stu_ ULID', 'stu_', 'ULID'),
 ('Trial', 'trl_ ULID', 'trl_', 'ULID'),
 ('PortfolioConstructionSpec', 'pcs_ ULID', 'pcs_', 'ULID'),
 ('PortfolioVersion', 'pfv_ ULID', 'pfv_', 'ULID'),
 ('RiskModelSpec', 'rms_ ULID', 'rms_', 'ULID'),
 ('RiskModelVersion', 'rmv_ ULID', 'rmv_', 'ULID'),
 ('ConstraintSetVersion', 'csv_ ULID', 'csv_', 'ULID'),
 ('OptimizationProblem', 'opb_ ULID', 'opb_', 'ULID'),
 ('OptimizationSolution', 'ops_ ULID', 'ops_', 'ULID'),
 ('Experiment', 'exp_ ULID', 'exp_', 'ULID'),
 ('BacktestRunSpec', 'brs_ ULID', 'brs_', 'ULID'),
 ('Task', 'tsk_ ULID', 'tsk_', 'ULID'),
 ('Run', 'run_ ULID', 'run_', 'ULID'),
 ('TaskAttempt', 'att_ ULID', 'att_', 'ULID'),
 ('TaskEvent', 'tev_ ULID', 'tev_', 'ULID'),
 ('Result', 'res_ ULID', 'res_', 'ULID'),
 ('Artifact', 'art_sha256_ hash', 'art_sha256_', 'hash'),
 ('ArtifactReference', 'arf_ ULID', 'arf_', 'ULID'),
 ('WorkerLease', 'lea_ ULID', 'lea_', 'ULID'),
 ('ProvenanceEntity', 'prv_ ULID', 'prv_', 'ULID'),
 ('ProvenanceEdge', 'pre_ ULID', 'pre_', 'ULID'))
IDENTITY_SPECS = MappingProxyType({
    row[0]: IdentitySpec(*row) for row in _IDENTITY_ROWS
})
ID_PREFIXES = MappingProxyType({
    spec.prefix: spec.object_type for spec in IDENTITY_SPECS.values()
})
LIFECYCLE_STATES_BY_OBJECT = MappingProxyType({'Project': ('ACTIVE', 'ARCHIVED'),
 'ProjectContextRevision': ('PUBLISHED',),
 'Session': ('OPEN', 'CLOSED'),
 'Connector': ('REGISTERED', 'DISABLED'),
 'ConnectorVersion': ('QUARANTINED', 'ADMITTED', 'REJECTED', 'RETIRED'),
 'ConnectorAdmission': ('PENDING', 'RUNNING', 'PASSED', 'FAILED'),
 'CredentialReference': ('ACTIVE', 'REVOKED'),
 'Instrument': ('ACTIVE', 'DELISTED', 'MERGED'),
 'InstrumentAlias': ('EFFECTIVE', 'EXPIRED'),
 'RawCapture': ('CAPTURED', 'QUARANTINED', 'ACCEPTED'),
 'DataSnapshotVersion': ('CANDIDATE', 'VALIDATED', 'PUBLISHED', 'REJECTED'),
 'IndustryTaxonomyVersion': ('PUBLISHED',),
 'UniverseDefinition': ('DRAFT', 'PUBLISHED'),
 'UniverseVersion': ('BUILDING', 'PUBLISHED', 'REJECTED'),
 'FactorDefinition': ('DRAFT', 'PUBLISHED'),
 'FactorVersion': ('PUBLISHED', 'RETIRED'),
 'DatasetSpec': ('DRAFT', 'VALIDATED', 'REJECTED'),
 'DatasetVersion': ('MATERIALIZING', 'PUBLISHED', 'REJECTED'),
 'StrategyDraft': ('EDITABLE', 'SUPERSEDED'),
 'StrategyVersion': ('PUBLISHED', 'RETIRED'),
 'ModelSpec': ('DRAFT', 'VALIDATED'),
 'ModelVersion': ('TRAINING', 'PUBLISHED', 'REJECTED'),
 'PredictionSignalVersion': ('GENERATING', 'PUBLISHED', 'REJECTED'),
 'Study': ('CREATED',
   'RUNNING',
   'PAUSING',
   'PAUSED',
   'COMPLETED',
   'PARTIAL',
   'CANCELLED',
   'FAILED'),
 'Trial': ('QUEUED', 'RUNNING', 'PRUNED', 'COMPLETED', 'FAILED', 'CANCELLED'),
 'PortfolioConstructionSpec': ('DRAFT', 'PUBLISHED'),
 'PortfolioVersion': ('BUILDING', 'PUBLISHED', 'REJECTED'),
 'RiskModelSpec': ('DRAFT', 'VALIDATED'),
 'RiskModelVersion': ('BUILDING', 'PUBLISHED', 'REJECTED'),
 'ConstraintSetVersion': ('PUBLISHED',),
 'OptimizationProblem': ('READY', 'INVALID'),
 'OptimizationSolution': ('OPTIMAL', 'INFEASIBLE', 'UNBOUNDED', 'FAILED', 'INVALID'),
 'Experiment': ('DRAFT', 'EXPANDED', 'RUNNING', 'PARTIAL', 'COMPLETED', 'FAILED', 'CANCELLED'),
 'BacktestRunSpec': ('PUBLISHED',),
 'Task': ('QUEUED',
  'RUNNING',
  'PAUSE_REQUESTED',
  'PAUSED',
  'CANCEL_REQUESTED',
  'SUCCEEDED',
  'FAILED',
  'CANCELLED',
  'PARTIAL'),
 'Run': ('SEALED', 'ACTIVE', 'TERMINAL'),
 'TaskAttempt': ('QUEUED',
         'LEASED',
         'STARTING',
         'RUNNING',
         'CHECKPOINTING',
         'SUCCEEDED',
         'FAILED',
         'CANCELLED',
         'LOST'),
 'TaskEvent': ('PERSISTED',),
 'Result': ('PENDING_RECONCILIATION', 'VALID', 'INVALID'),
 'Artifact': ('STAGED', 'PUBLISHED', 'QUARANTINED', 'DELETED'),
 'ArtifactReference': ('ACTIVE', 'RELEASED'),
 'WorkerLease': ('GRANTED', 'RENEWED', 'EXPIRED', 'RELEASED', 'REVOKED'),
 'ProvenanceEntity': ('RECORDED',),
 'ProvenanceEdge': ('RECORDED',)})


class InvalidV3Id(ValueError):
    pass


def _spec_for_value(value: str) -> IdentitySpec:
    for prefix in sorted(ID_PREFIXES, key=len, reverse=True):
        if value.startswith(prefix):
            return IDENTITY_SPECS[ID_PREFIXES[prefix]]
    raise InvalidV3Id(f"unknown V3 ID prefix: {value!r}")


def validate_v3_id(value: str, expected_object_type: str | None = None) -> str:
    if not isinstance(value, str):
        raise InvalidV3Id("V3 ID must be a string")
    spec = _spec_for_value(value)
    if expected_object_type is not None and spec.object_type != expected_object_type:
        raise InvalidV3Id(
            f"expected {expected_object_type} ID, got {spec.object_type}"
        )
    suffix = value[len(spec.prefix):]
    if spec.algorithm == "ULID":
        if _ULID_RE.fullmatch(suffix) is None:
            raise InvalidV3Id(f"invalid canonical ULID for {spec.object_type}")
    elif spec.algorithm == "UUIDv7":
        try:
            parsed = uuid.UUID(suffix)
        except ValueError as exc:
            raise InvalidV3Id("invalid UUIDv7") from exc
        if parsed.version != 7 or str(parsed) != suffix:
            raise InvalidV3Id("session ID must use canonical lowercase UUIDv7")
    elif spec.algorithm == "hash":
        if _SHA256_RE.fullmatch(suffix) is None:
            raise InvalidV3Id("artifact ID must contain lowercase SHA-256")
    else:
        raise InvalidV3Id(f"unsupported identity algorithm: {spec.algorithm}")
    return value


def object_type_for_id(value: str) -> str:
    validate_v3_id(value)
    return _spec_for_value(value).object_type


def is_canonical_v3_id(value: object, expected_object_type: str | None = None) -> bool:
    try:
        validate_v3_id(value, expected_object_type)  # type: ignore[arg-type]
    except (InvalidV3Id, TypeError):
        return False
    return True


@dataclass(frozen=True)
class V3Id:
    value: str
    object_type: str | None = None

    def __post_init__(self) -> None:
        validate_v3_id(self.value, self.object_type)
        if self.object_type is None:
            object.__setattr__(self, "object_type", object_type_for_id(self.value))

    def __str__(self) -> str:
        return self.value
