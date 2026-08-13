from __future__ import annotations

from v3_backend.adapters.tdx_formula import TdxDataSemanticProfileVersion, TdxTranslator
from v3_backend.agents.contracts import PermissionLevel
from v3_backend.agents.permissions import require_permission
from v3_backend.domain.agent_research_loop import (
    ResearchActionDraft,
    ResearchActionType,
    ResearchLoopBudgetVersion,
)
from v3_backend.domain.factor_assets import CatalogQuery, FactorDraftProposal
from v3_backend.domain.factor_library import (
    FactorApplicationSpec,
    FactorEvidenceExplanation,
    FactorLibraryService,
    FactorTranslationPreview,
)

from .contracts import FACTOR_AGENT_TOOL_CATALOG, FactorAgentError
from .worker import FactorDraftWorker


class FactorAgentService:
    """L0/L1 orchestration only; confirmation/application is intentionally absent."""

    def __init__(
        self,
        *,
        permission: object,
        library: FactorLibraryService,
        translator: TdxTranslator,
        data_profile: TdxDataSemanticProfileVersion,
        worker: FactorDraftWorker | None = None,
    ) -> None:
        self._permission = permission
        self._library = library
        self._translator = translator
        self._data_profile = data_profile
        self._worker = worker

    @property
    def tool_inventory(self) -> tuple[str, ...]:
        decision = require_permission(self._permission, PermissionLevel.L0_READ)
        levels = {PermissionLevel.L0_READ}
        if decision.normalized is PermissionLevel.L1_DRAFT:
            levels.add(PermissionLevel.L1_DRAFT)
        return tuple(item.name for item in FACTOR_AGENT_TOOL_CATALOG if item.required_permission in levels)

    def search_catalog(self, query: CatalogQuery) -> tuple[dict[str, object], ...]:
        require_permission(self._permission, PermissionLevel.L0_READ)
        return tuple(value.to_wire() for value in self._library.search(query))

    def read_factor(self, asset_key: str) -> dict[str, object]:
        require_permission(self._permission, PermissionLevel.L0_READ)
        return self._library.read(asset_key).to_wire()

    def explain_evidence(self, asset_key: str) -> FactorEvidenceExplanation:
        require_permission(self._permission, PermissionLevel.L0_READ)
        return self._library.explain_evidence(asset_key)

    def draft_natural_language(self, intent: str) -> FactorDraftProposal:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        if self._worker is None:
            raise FactorAgentError("FACTOR_DRAFT_WORKER_NOT_CONFIGURED", "typed worker is required")
        response = self._worker.draft(intent)
        payload = response.payload
        return FactorDraftProposal.create(
            natural_language_intent=intent,
            draft_kind=payload.draft_kind,
            draft_payload=payload.draft_payload,
            rationale=payload.rationale,
            expected_inputs=payload.expected_inputs,
            expected_output=payload.expected_output,
        )

    def preview_tdx(self, proposal: FactorDraftProposal) -> FactorTranslationPreview:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        return FactorTranslationPreview.from_proposal(
            proposal,
            translator=self._translator,
            data_profile=self._data_profile,
            provenance_ref=f"factor-agent-proposal:{proposal.proposal_id}",
        )

    def draft_import_action(
        self,
        application_spec: FactorApplicationSpec,
        *,
        resource_profile_ref: str,
        budget: ResearchLoopBudgetVersion,
    ) -> ResearchActionDraft:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        application_spec.assert_canonical()
        return ResearchActionDraft.create(
            action_type=ResearchActionType.FACTOR_IMPORT,
            exact_input_refs=(
                application_spec.application_spec_id,
                "sha256:" + application_spec.content_hash,
                application_spec.preview_id,
                application_spec.factor_definition_version_id,
            ),
            requested_capability="factor.import.USER_EXECUTION_AUTHORITY_NOT_AVAILABLE",
            expected_output_kind="NOT_AVAILABLE",
            resource_profile_ref=resource_profile_ref,
            budget_version_id=budget.budget_version_id,
        )

    def draft_evaluate_action(
        self,
        factor_definition_version_id: str,
        *,
        evaluation_context_ref: str,
        resource_profile_ref: str,
        budget: ResearchLoopBudgetVersion,
    ) -> ResearchActionDraft:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        return ResearchActionDraft.create(
            action_type=ResearchActionType.FACTOR_EVALUATE,
            exact_input_refs=(factor_definition_version_id, evaluation_context_ref),
            requested_capability="factor.evaluate",
            expected_output_kind="FactorEvaluation",
            resource_profile_ref=resource_profile_ref,
            budget_version_id=budget.budget_version_id,
        )
