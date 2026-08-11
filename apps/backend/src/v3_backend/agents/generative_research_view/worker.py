from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ..contracts import PermissionLevel
from ..permissions import require_permission
from .models import EvidenceId, ResearchViewSpecV1, StructuredResearchViewResult


PYDANTIC_AI_VERIFIED_VERSION = "2.27.0"


class PydanticResearchViewWorker:
    """Track M L1-only structured proposal adapter; never a data or execution authority."""

    def __init__(self, *, model: Model, permission: object) -> None:
        try:
            installed = version("pydantic-ai-slim")
        except PackageNotFoundError as exc:
            raise RuntimeError("pydantic-ai-slim is required") from exc
        if installed != PYDANTIC_AI_VERIFIED_VERSION:
            raise RuntimeError(
                f"pydantic-ai-slim version mismatch: expected {PYDANTIC_AI_VERIFIED_VERSION}, got {installed}"
            )
        self._model = model
        self._permission = permission

    def run(
        self,
        *,
        prompt: str,
        session_view_id: str,
        evidence_ids: tuple[EvidenceId, ...],
        text_draft: str | None = None,
    ) -> StructuredResearchViewResult:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        allowed_evidence = set(evidence_ids)
        instructions = (
            "Return only v3.generative_research_view/1.0.0 JSON as an L1_DRAFT proposal. "
            "Use only the supplied session_view_id and evidence IDs. Canonical blocks contain selectors, never raw canonical values. "
            "Do not emit JSX, HTML, JavaScript, CSS, ECharts options, formulas, Truth, Admission, Validation, execution, or publication claims. "
            f"session_view_id={session_view_id}; evidence_ids={','.join(evidence_ids)}"
        )
        agent: Agent[None, ResearchViewSpecV1] = Agent(
            self._model,
            output_type=ResearchViewSpecV1,
            instructions=instructions,
            retries={"output": 1},
        )
        try:
            view_spec = ResearchViewSpecV1.model_validate(agent.run_sync(prompt).output)
            if view_spec.session_view_id != session_view_id:
                raise ValueError("structured view session does not match the active session")
            proposed_evidence = {
                evidence_id
                for block in view_spec.blocks
                for evidence_id in block.evidence_ids
            }
            if not proposed_evidence.issubset(allowed_evidence):
                raise ValueError("structured view references evidence outside the active session")
            return StructuredResearchViewResult(
                status="VALID",
                view_spec=view_spec,
                error=None,
                text_draft=text_draft,
            )
        except Exception:
            return StructuredResearchViewResult(
                status="INVALID",
                view_spec=None,
                error="INVALID_STRUCTURED_RESEARCH_VIEW",
                text_draft=text_draft,
            )
