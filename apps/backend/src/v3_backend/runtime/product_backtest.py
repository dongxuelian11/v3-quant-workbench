"""V1.1 Product research Backtest over actual Data/Strategy/Risk owner bytes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from v3_backend.adapters.sqlite.risk_application import (
    SQLiteRiskApplicationRepository,
)
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.backtest_runtime import (
    BacktestContractError,
    BacktestRunSpec,
    Board,
    DailyMarketState,
    DeterministicAshareBacktestEngine,
    ExactInputReference,
    InstrumentDefinition,
    MarketSession,
    ResearchExecutionInputs,
    ResearchExecutionProfileV1,
    ResearchLiquidityRow,
    ScheduledWeights,
    cn_a_share_2023_08_28_cost_policy,
    cn_a_share_2026_07_06_execution_timing_profile,
    cn_a_share_2026_07_06_rule_profile,
)
from v3_backend.domain.weights import RuntimeIdentity
from v3_backend.domain.tasks.entities import AttemptState, RunState, TaskAttempt, TaskState
from v3_backend.domain.tasks.events import PendingTaskEvent
from v3_backend.domain.tasks.retry_policy import ErrorCategory, RetryPolicy
from v3_backend.domain.tasks.state_machine import (
    TaskTransitionContext,
    transition_task,
)
from v3_backend.errors.exceptions import (
    CapabilityUnavailableError,
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256

from .product_data import PARTITION_MANIFEST_ROLE
from .product_corporate_actions import ProductCorporateActionService
from .product_factor import ManifestAwareLocalSnapshotReader, ResolvedLocalSnapshotPanel
from .product_publication import (
    ANALYTICS_ROLE,
    ASSUMPTION_RECEIPT_ROLE,
    EXECUTION_INPUTS_ROLE,
    FILLS_EXPORT_ROLE,
    LINEAGE_ROLE,
    ORDERS_EXPORT_ROLE,
    ProductBacktestPublication,
    READ_MODEL_ROLE,
    SUMMARY_EXPORT_ROLE,
)
from .product_runtime import (
    BACKTEST_RUN_RESULT_ROLE,
    BACKTEST_RUN_SPEC_ROLE,
    LEDGER_MANIFEST_ROLE,
    ProductRuntime,
    _TASK_EVENT_VERSION,
    _accept_outcome_json,
    _canonical_request_hash,
    classify_execution_error,
    mint_v3_id,
)
from .product_strategy import ProductStrategyService


PRODUCT_RESEARCH_BACKTEST_OPERATION = (
    "ProductEntryService.v1.submitResearchBacktest"
)
_CONTEXT_SCHEMA = "v3.product-research-backtest-context/1.1.0"
_MAX_SESSIONS = 3_000
_MAX_INSTRUMENTS = 500
_MAX_SESSION_INSTRUMENTS = 1_000_000
_MAX_READ_MODEL_BYTES = 8 * 1024 * 1024
_MAX_CONTROL_ARTIFACT_BYTES = 16 * 1024 * 1024
_ENGINE_RUNTIME = RuntimeIdentity(
    code_version="v3-v1.1-product-backtest",
    runtime_profile_id="v3.product-research-backtest/1.0.0",
    environment_fingerprint="cpython-3.14-v3-product-research-backtest",
)


@dataclass(frozen=True, slots=True)
class _ExecutionPolicyBundle:
    effective_from: date
    effective_to: date | None
    boards: tuple[Board, ...]
    rule: Any
    cost: Any
    timing: Any


class ExecutionPolicyRegistry:
    """Closed V1.1 date/board registry; never extrapolates an adjacent policy."""

    def __init__(self, bundles: tuple[_ExecutionPolicyBundle, ...]) -> None:
        if not bundles:
            raise ValueError("execution policy registry must not be empty")
        ordered = tuple(
            sorted(
                bundles,
                key=lambda item: (
                    item.effective_from,
                    date.max if item.effective_to is None else item.effective_to,
                    item.rule.profile_id,
                ),
            )
        )
        for bundle in ordered:
            if bundle.effective_to is not None and bundle.effective_to < bundle.effective_from:
                raise ValueError("execution policy bundle has an empty effective range")
            if not bundle.boards or len(set(bundle.boards)) != len(bundle.boards):
                raise ValueError("execution policy bundle boards are invalid")
        for board in Board:
            prior_end: date | None = None
            prior_seen = False
            for bundle in (item for item in ordered if board in item.boards):
                if prior_seen and (prior_end is None or bundle.effective_from <= prior_end):
                    raise ValueError(
                        f"execution policy ranges overlap for board {board.value}"
                    )
                prior_seen = True
                prior_end = bundle.effective_to
        self._bundles = ordered

    @classmethod
    def bounded_v1_1(cls) -> ExecutionPolicyRegistry:
        rule = cn_a_share_2026_07_06_rule_profile()
        timing = cn_a_share_2026_07_06_execution_timing_profile()
        cost = cn_a_share_2023_08_28_cost_policy(
            commission_rate="0.0003", minimum_commission="5"
        )
        finite_ends = tuple(
            value
            for value in (rule.effective_to, timing.effective_to, cost.effective_to)
            if value is not None
        )
        boards = tuple(
            sorted(
                {item.board for item in rule.board_rules}
                & {item.board for item in cost.market_rules},
                key=lambda value: value.value,
            )
        )
        return cls(
            (
                _ExecutionPolicyBundle(
                    max(rule.effective_from, timing.effective_from, cost.effective_from),
                    min(finite_ends) if finite_ends else None,
                    boards,
                    rule,
                    cost,
                    timing,
                ),
            )
        )

    def resolve(
        self,
        *,
        session_start: date,
        session_end: date,
        boards: tuple[Board, ...],
    ) -> _ExecutionPolicyBundle:
        if session_end < session_start or not boards:
            raise TruthPreconditionFailedError(
                "execution policy coverage request is invalid"
            )
        required_boards = set(boards)
        matches = tuple(
            bundle
            for bundle in self._bundles
            if session_start >= bundle.effective_from
            and (bundle.effective_to is None or session_end <= bundle.effective_to)
            and required_boards.issubset(bundle.boards)
        )
        if len(matches) != 1:
            bounded = self._bundles[0] if len(self._bundles) == 1 else None
            raise CapabilityUnavailableError(
                "Backtest session range or board set is outside admitted execution policy coverage",
                details={
                    "reason_code": "EXECUTION_POLICY_COVERAGE_UNAVAILABLE",
                    "coverage_start": (
                        None if bounded is None else bounded.effective_from.isoformat()
                    ),
                    "coverage_end": (
                        None
                        if bounded is None or bounded.effective_to is None
                        else bounded.effective_to.isoformat()
                    ),
                },
            )
        return matches[0]

    def public_coverage(self) -> dict[str, Any]:
        if len(self._bundles) != 1:
            raise TruthPreconditionFailedError(
                "V1.1 Product Home requires one closed execution policy bundle"
            )
        bundle = self._bundles[0]
        return {
            "schema_version": "v3.product-backtest-policy-coverage/1.0.0",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "coverage_start": bundle.effective_from.isoformat(),
            "coverage_end": (
                None if bundle.effective_to is None else bundle.effective_to.isoformat()
            ),
            "rule_profile_id": bundle.rule.profile_id,
            "cost_policy_id": bundle.cost.policy_id,
            "execution_timing_profile_id": bundle.timing.profile_id,
            "commission_rate": bundle.cost.commission_rate,
            "minimum_commission_cny": bundle.cost.minimum_commission,
            "stamp_duty_sell_rate": bundle.cost.stamp_duty_sell_rate,
            "resource_estimate": {
                "resource_class": "PRODUCT_BACKTEST_CPU",
                "cpu_slots": 1,
                "memory_limit_bytes": 1024 * 1024 * 1024,
                "scratch_limit_bytes": 1024 * 1024 * 1024,
                "checkpoint_resume": "UNAVAILABLE",
            },
        }


def _canonical_decimal(
    value: str,
    name: str,
    *,
    maximum: Decimal,
    allow_zero: bool = False,
) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidArgumentError(f"{name} must be canonical decimal text")
    try:
        observed = Decimal(value)
    except InvalidOperation as error:
        raise InvalidArgumentError(f"{name} must be canonical decimal text") from error
    if (
        not observed.is_finite()
        or observed < 0
        or (observed == 0 and not allow_zero)
        or observed > maximum
    ):
        raise InvalidArgumentError(f"{name} is outside the admitted range")
    normalized = format(observed.normalize(), "f")
    return "0" if normalized == "-0" else normalized


def _price(value: float | None, name: str) -> str:
    if value is None:
        raise TruthPreconditionFailedError(f"{name} is unavailable")
    try:
        observed = Decimal(str(value))
    except InvalidOperation as error:
        raise TruthPreconditionFailedError(f"{name} is invalid") from error
    if not observed.is_finite() or observed <= 0:
        raise TruthPreconditionFailedError(f"{name} is unavailable")
    normalized = format(observed.normalize(), "f")
    return "0" if normalized == "-0" else normalized


def _board(instrument_id: str) -> Board:
    parts = instrument_id.split("_")
    if len(parts) != 4 or parts[:2] != ["ins", "cn"]:
        raise TruthPreconditionFailedError("instrument identity is not canonical A-share")
    exchange, symbol = parts[2], parts[3]
    if len(symbol) != 6 or not symbol.isdigit():
        raise TruthPreconditionFailedError("instrument symbol is not canonical")
    if exchange == "bse":
        return Board.BSE
    if exchange == "sse":
        return Board.SSE_STAR if symbol.startswith(("688", "689")) else Board.SSE_MAIN
    if exchange == "szse":
        return (
            Board.SZSE_CHINEXT
            if symbol.startswith(("300", "301"))
            else Board.SZSE_MAIN
        )
    raise TruthPreconditionFailedError("instrument exchange is not admitted")


@dataclass(frozen=True, slots=True)
class ProductResearchBacktestSubmission:
    project_id: str
    project_context_revision_id: str
    research_strategy_spec_id: str
    session_start: date
    session_end: date
    slippage_bps: str
    daily_volume_participation_rate: str
    idempotency_key: str
    execution_deadline_at: str | None = None


@dataclass(frozen=True, slots=True)
class _PreparedBacktestRequest:
    project_id: str
    project_context_revision_id: str
    research_strategy_spec_id: str
    session_start: date
    session_end: date
    slippage_bps: str
    daily_volume_participation_rate: str
    semantic: dict[str, Any]
    request_hash: str
    research_backtest_request_id: str
    scope: str
    execution_deadline_at: str | None


@dataclass(frozen=True, slots=True)
class _BacktestTaskHandles:
    task: Any
    run: Any
    attempt: Any


class ProductResearchBacktestService:
    """Durably accept, isolate and finalize the bounded research Backtest."""

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    @staticmethod
    def _artifact_content_sha256(artifact_id: object, label: str) -> str:
        if (
            not isinstance(artifact_id, str)
            or not artifact_id.startswith("art_sha256_")
            or len(artifact_id) != len("art_sha256_") + 64
        ):
            raise TruthPreconditionFailedError(f"{label} Artifact identity is invalid")
        digest = artifact_id.removeprefix("art_sha256_")
        if any(character not in "0123456789abcdef" for character in digest):
            raise TruthPreconditionFailedError(f"{label} Artifact identity is invalid")
        return digest

    def _resource_admission_reference(
        self, handles: _BacktestTaskHandles
    ) -> ExactInputReference:
        """Snapshot the durable worker lease that admitted this exact Attempt."""

        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT l.lease_id,l.attempt_id,l.worker_id,l.cpu_slots,
                       l.memory_limit_bytes,l.gpu_device,l.scratch_limit_bytes,
                       l.granted_at,l.state,w.worker_kind,w.environment_profile_id
                FROM worker_lease AS l
                JOIN worker AS w ON w.worker_id=l.worker_id
                WHERE l.attempt_id=?
                """,
                (handles.attempt.attempt_id,),
            ).fetchall()
        finally:
            connection.close()
        if len(rows) != 1:
            raise TruthPreconditionFailedError(
                "Backtest resource admission lease is unavailable"
            )
        row = rows[0]
        if (
            str(row[1]) != handles.attempt.attempt_id
            or str(row[8]) not in {"GRANTED", "RENEWED"}
            or int(row[3]) != 1
            or int(row[4]) != 1024 * 1024 * 1024
            or int(row[6]) != 1024 * 1024 * 1024
        ):
            raise TruthPreconditionFailedError(
                "Backtest resource admission lease drifted"
            )
        receipt = {
            "schema_version": "v3.product-resource-admission-receipt/1.0.0",
            "operation_id": PRODUCT_RESEARCH_BACKTEST_OPERATION,
            "resource_class": "PRODUCT_BACKTEST_CPU",
            "task_id": handles.task.task_id,
            "run_id": handles.run.run_id,
            "attempt_id": handles.attempt.attempt_id,
            "lease_id": str(row[0]),
            "worker_id": str(row[2]),
            "cpu_slots": int(row[3]),
            "memory_limit_bytes": int(row[4]),
            "gpu_device": None if row[5] is None else str(row[5]),
            "scratch_limit_bytes": int(row[6]),
            "granted_at": str(row[7]),
            "worker_kind": str(row[9]),
            "environment_profile_id": str(row[10]),
            "checkpoint_resume": "UNAVAILABLE",
        }
        digest = canonical_sha256(receipt)
        return ExactInputReference(
            "RESOURCE_ADMISSION",
            "radm_sha256_" + digest,
            digest,
            PRE_ALPHA_CEILING,
        )

    @staticmethod
    def bounded_policy_coverage() -> dict[str, Any]:
        """Project-visible projection of the exact admitted coverage registry."""
        return ExecutionPolicyRegistry.bounded_v1_1().public_coverage()

    def _lightweight_preflight(self, request: _PreparedBacktestRequest) -> None:
        """Reject known binding/coverage/action gaps before durable Task acceptance.

        This path reads only bounded control Artifacts and Catalog rows. Partition
        bytes, Factor materializations and engine inputs remain worker-owned.
        """
        context = self.product.require_project_context_ownership(
            request.project_id, request.project_context_revision_id
        )
        connection = self.product._connection(read_only=True)
        try:
            strategy_row = connection.execute(
                """
                SELECT a.artifact_id,a.byte_size
                FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=?
                  AND r.role='PRODUCT_STRATEGY_READ_MODEL'
                  AND r.state='ACTIVE' AND a.state='PUBLISHED'
                ORDER BY r.created_at DESC,r.artifact_reference_id DESC
                LIMIT 1
                """,
                (request.project_id,),
            ).fetchone()
            snapshot_row = connection.execute(
                """
                SELECT manifest_artifact_id,state
                FROM data_snapshot WHERE snapshot_id=?
                """,
                (context.get("snapshot_id"),),
            ).fetchone()
        finally:
            connection.close()
        if strategy_row is None or int(strategy_row[1]) > _MAX_READ_MODEL_BYTES:
            raise TruthPreconditionFailedError(
                "current project Strategy read model is unavailable"
            )
        try:
            strategy = json.loads(
                self.product.read_verified_bytes(str(strategy_row[0])).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(
                "current project Strategy read-model bytes are invalid"
            ) from error
        if (
            not isinstance(strategy, dict)
            or strategy.get("schema_version")
            != "v3.product-strategy-read-model/1.0.0"
            or strategy.get("project_id") != request.project_id
            or strategy.get("project_context_revision_id")
            != request.project_context_revision_id
            or strategy.get("research_strategy_spec_id")
            != request.research_strategy_spec_id
            or strategy.get("snapshot_id") != context.get("snapshot_id")
            or strategy.get("universe_version_id")
            != context.get("universe_version_id")
        ):
            raise TruthPreconditionFailedError(
                "Backtest requires the latest exact Strategy in the current project context"
            )
        profile_refs = strategy.get("profile_refs")
        if not isinstance(profile_refs, dict) or set(profile_refs) != {
            "cost_policy_version_id",
            "execution_policy_version_id",
            "risk_policy_set_version_id",
            "assumption_profile_id",
        }:
            raise TruthPreconditionFailedError(
                "Backtest Strategy profile bindings are not closed"
            )
        bounded_refs = ProductStrategyService.bounded_profile_ids()
        for key in (
            "cost_policy_version_id",
            "execution_policy_version_id",
            "risk_policy_set_version_id",
        ):
            if profile_refs.get(key) != bounded_refs[key]:
                raise TruthPreconditionFailedError(
                    "Backtest Strategy profile binding is not admitted"
                )
        assumption_id = profile_refs.get("assumption_profile_id")
        if not isinstance(assumption_id, str):
            raise TruthPreconditionFailedError(
                "Backtest Strategy assumption profile is absent"
            )
        ProductStrategyService.assumption_mode(assumption_id)

        if snapshot_row is None or str(snapshot_row[1]) != "PUBLISHED":
            raise TruthPreconditionFailedError(
                "Backtest Snapshot is not published in the current project context"
            )
        manifest_artifact_id = str(snapshot_row[0])
        descriptor = self.product.require_published_artifact(manifest_artifact_id)
        if (
            descriptor["semantic_role"] != PARTITION_MANIFEST_ROLE
            or int(descriptor["byte_size"]) > _MAX_READ_MODEL_BYTES
        ):
            raise TruthPreconditionFailedError(
                "Backtest Snapshot manifest binding is invalid"
            )
        try:
            manifest = json.loads(
                self.product.read_verified_bytes(manifest_artifact_id).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(
                "Backtest Snapshot manifest bytes are invalid"
            ) from error
        expected_keys = {
            "schema_version",
            "data_schema_version",
            "adjustment",
            "amount_unit",
            "timezone",
            "volume_unit",
            "row_count",
            "instrument_count",
            "corporate_action_ref_count",
            "partitions",
        }
        manifest_schema = manifest.get("schema_version") if isinstance(manifest, dict) else None
        if manifest_schema == "v3.local-a-share-eod-manifest/1.2.0":
            expected_keys.add("corporate_action_refs")
        if (
            not isinstance(manifest, dict)
            or set(manifest) != expected_keys
            or manifest_schema
            not in {
                "v3.local-a-share-eod-manifest/1.1.0",
                "v3.local-a-share-eod-manifest/1.2.0",
            }
            or not isinstance(manifest.get("partitions"), list)
            or not manifest["partitions"]
        ):
            raise CapabilityUnavailableError(
                "Snapshot lacks the bounded preflight summary required by research Backtest",
                details={"reason_code": "SNAPSHOT_PREFLIGHT_SUMMARY_NOT_AVAILABLE"},
            )
        action_count = manifest.get("corporate_action_ref_count")
        if (
            not isinstance(action_count, int)
            or isinstance(action_count, bool)
            or action_count < 0
            or action_count > manifest.get("row_count", -1)
        ):
            raise TruthPreconditionFailedError(
                "Snapshot corporate-action preflight summary is invalid"
            )
        if action_count > 0:
            action_refs = manifest.get("corporate_action_refs")
            if (
                manifest_schema != "v3.local-a-share-eod-manifest/1.2.0"
                or not isinstance(action_refs, list)
                or not action_refs
                or any(not isinstance(value, str) for value in action_refs)
            ):
                raise CapabilityUnavailableError(
                    "known corporate-action refs require an admitted Corporate Action owner",
                    details={"reason_code": "CORPORATE_ACTION_NOT_AVAILABLE"},
                )
            ProductCorporateActionService(self.product).preflight_refs(
                project_id=request.project_id,
                refs=tuple(action_refs),
            )
        first_partition = manifest["partitions"][0]
        last_partition = manifest["partitions"][-1]
        try:
            coverage_start = date.fromisoformat(first_partition["min_session_date"])
            coverage_end = date.fromisoformat(last_partition["max_session_date"])
        except (KeyError, TypeError, ValueError) as error:
            raise TruthPreconditionFailedError(
                "Snapshot date-coverage summary is invalid"
            ) from error
        if (
            request.session_start < coverage_start
            or request.session_end > coverage_end
        ):
            raise InvalidArgumentError(
                "Backtest session range exceeds current Snapshot coverage"
            )

        ExecutionPolicyRegistry.bounded_v1_1().resolve(
            session_start=request.session_start,
            session_end=request.session_end,
            boards=tuple(Board),
        )

    def _prepare_submission(
        self, submission: ProductResearchBacktestSubmission
    ) -> _PreparedBacktestRequest:
        context = self.product.require_project_context_ownership(
            submission.project_id, submission.project_context_revision_id
        )
        current = self.product.current_revision(submission.project_id)
        if current["project_context_revision_id"] != context["project_context_revision_id"]:
            raise ConflictError("Backtest requires the current project context revision")
        if (
            not isinstance(submission.research_strategy_spec_id, str)
            or not submission.research_strategy_spec_id.startswith("rssv_sha256_")
        ):
            raise InvalidArgumentError("research_strategy_spec_id is not canonical")
        if (
            not isinstance(submission.session_start, date)
            or isinstance(submission.session_start, datetime)
            or not isinstance(submission.session_end, date)
            or isinstance(submission.session_end, datetime)
            or submission.session_end < submission.session_start
        ):
            raise InvalidArgumentError("Backtest session range is invalid")
        observed_days = (submission.session_end - submission.session_start).days + 1
        if observed_days > _MAX_SESSIONS:
            raise InvalidArgumentError("Backtest session range exceeds the admitted bound")
        if not isinstance(submission.idempotency_key, str) or not submission.idempotency_key.strip():
            raise InvalidArgumentError("idempotency_key is required")
        slippage = _canonical_decimal(
            submission.slippage_bps,
            "slippage_bps",
            maximum=Decimal("10000"),
            allow_zero=True,
        )
        participation = _canonical_decimal(
            submission.daily_volume_participation_rate,
            "daily_volume_participation_rate",
            maximum=Decimal("1"),
        )
        semantic = {
            "project_id": submission.project_id,
            "project_context_revision_id": submission.project_context_revision_id,
            "research_strategy_spec_id": submission.research_strategy_spec_id,
            "session_start": submission.session_start.isoformat(),
            "session_end": submission.session_end.isoformat(),
            "slippage_bps": slippage,
            "daily_volume_participation_rate": participation,
        }
        request_hash = _canonical_request_hash(
            PRODUCT_RESEARCH_BACKTEST_OPERATION, semantic
        )
        request_id = "rbrq_sha256_" + canonical_sha256(semantic)
        return _PreparedBacktestRequest(
            submission.project_id,
            submission.project_context_revision_id,
            submission.research_strategy_spec_id,
            submission.session_start,
            submission.session_end,
            slippage,
            participation,
            semantic,
            request_hash,
            request_id,
            self.product.idempotency.scope_key(
                PRODUCT_RESEARCH_BACKTEST_OPERATION,
                submission.project_id,
                submission.idempotency_key,
            ),
            submission.execution_deadline_at,
        )

    @staticmethod
    def _accepted_outcome(
        task_id: str,
        run_id: str,
        request: _PreparedBacktestRequest,
        *,
        event_cursor: int | None = None,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "task_id": task_id,
            "run_id": run_id,
            "accepted_state": "QUEUED",
            "maturity": "PRODUCT_CONNECTED",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "checkpoint_resume": "UNAVAILABLE",
            "retry": "NEW_ATTEMPT_SAME_RUN_FROM_START",
            "research_backtest_request_id": request.research_backtest_request_id,
        }
        if event_cursor is not None:
            value["event_cursor"] = event_cursor
        return value

    def _accept_request(
        self, request: _PreparedBacktestRequest
    ) -> _BacktestTaskHandles:
        context_artifact_id = self.product.execution._persist_context_artifact(
            {
                "schema_version": _CONTEXT_SCHEMA,
                "context_kind": "PRODUCT_RESEARCH_BACKTEST",
                **request.semantic,
                "research_backtest_request_id": request.research_backtest_request_id,
                "truth": "NOT_FORMAL",
                "admission": "PRE_ALPHA",
                "execution_state": "QUEUED_BEFORE_OWNER_RESOLUTION",
            },
            provenance="prv_product_backtest_intent_" + request.request_hash,
        )
        return _BacktestTaskHandles(
            *self.product.execution._create_task(
                operation_id=PRODUCT_RESEARCH_BACKTEST_OPERATION,
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

    def submit(
        self, submission: ProductResearchBacktestSubmission
    ) -> dict[str, Any]:
        request = self._prepare_submission(submission)
        existing = self.product.idempotency.lookup(
            self.product, request.scope, request.request_hash
        )
        if existing is not None:
            return self._accepted_outcome(
                str(existing["task_id"]), str(existing["run_id"]), request
            )
        self._lightweight_preflight(request)
        workers = getattr(self.product, "product_workers", None)
        if workers is None:
            raise CapabilityUnavailableError(
                "isolated Product worker is unavailable for research Backtest",
                details={"reason_code": "PRODUCT_WORKER_NOT_AVAILABLE"},
            )
        reservation = workers.reserve_capacity()
        handles: _BacktestTaskHandles | None = None
        try:
            handles = self._accept_request(request)
            workers.start(
                request,
                handles,
                reservation_token=reservation,
                operation_id=PRODUCT_RESEARCH_BACKTEST_OPERATION,
                work_kind="RESEARCH_BACKTEST",
                resource_class="PRODUCT_BACKTEST_CPU",
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

    def preview(
        self, submission: ProductResearchBacktestSubmission
    ) -> dict[str, Any]:
        """Run the exact admission preflight without creating durable state."""

        request = self._prepare_submission(submission)
        self._lightweight_preflight(request)
        strategy = ProductStrategyService(self.product).get_latest_strategy(
            project_id=request.project_id,
            project_context_revision_id=request.project_context_revision_id,
        )
        coverage = self.bounded_policy_coverage()
        if strategy["research_strategy_spec_id"] != request.research_strategy_spec_id:
            raise TruthPreconditionFailedError(
                "Backtest preflight Strategy binding drifted"
            )
        return {
            "schema_version": "v3.product-backtest-preflight/1.0.0",
            "maturity": "PRODUCT_CONNECTED",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "status": "PASS",
            "project_id": request.project_id,
            "project_context_revision_id": request.project_context_revision_id,
            "research_strategy_spec_id": request.research_strategy_spec_id,
            "research_backtest_request_id": request.research_backtest_request_id,
            "snapshot_id": strategy["snapshot_id"],
            "universe_version_id": strategy["universe_version_id"],
            "session_start": request.session_start.isoformat(),
            "session_end": request.session_end.isoformat(),
            "slippage_bps": request.slippage_bps,
            "daily_volume_participation_rate": (
                request.daily_volume_participation_rate
            ),
            "commission_rate": coverage["commission_rate"],
            "minimum_commission_cny": coverage["minimum_commission_cny"],
            "stamp_duty_sell_rate": coverage["stamp_duty_sell_rate"],
            "assumption_mode": ProductStrategyService.assumption_mode(
                str(strategy["profile_refs"]["assumption_profile_id"])
            ),
            "policy_refs": {
                "rule_profile_id": coverage["rule_profile_id"],
                "cost_policy_id": coverage["cost_policy_id"],
                "execution_timing_profile_id": coverage[
                    "execution_timing_profile_id"
                ],
                "risk_policy_set_version_id": strategy["profile_refs"][
                    "risk_policy_set_version_id"
                ],
            },
            "resource_estimate": coverage["resource_estimate"],
            "side_effects": "NONE",
        }

    def retry_failed_task(
        self,
        *,
        task_id: str,
        failed_attempt_id: str,
        expected_state_version: int,
    ) -> str:
        """Replay one admitted Product Backtest as a new isolated Attempt.

        The immutable Run and execution-context Artifact are reused. No caller
        payload, renderer cache, checkpoint, or prior partial output is accepted
        as replay authority.
        """
        task = self.product.task_persistence.read_task(task_id)
        if task.operation_id != PRODUCT_RESEARCH_BACKTEST_OPERATION:
            raise InvalidArgumentError("Task is not a Product research Backtest")
        if task.state not in {TaskState.FAILED, TaskState.PARTIAL}:
            raise ConflictError("Task is not in a retryable state")
        if task.state_version != expected_state_version:
            raise ConflictError("Task state version is stale")
        latest = self.product.task_persistence.latest_attempt(task_id)
        if latest.attempt_id != failed_attempt_id or latest.state is not AttemptState.FAILED:
            raise InvalidArgumentError(
                "failed_attempt_id is not the latest failed Attempt"
            )
        if latest.terminal_error_category is None:
            raise InvalidArgumentError(
                "failed Attempt carries no error classification"
            )
        try:
            category = ErrorCategory(latest.terminal_error_category)
        except ValueError as error:
            raise InvalidArgumentError(
                "failed Attempt carries an unknown error classification"
            ) from error
        decision = RetryPolicy().decide(category, prior_attempt_count=latest.ordinal)
        if not decision.allowed:
            raise ConflictError(f"retry not admitted: {decision.reason}")

        run = self.product.execution._read_run(task.active_run_id)
        context_artifact_id = self.product.execution._run_context_artifact(run.run_id)
        try:
            context = json.loads(
                self.product.read_verified_bytes(context_artifact_id).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(
                "Product Backtest retry context bytes are invalid"
            ) from error
        expected_context_keys = {
            "schema_version",
            "context_kind",
            "project_id",
            "project_context_revision_id",
            "research_strategy_spec_id",
            "session_start",
            "session_end",
            "slippage_bps",
            "daily_volume_participation_rate",
            "research_backtest_request_id",
            "truth",
            "admission",
            "execution_state",
        }
        if (
            not isinstance(context, dict)
            or set(context) != expected_context_keys
            or context.get("schema_version") != _CONTEXT_SCHEMA
            or context.get("context_kind") != "PRODUCT_RESEARCH_BACKTEST"
            or context.get("project_id") != task.project_id
            or context.get("project_context_revision_id")
            != run.identity.project_context_revision_id
            or context.get("truth") != "NOT_FORMAL"
            or context.get("admission") != "PRE_ALPHA"
            or context.get("execution_state")
            != "QUEUED_BEFORE_OWNER_RESOLUTION"
        ):
            raise TruthPreconditionFailedError(
                "Product Backtest retry context identity drifted"
            )
        replay = self._prepare_submission(
            ProductResearchBacktestSubmission(
                project_id=str(context["project_id"]),
                project_context_revision_id=str(
                    context["project_context_revision_id"]
                ),
                research_strategy_spec_id=str(
                    context["research_strategy_spec_id"]
                ),
                session_start=date.fromisoformat(str(context["session_start"])),
                session_end=date.fromisoformat(str(context["session_end"])),
                slippage_bps=str(context["slippage_bps"]),
                daily_volume_participation_rate=str(
                    context["daily_volume_participation_rate"]
                ),
                idempotency_key=f"retry:{task_id}:{latest.ordinal + 1}",
            )
        )
        if (
            canonical_sha256(replay.semantic) != run.identity.normalized_input_hash
            or replay.research_backtest_request_id
            != context["research_backtest_request_id"]
        ):
            raise TruthPreconditionFailedError(
                "Product Backtest retry context does not match immutable Run identity"
            )
        self._lightweight_preflight(replay)
        workers = getattr(self.product, "product_workers", None)
        if workers is None:
            raise CapabilityUnavailableError(
                "isolated Product worker is unavailable for research Backtest retry",
                details={"reason_code": "PRODUCT_WORKER_NOT_AVAILABLE"},
            )
        reservation = workers.reserve_capacity()
        handles: _BacktestTaskHandles | None = None
        try:
            with self.product.task_persistence.begin() as unit:
                current_task = unit.require_task(task_id)
                if (
                    current_task.state_version != expected_state_version
                    or current_task.state not in {TaskState.FAILED, TaskState.PARTIAL}
                ):
                    raise ConflictError("Task retry admission became stale")
                current_task.state = transition_task(
                    current_task.state,
                    "RETRY_SCHEDULED",
                    TaskTransitionContext(retry_epoch=True),
                )
                unit.save_task(
                    current_task, expected_version=current_task.state_version
                )
                attempt = TaskAttempt(
                    attempt_id=mint_v3_id("att_"),
                    task_id=task_id,
                    run_id=run.run_id,
                    ordinal=latest.ordinal + 1,
                    state=AttemptState.QUEUED,
                    state_version=0,
                    lease_id=None,
                    resume_checkpoint_artifact_id=None,
                    terminal_error_category=None,
                )
                unit.add_attempt(attempt)
                unit.append_event(
                    PendingTaskEvent(
                        event_id=mint_v3_id("tev_"),
                        event_version=_TASK_EVENT_VERSION,
                        project_id=current_task.project_id,
                        task_id=task_id,
                        event_type="TASK_QUEUED",
                        occurred_at=datetime.now(timezone.utc),
                        payload={
                            "operation_id": current_task.operation_id,
                            "retry_of_attempt": failed_attempt_id,
                            "retry_mode": "NEW_ATTEMPT_SAME_RUN_FROM_START",
                        },
                        run_id=run.run_id,
                        attempt_id=attempt.attempt_id,
                    )
                )
                unit.commit()
            handles = _BacktestTaskHandles(current_task, run, attempt)
            workers.start(
                replay,
                handles,
                reservation_token=reservation,
                operation_id=PRODUCT_RESEARCH_BACKTEST_OPERATION,
                work_kind="RESEARCH_BACKTEST",
                resource_class="PRODUCT_BACKTEST_CPU",
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
                    run_transition=False,
                )
            raise
        return task_id

    def execute_accepted(
        self,
        request: _PreparedBacktestRequest,
        handles: _BacktestTaskHandles,
    ) -> dict[str, Any]:
        try:
            self.product.execution._record_progress(
                handles.task,
                handles.run,
                handles.attempt,
                phase="VALIDATING",
                completed_units=0,
                total_units=4,
                work_unit="CANONICAL_OWNER_RESOLUTION",
            )
            strategy_service = ProductStrategyService(self.product)
            strategy = strategy_service.get_strategy(
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                research_strategy_spec_id=request.research_strategy_spec_id,
            )
            panel = ManifestAwareLocalSnapshotReader(self.product).resolve(
                project_id=request.project_id,
                snapshot_id=str(strategy["snapshot_id"]),
                universe_version_id=str(strategy["universe_version_id"]),
            )
            spec_wire = self._strategy_spec(strategy)
            execution_profile = ResearchExecutionProfileV1.create(
                slippage_bps=request.slippage_bps,
                daily_volume_participation_rate=request.daily_volume_participation_rate,
                assumption_mode=strategy_service.assumption_mode(
                    str(spec_wire.get("assumption_profile_id"))
                ),
            )
            resource_admission = self._resource_admission_reference(handles)
            spec, execution_inputs, first_effective = self._build_run_spec(
                request=request,
                strategy_service=strategy_service,
                strategy=strategy,
                strategy_spec=spec_wire,
                panel=panel,
                resource_admission=resource_admission,
                execution_profile=execution_profile,
            )
            self.product.execution._record_progress(
                handles.task,
                handles.run,
                handles.attempt,
                phase="COMPUTING",
                completed_units=1,
                total_units=4,
                work_unit="DETERMINISTIC_BACKTEST",
            )
            result = DeterministicAshareBacktestEngine().run(
                spec, research_execution=execution_inputs
            )
            self.product.execution._record_progress(
                handles.task,
                handles.run,
                handles.attempt,
                phase="PUBLISHING",
                completed_units=2,
                total_units=4,
                work_unit="RESULT_PUBLICATION",
            )
            assumption_receipt = {
                "schema_version": "v3.research-assumption-receipt/1.0.0",
                "research_backtest_request_id": request.research_backtest_request_id,
                "assumption_mode": execution_inputs.profile.assumption_mode,
                "market_state_derivation": (
                    "VERIFIED_CANONICAL_EXPLICIT_STATUS_FIELDS"
                    if execution_inputs.profile.assumption_mode
                    == "STRICT_FAIL_CLOSED"
                    else "VERIFIED_BAR_PRESENT_AND_VOLUME_POSITIVE"
                ),
                "corporate_actions": (
                    "NO_ADMITTED_ACTIONS_IN_RESOLVED_RANGE"
                    if not any(session.corporate_actions for session in spec.sessions)
                    else "ADMITTED_PRE_ALPHA_ACTIONS_IN_RESOLVED_RANGE"
                ),
                "snapshot_id": panel.snapshot_id,
                "snapshot_sha256": panel.manifest_sha256,
                "research_execution_profile_id": execution_inputs.profile.profile_id,
                "truth": "NOT_FORMAL",
                "admission": "PRE_ALPHA",
            }
            finalized = ProductBacktestPublication(self.product).finalize(
                project_id=request.project_id,
                handles=handles,
                request_id=request.research_backtest_request_id,
                strategy=strategy,
                spec=spec,
                execution_inputs=execution_inputs,
                result=result,
                assumption_receipt=assumption_receipt,
                first_effective_session_date=first_effective,
            )
            return finalized.read_model
        except Exception as error:
            self.product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=error,
                category=classify_execution_error(error),
                run_transition=handles.run.state is not RunState.TERMINAL,
            )
            raise

    def _strategy_spec(self, strategy: Mapping[str, Any]) -> Mapping[str, Any]:
        artifact_id = strategy.get("research_strategy_spec_artifact_id")
        if not isinstance(artifact_id, str):
            raise TruthPreconditionFailedError("Strategy spec Artifact is absent")
        descriptor = self.product.require_published_artifact(artifact_id)
        if descriptor["semantic_role"] != "PRODUCT_RESEARCH_STRATEGY_SPEC":
            raise TruthPreconditionFailedError("Strategy spec Artifact role drifted")
        try:
            value = json.loads(
                self.product.artifact_store.read_bytes(
                    artifact_id, max_bytes=_MAX_READ_MODEL_BYTES
                ).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError("Strategy spec bytes are invalid") from error
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "schema_version",
                "research_strategy_spec_id",
                "universe_version_id",
                "entry_signal_factor_version_id",
                "exit_signal_factor_version_id",
                "position_sizing",
                "max_positions",
                "gross_exposure",
                "rebalance",
                "cost_policy_version_id",
                "execution_policy_version_id",
                "risk_policy_set_version_id",
                "initial_cash",
                "assumption_profile_id",
            }
            or value.get("schema_version") != "v3.research-strategy-spec/1.0.0"
            or value.get("research_strategy_spec_id")
            != strategy.get("research_strategy_spec_id")
        ):
            raise TruthPreconditionFailedError("Strategy spec identity drifted")
        profile_refs = strategy.get("profile_refs")
        if (
            not isinstance(profile_refs, dict)
            or value.get("universe_version_id") != strategy.get("universe_version_id")
            or value.get("entry_signal_factor_version_id")
            != strategy.get("entry_signal_ref", {}).get(
                "factor_definition_version_id"
            )
            or value.get("exit_signal_factor_version_id")
            != strategy.get("exit_signal_ref", {}).get(
                "factor_definition_version_id"
            )
            or any(
                value.get(key) != profile_refs.get(key)
                for key in (
                    "cost_policy_version_id",
                    "execution_policy_version_id",
                    "risk_policy_set_version_id",
                    "assumption_profile_id",
                )
            )
        ):
            raise TruthPreconditionFailedError("Strategy spec owner bindings drifted")
        return value

    def _build_run_spec(
        self,
        *,
        request: _PreparedBacktestRequest,
        strategy_service: ProductStrategyService,
        strategy: Mapping[str, Any],
        strategy_spec: Mapping[str, Any],
        panel: ResolvedLocalSnapshotPanel,
        resource_admission: ExactInputReference,
        execution_profile: ResearchExecutionProfileV1 | None = None,
    ) -> tuple[BacktestRunSpec, ResearchExecutionInputs, str]:
        if execution_profile is None:
            execution_profile = ResearchExecutionProfileV1.create(
                slippage_bps=request.slippage_bps,
                daily_volume_participation_rate=request.daily_volume_participation_rate,
                assumption_mode=strategy_service.assumption_mode(
                    str(strategy_spec.get("assumption_profile_id"))
                ),
            )
        owner = strategy_service._owner_context(
            project_id=request.project_id,
            project_context_revision_id=request.project_context_revision_id,
        )
        if (
            panel.snapshot_id != owner.snapshot_id
            or panel.universe_version_id != owner.universe_version_id
            or panel.membership != owner.instrument_ids
        ):
            raise TruthPreconditionFailedError("Data/Strategy owner context drifted")
        rows = tuple(
            row
            for row in panel.rows
            if request.session_start <= row.session_date <= request.session_end
        )
        session_dates = tuple(sorted({row.session_date for row in rows}))
        if not session_dates:
            raise TruthPreconditionFailedError("Backtest range has no admitted sessions")
        if session_dates[0] != request.session_start or session_dates[-1] != request.session_end:
            raise TruthPreconditionFailedError(
                "Backtest range endpoints are outside Snapshot coverage"
            )
        if len(session_dates) > _MAX_SESSIONS or len(owner.instrument_ids) > _MAX_INSTRUMENTS:
            raise TruthPreconditionFailedError("Backtest resources exceed admitted bounds")
        if len(session_dates) * len(owner.instrument_ids) > _MAX_SESSION_INSTRUMENTS:
            raise TruthPreconditionFailedError("Backtest panel exceeds admitted bound")
        by_key = {(row.session_date, row.instrument_id): row for row in rows}
        market_by_key = {
            (row.session_date, row.instrument_id): row
            for row in panel.market_rows
            if request.session_start <= row.session_date <= request.session_end
        }
        expected = {
            (session_date, instrument_id)
            for session_date in session_dates
            for instrument_id in owner.instrument_ids
        }
        if set(by_key) != expected or set(market_by_key) != expected:
            raise TruthPreconditionFailedError(
                "Backtest market rows do not cover exact sessions/Universe"
            )
        resolved_actions = ProductCorporateActionService(
            self.product
        ).resolve_for_panel(
            project_id=request.project_id,
            panel=panel,
            session_start=request.session_start,
            session_end=request.session_end,
        )

        instruments = tuple(
            InstrumentDefinition(instrument_id, _board(instrument_id))
            for instrument_id in owner.instrument_ids
        )
        sessions: list[MarketSession] = []
        liquidity: list[ResearchLiquidityRow] = []
        for session_date in session_dates:
            states: list[DailyMarketState] = []
            for instrument_id in owner.instrument_ids:
                row = by_key[(session_date, instrument_id)]
                market = market_by_key[(session_date, instrument_id)]
                raw_volume = row.features.get("volume")
                if raw_volume is None or raw_volume < 0 or int(raw_volume) != raw_volume:
                    raise TruthPreconditionFailedError(
                        "canonical research volume is unavailable or non-integral"
                    )
                volume = int(raw_volume)
                raw_open = _price(row.features.get("open"), "raw_open")
                raw_close = _price(row.features.get("close"), "raw_close")
                if execution_profile.assumption_mode == "STRICT_FAIL_CLOSED":
                    required = (
                        market.is_suspended,
                        market.is_st,
                        market.tradable,
                        market.no_price_limit_session,
                    )
                    if any(value is None for value in required):
                        raise CapabilityUnavailableError(
                            "strict execution requires explicit trading-state fields",
                            details={
                                "reason_code": "EXECUTION_POLICY_COVERAGE_UNAVAILABLE"
                            },
                        )
                    if market.is_suspended and market.tradable:
                        raise TruthPreconditionFailedError(
                            "strict trading state cannot be suspended and tradable"
                        )
                    if (
                        market.no_price_limit_session is False
                        and (
                            market.price_limit_up is None
                            or market.price_limit_down is None
                        )
                    ):
                        raise CapabilityUnavailableError(
                            "strict execution requires explicit price-limit values",
                            details={
                                "reason_code": "EXECUTION_POLICY_COVERAGE_UNAVAILABLE"
                            },
                        )
                    limit_up = (
                        None
                        if market.price_limit_up is None
                        else Decimal(str(market.price_limit_up))
                    )
                    limit_down = (
                        None
                        if market.price_limit_down is None
                        else Decimal(str(market.price_limit_down))
                    )
                    open_value = Decimal(raw_open)
                    state = DailyMarketState(
                        instrument_id,
                        raw_open,
                        raw_close,
                        suspended=bool(market.is_suspended),
                        tradable=bool(market.tradable),
                        restricted_security=bool(market.is_st),
                        at_limit_up_open=(
                            limit_up is not None and open_value >= limit_up
                        ),
                        at_limit_down_open=(
                            limit_down is not None and open_value <= limit_down
                        ),
                        no_price_limit_session=bool(
                            market.no_price_limit_session
                        ),
                    )
                else:
                    state = DailyMarketState(
                        instrument_id,
                        raw_open,
                        raw_close,
                        suspended=False,
                        tradable=volume > 0,
                    )
                states.append(state)
                liquidity.append(
                    ResearchLiquidityRow(session_date, instrument_id, volume)
                )
            sessions.append(
                MarketSession(
                    session_date,
                    True,
                    tuple(states),
                    resolved_actions.events_by_date.get(session_date, ()),
                )
            )

        risk_repository = SQLiteRiskApplicationRepository(
            self.product.database_path, self.product.artifact_root
        )
        schedule: list[ScheduledWeights] = []
        for chain in strategy.get("decision_chains", []):
            if not isinstance(chain, dict):
                raise TruthPreconditionFailedError("Strategy decision chain is invalid")
            try:
                effective_at = datetime.fromisoformat(str(chain["effective_time"]))
            except (KeyError, ValueError) as error:
                raise TruthPreconditionFailedError(
                    "Strategy effective time is invalid"
                ) from error
            if effective_at.tzinfo is None or effective_at.utcoffset() is None:
                raise TruthPreconditionFailedError("Strategy effective time lacks timezone")
            if not request.session_start <= effective_at.date() <= request.session_end:
                continue
            vector_id = chain.get("risk_adjusted_weight_vector_id")
            if not isinstance(vector_id, str):
                raise TruthPreconditionFailedError("Risk-adjusted vector identity is absent")
            vector = risk_repository.require_adjusted_weight_vector(vector_id)
            if vector.source_target.rebalance_time != effective_at:
                raise TruthPreconditionFailedError(
                    "Strategy/Risk effective-time binding drifted"
                )
            schedule.append(ScheduledWeights(effective_at, vector))
        if not schedule:
            raise TruthPreconditionFailedError("Backtest range has no canonical decisions")
        schedule.sort(key=lambda value: value.effective_at)

        execution_inputs = ResearchExecutionInputs.create(
            profile=execution_profile,
            market_data_source_id=panel.snapshot_id,
            market_data_content_sha256=panel.manifest_sha256,
            liquidity_rows=tuple(liquidity),
        )
        policy = ExecutionPolicyRegistry.bounded_v1_1().resolve(
            session_start=request.session_start,
            session_end=request.session_end,
            boards=tuple(
                sorted(
                    {item.board for item in instruments},
                    key=lambda value: value.value,
                )
            ),
        )
        rule = policy.rule
        timing = policy.timing
        cost = policy.cost
        entry_ref = strategy.get("entry_signal_ref")
        exit_ref = strategy.get("exit_signal_ref")
        if not isinstance(entry_ref, dict) or not isinstance(exit_ref, dict):
            raise TruthPreconditionFailedError("Strategy Factor refs are invalid")
        exact_references: list[ExactInputReference] = [
            ExactInputReference("SNAPSHOT", owner.snapshot_id, owner.snapshot_sha256, PRE_ALPHA_CEILING),
            ExactInputReference("MARKET_DATA", panel.snapshot_id, panel.manifest_sha256, PRE_ALPHA_CEILING),
            ExactInputReference("TRADING_CALENDAR", owner.calendar_version_id, owner.calendar_sha256, PRE_ALPHA_CEILING),
            ExactInputReference("UNIVERSE", owner.universe_version_id, owner.membership_sha256, PRE_ALPHA_CEILING),
            ExactInputReference(
                "CORPORATE_ACTIONS",
                resolved_actions.source_id,
                resolved_actions.content_sha256,
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference("OFFICIAL_TRADING_HOURS", timing.profile_id, timing.content_sha256, PRE_ALPHA_CEILING),
            ExactInputReference("OFFICIAL_COST_RULES", cost.policy_id, cost.content_sha256, PRE_ALPHA_CEILING),
            ExactInputReference("TRADING_RULE_PROFILE", rule.profile_id, rule.content_sha256, PRE_ALPHA_CEILING),
            ExactInputReference("RESEARCH_EXECUTION_POLICY", execution_profile.profile_id, execution_profile.content_sha256, PRE_ALPHA_CEILING),
            ExactInputReference(
                "FACTOR_DEFINITION_ENTRY",
                str(entry_ref.get("factor_definition_version_id")),
                str(entry_ref.get("factor_definition_version_id")).removeprefix("fdv_sha256_"),
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "FACTOR_MATERIALIZATION_ENTRY",
                str(entry_ref.get("materialization_id")),
                self._artifact_content_sha256(
                    entry_ref.get("materialization_artifact_id"),
                    "entry Factor materialization",
                ),
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "FACTOR_DEFINITION_EXIT",
                str(exit_ref.get("factor_definition_version_id")),
                str(exit_ref.get("factor_definition_version_id")).removeprefix("fdv_sha256_"),
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "FACTOR_MATERIALIZATION_EXIT",
                str(exit_ref.get("materialization_id")),
                self._artifact_content_sha256(
                    exit_ref.get("materialization_artifact_id"),
                    "exit Factor materialization",
                ),
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "RESEARCH_STRATEGY_SPEC",
                str(strategy.get("research_strategy_spec_id")),
                self._artifact_content_sha256(
                    strategy.get("research_strategy_spec_artifact_id"),
                    "ResearchStrategySpec",
                ),
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "STRATEGY_DEFINITION",
                str(strategy.get("strategy_definition_version_id")),
                self._artifact_content_sha256(
                    strategy.get("strategy_definition_artifact_id"),
                    "StrategyDefinition",
                ),
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "STRATEGY_STATE",
                str(strategy.get("state_materialization_id")),
                self._artifact_content_sha256(
                    strategy.get("state_materialization_artifact_id"),
                    "Strategy state",
                ),
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "RISK_POLICY_SET",
                str(strategy.get("profile_refs", {}).get("risk_policy_set_version_id")),
                str(strategy.get("profile_refs", {}).get("risk_policy_set_version_id")).removeprefix("rpsv_sha256_"),
                PRE_ALPHA_CEILING,
            ),
            resource_admission,
        ]
        for ordinal, chain in enumerate(strategy.get("decision_chains", [])):
            if not isinstance(chain, dict):
                raise TruthPreconditionFailedError("Strategy decision chain is invalid")
            for kind, identity_key, artifact_key in (
                ("SIGNAL", "signal_artifact_id", "signal_payload_artifact_id"),
                ("PORTFOLIO_INTENT", "portfolio_intent_id", "portfolio_intent_payload_artifact_id"),
                ("TARGET_WEIGHT", "target_weight_vector_id", "target_weight_payload_artifact_id"),
                ("RISK_APPLICATION", "risk_application_receipt_id", "risk_application_receipt_artifact_id"),
                ("RISK_ADJUSTED_WEIGHT", "risk_adjusted_weight_vector_id", "risk_adjusted_weight_artifact_id"),
            ):
                source_id = chain.get(identity_key)
                if not isinstance(source_id, str):
                    raise TruthPreconditionFailedError(
                        f"Strategy decision chain {identity_key} is invalid"
                    )
                exact_references.append(
                    ExactInputReference(
                        f"{kind}:{ordinal:08d}",
                        source_id,
                        self._artifact_content_sha256(
                            chain.get(artifact_key), f"Strategy {kind}"
                        ),
                        PRE_ALPHA_CEILING,
                    )
                )
        initial_cash = strategy_spec.get("initial_cash")
        if not isinstance(initial_cash, str):
            raise TruthPreconditionFailedError("Strategy initial cash is invalid")
        try:
            spec = BacktestRunSpec.create(
                initial_cash=initial_cash,
                initial_holdings=(),
                instruments=instruments,
                sessions=tuple(sessions),
                schedule=tuple(schedule),
                rule_profile=rule,
                cost_policy=cost,
                execution_timing_profile=timing,
                exact_references=tuple(exact_references),
                runtime_identity=_ENGINE_RUNTIME,
                engine_version=DeterministicAshareBacktestEngine.research_engine_version,
            )
        except BacktestContractError as error:
            raise TruthPreconditionFailedError(str(error)) from error
        return spec, execution_inputs, schedule[0].effective_at.date().isoformat()

    def _read_project_artifact(
        self, *, project_id: str, artifact_id: str, label: str
    ) -> bytes:
        descriptor = self.product.require_project_reachable_artifact(
            project_id, artifact_id
        )
        if int(descriptor["byte_size"]) > _MAX_CONTROL_ARTIFACT_BYTES:
            raise TruthPreconditionFailedError(f"{label} exceeds its byte bound")
        return self.product.read_verified_bytes(artifact_id)

    def _read_project_json_artifact(
        self, *, project_id: str, artifact_id: str, label: str
    ) -> tuple[bytes, dict[str, Any]]:
        payload = self._read_project_artifact(
            project_id=project_id, artifact_id=artifact_id, label=label
        )
        return payload, ProductBacktestPublication._decode_json_object(payload, label)

    @staticmethod
    def _verify_lineage_readback(
        *,
        lineage: Mapping[str, Any],
        read_model: Mapping[str, Any],
        data: Mapping[str, Any],
        strategy: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        artifact_ids = data.get("artifact_ids")
        profile_refs = strategy.get("profile_refs")
        if not isinstance(artifact_ids, dict) or not isinstance(profile_refs, dict):
            raise TruthPreconditionFailedError("Result lineage owner context is incomplete")
        expected_data = {
            "raw_capture_id": data.get("raw_capture_id"),
            "raw_artifact_id": artifact_ids.get("LOCAL_DATA_RAW_FILE"),
            "snapshot_id": data.get("snapshot_id"),
            "snapshot_manifest_artifact_id": artifact_ids.get(
                "DATA_TRUTH_SNAPSHOT_MANIFEST"
            ),
            "universe_version_id": data.get("universe_version_id"),
            "universe_membership_artifact_id": artifact_ids.get(
                "UNIVERSE_MEMBERSHIP"
            ),
        }
        expected_strategy = {
            "research_strategy_spec_id": strategy.get("research_strategy_spec_id"),
            "research_strategy_spec_artifact_id": strategy.get(
                "research_strategy_spec_artifact_id"
            ),
            "strategy_version_id": strategy.get("strategy_version_id"),
            "strategy_definition_version_id": strategy.get(
                "strategy_definition_version_id"
            ),
            "strategy_definition_artifact_id": strategy.get(
                "strategy_definition_artifact_id"
            ),
            "risk_policy_set_version_id": profile_refs.get(
                "risk_policy_set_version_id"
            ),
            "decision_chains": strategy.get("decision_chains"),
        }
        expected_execution = {
            "run_id": read_model.get("run_id"),
            "run_spec_id": read_model.get("run_spec_id"),
            "run_spec_artifact_id": read_model.get("run_spec_artifact_id"),
            "target_quantity_vectors": [
                {
                    "target_quantity_vector_id": row.get(
                        "target_quantity_vector_id"
                    ),
                    "source_weight_vector_id": row.get("source_weight_vector_id"),
                    "session_date": row.get("session_date"),
                }
                for row in result.get("target_quantity_vectors", [])
                if isinstance(row, dict)
            ],
            "orders": [
                {
                    "order_id": row.get("order_id"),
                    "source_target_quantity_vector_id": row.get(
                        "source_target_quantity_vector_id"
                    ),
                    "instrument_id": row.get("instrument_id"),
                    "session_date": row.get("session_date"),
                }
                for row in result.get("orders", [])
                if isinstance(row, dict)
            ],
            "fills": [
                {
                    "fill_id": row.get("fill_id"),
                    "order_id": row.get("order_id"),
                    "instrument_id": row.get("instrument_id"),
                    "session_date": row.get("session_date"),
                }
                for row in result.get("fills", [])
                if isinstance(row, dict)
            ],
        }
        expected_result = {
            "result_id": read_model.get("result_id"),
            "backtest_result_id": read_model.get("backtest_result_id"),
            "backtest_result_sha256": result.get("content_sha256"),
            "result_artifact_id": read_model.get("result_artifact_id"),
            "analytics_id": read_model.get("analytics_id"),
            "analytics_artifact_id": read_model.get("analytics_artifact_id"),
        }
        lineage_execution = lineage.get("execution")
        lineage_result = lineage.get("result")
        if (
            lineage.get("project_context_revision_id")
            != read_model.get("project_context_revision_id")
            or lineage.get("truth") != "NOT_FORMAL"
            or lineage.get("admission") != "PRE_ALPHA"
            or lineage.get("data") != expected_data
            or lineage.get("factors")
            != {
                "entry": strategy.get("entry_signal_ref"),
                "exit": strategy.get("exit_signal_ref"),
            }
            or lineage.get("strategy") != expected_strategy
            or lineage_execution != expected_execution
            or lineage_result != expected_result
            or lineage.get("result_lineage_id")
            != read_model.get("result_lineage_id")
        ):
            raise TruthPreconditionFailedError("Product Result lineage binding drifted")

    def get_backtest(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        research_backtest_request_id: str,
    ) -> dict[str, Any]:
        self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT a.artifact_id,a.byte_size
                FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=? AND r.role=?
                  AND r.state='ACTIVE' AND a.state='PUBLISHED'
                ORDER BY r.created_at DESC,r.artifact_reference_id DESC
                """,
                (project_id, READ_MODEL_ROLE),
            ).fetchall()
        finally:
            connection.close()
        for artifact_id, byte_size in rows:
            if int(byte_size) > _MAX_READ_MODEL_BYTES:
                raise TruthPreconditionFailedError("Backtest read model exceeds its bound")
            try:
                _, value = self._read_project_json_artifact(
                    project_id=project_id,
                    artifact_id=str(artifact_id),
                    label="Backtest read model",
                )
            except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
                raise TruthPreconditionFailedError("Backtest read-model bytes are invalid") from error
            if not isinstance(value, dict) or (
                value.get("research_backtest_request_id")
                != research_backtest_request_id
            ):
                continue
            if (
                value.get("project_id") != project_id
                or value.get("project_context_revision_id")
                != project_context_revision_id
                or value.get("truth") != "NOT_FORMAL"
                or value.get("admission") != "PRE_ALPHA"
                or value.get("result_state") != "VALID"
                or value.get("assumption_mode")
                not in {"RESEARCH_APPROXIMATE", "STRICT_FAIL_CLOSED"}
            ):
                raise TruthPreconditionFailedError("Backtest read-model binding drifted")
            connection = self.product._connection(read_only=True)
            try:
                result_row = connection.execute(
                    "SELECT state,backtest_run_id FROM result WHERE result_id=? AND project_id=?",
                    (value.get("result_id"), project_id),
                ).fetchone()
                intent_row = connection.execute(
                    "SELECT state FROM publication_intent WHERE publication_intent_id=? AND project_id=?",
                    (value.get("publication_intent_id"), project_id),
                ).fetchone()
            finally:
                connection.close()
            if (
                result_row is None
                or str(result_row[0]) != "VALID"
                or str(result_row[1]) != value.get("run_id")
                or intent_row is None
                or str(intent_row[0]) != "FINALIZED"
            ):
                raise TruthPreconditionFailedError("Backtest finality is not durable")
            publication = ProductBacktestPublication(self.product)
            artifact_bindings = (
                ("run_spec_artifact_id", "run_id", BACKTEST_RUN_SPEC_ROLE),
                (
                    "research_execution_inputs_artifact_id",
                    "run_id",
                    EXECUTION_INPUTS_ROLE,
                ),
                ("result_artifact_id", "result_id", BACKTEST_RUN_RESULT_ROLE),
                ("ledger_manifest_artifact_id", "result_id", LEDGER_MANIFEST_ROLE),
                (
                    "assumption_receipt_artifact_id",
                    "result_id",
                    ASSUMPTION_RECEIPT_ROLE,
                ),
                ("analytics_artifact_id", "result_id", ANALYTICS_ROLE),
                ("lineage_artifact_id", "result_id", LINEAGE_ROLE),
            )
            verified: dict[str, tuple[bytes, dict[str, Any]]] = {}
            for key, owner_key, role in artifact_bindings:
                artifact = value.get(key)
                if not isinstance(artifact, str):
                    raise TruthPreconditionFailedError("Backtest Artifact identity is absent")
                publication._require_active_reference(
                    str(value[owner_key]), role, artifact
                )
                verified[key] = self._read_project_json_artifact(
                    project_id=project_id, artifact_id=artifact, label=role
                )

            _, run_spec_wire = verified["run_spec_artifact_id"]
            result_payload, result_wire = verified["result_artifact_id"]
            _, execution_wire = verified[
                "research_execution_inputs_artifact_id"
            ]
            _, ledger_wire = verified["ledger_manifest_artifact_id"]
            _, assumption_wire = verified["assumption_receipt_artifact_id"]
            _, analytics_wire = verified["analytics_artifact_id"]
            _, lineage_wire = verified["lineage_artifact_id"]
            execution_profile = execution_wire.get("profile")
            if (
                run_spec_wire.get("run_spec_id") != value.get("run_spec_id")
                or result_wire.get("result_id") != value.get("backtest_result_id")
                or execution_wire.get("schema_version")
                != "v3.research-execution-inputs/1.0.0"
                or not isinstance(execution_profile, dict)
                or assumption_wire.get("schema_version")
                != "v3.research-assumption-receipt/1.0.0"
                or assumption_wire.get("research_backtest_request_id")
                != research_backtest_request_id
                or assumption_wire.get("assumption_mode")
                != value.get("assumption_mode")
                or execution_profile.get("assumption_mode")
                != value.get("assumption_mode")
                or assumption_wire.get("research_execution_profile_id")
                != execution_profile.get("profile_id")
            ):
                raise TruthPreconditionFailedError(
                    "Backtest recovered Artifact relationship drifted"
                )
            publication._reconcile_wire(
                spec=run_spec_wire,
                result=result_wire,
                result_payload=result_payload,
            )
            publication._verify_ledger_manifest(ledger_wire, result_wire)
            publication._verify_analytics_wire(analytics_wire, result_wire)
            publication._verify_lineage_wire(
                lineage_wire,
                project_id=project_id,
                result_id=str(value["result_id"]),
                result=result_wire,
                analytics=analytics_wire,
            )
            export_bindings = (
                (
                    "summary_export_artifact_id",
                    SUMMARY_EXPORT_ROLE,
                    canonical_json_bytes(
                        publication._summary_export_wire(
                            result_wire,
                            analytics_wire,
                            engine_version=str(run_spec_wire["engine_version"]),
                        )
                    ),
                ),
                (
                    "orders_export_artifact_id",
                    ORDERS_EXPORT_ROLE,
                    publication._csv_export_wire(
                        result=result_wire, kind="orders"
                    ),
                ),
                (
                    "fills_export_artifact_id",
                    FILLS_EXPORT_ROLE,
                    publication._csv_export_wire(
                        result=result_wire, kind="fills"
                    ),
                ),
            )
            for key, role, expected_bytes in export_bindings:
                artifact_id = value.get(key)
                if not isinstance(artifact_id, str):
                    raise TruthPreconditionFailedError(
                        "Backtest export Artifact identity is absent"
                    )
                publication._require_active_reference(
                    str(value["result_id"]), role, artifact_id
                )
                descriptor = self.product.require_project_reachable_artifact(
                    project_id, artifact_id
                )
                if (
                    descriptor["semantic_role"] != role
                    or self.product.read_verified_bytes(artifact_id)
                    != expected_bytes
                ):
                    raise TruthPreconditionFailedError(
                        "Backtest export Artifact binding drifted"
                    )

            from .product_data import ProductDataService

            data = ProductDataService(self.product).get_local_dataset(
                project_id=project_id,
                project_context_revision_id=project_context_revision_id,
                snapshot_id=str(value["snapshot_id"]),
            )
            if data.get("universe_version_id") != value.get("universe_version_id"):
                raise TruthPreconditionFailedError(
                    "Backtest Data owner binding drifted"
                )
            ManifestAwareLocalSnapshotReader(self.product).resolve(
                project_id=project_id,
                snapshot_id=str(value["snapshot_id"]),
                universe_version_id=str(value["universe_version_id"]),
            )
            raw_artifact_id = data.get("artifact_ids", {}).get("LOCAL_DATA_RAW_FILE")
            if not isinstance(raw_artifact_id, str):
                raise TruthPreconditionFailedError("Backtest RawCapture Artifact is absent")
            self._read_project_artifact(
                project_id=project_id,
                artifact_id=raw_artifact_id,
                label="RawCapture",
            )
            strategy = ProductStrategyService(self.product).get_strategy(
                project_id=project_id,
                project_context_revision_id=project_context_revision_id,
                research_strategy_spec_id=str(value["research_strategy_spec_id"]),
            )
            self._verify_lineage_readback(
                lineage=lineage_wire,
                read_model=value,
                data=data,
                strategy=strategy,
                result=result_wire,
            )
            return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
        raise NotFoundError("Product research Backtest read model is unavailable")

    def get_latest_backtest(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
    ) -> dict[str, Any]:
        """Return the newest VALID product Backtest through full owner verification."""
        self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        connection = self.product._connection(read_only=True)
        try:
            row = connection.execute(
                """
                SELECT a.artifact_id,a.byte_size
                FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=? AND r.role=?
                  AND r.state='ACTIVE' AND a.state='PUBLISHED'
                ORDER BY r.created_at DESC,r.artifact_reference_id DESC
                LIMIT 1
                """,
                (project_id, READ_MODEL_ROLE),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise NotFoundError("Product research Backtest read model is unavailable")
        if int(row[1]) > _MAX_READ_MODEL_BYTES:
            raise TruthPreconditionFailedError("Backtest read model exceeds its bound")
        try:
            _, candidate = self._read_project_json_artifact(
                project_id=project_id,
                artifact_id=str(row[0]),
                label="Backtest read model",
            )
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(
                "Backtest read-model bytes are invalid"
            ) from error
        request_id = candidate.get("research_backtest_request_id")
        if not isinstance(request_id, str):
            raise TruthPreconditionFailedError("Backtest read-model identity is invalid")
        return self.get_backtest(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            research_backtest_request_id=request_id,
        )


__all__ = [
    "ExecutionPolicyRegistry",
    "PRODUCT_RESEARCH_BACKTEST_OPERATION",
    "ProductResearchBacktestService",
    "ProductResearchBacktestSubmission",
]
