from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class CapabilityTruthState(str, Enum):
    FORMAL = "FORMAL"
    DEMO = "DEMO"
    UNAVAILABLE = "UNAVAILABLE"


class OperationalTruthState(str, Enum):
    FORMAL = "FORMAL"
    DEMO = "DEMO"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"


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
_REASON_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]*")


@dataclass(frozen=True)
class CapabilityTruthV1:
    truth_state: CapabilityTruthState
    truth_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.truth_state, CapabilityTruthState):
            object.__setattr__(self, "truth_state", CapabilityTruthState(self.truth_state))
        if any(_REASON_CODE_RE.fullmatch(code) is None for code in self.truth_reason_codes):
            raise ValueError("truth reason codes must be uppercase stable codes")
        if self.truth_state is CapabilityTruthState.FORMAL and self.truth_reason_codes:
            raise ValueError("FORMAL truth cannot carry downgrade reason codes")

    def to_wire(self) -> dict[str, object]:
        return {
            "truth_state": self.truth_state.value,
            "truth_reason_codes": list(self.truth_reason_codes),
        }


@dataclass(frozen=True)
class LifecycleStateV1:
    object_type: str
    state: str

    def __post_init__(self) -> None:
        allowed = LIFECYCLE_STATES_BY_OBJECT.get(self.object_type)
        if allowed is None:
            raise ValueError(f"unknown lifecycle object type: {self.object_type}")
        if self.state not in allowed:
            raise ValueError(
                f"invalid {self.object_type} lifecycle state {self.state!r}; allowed={allowed}"
            )
