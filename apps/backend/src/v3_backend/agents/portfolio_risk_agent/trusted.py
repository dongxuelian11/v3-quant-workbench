from __future__ import annotations

"""Resolver-owned trusted evidence representations (R-C trust boundary).

`ScenarioEvidenceBundle` remains an explicitly untrusted projection DTO for
rendering/serialization.  Trusted R consumers accept only
`ResolvedScenarioEvidenceBundle` instances, which are produced exclusively by
`resolve_scenario_evidence` over canonical owner objects.

Plain construction paths cannot obtain trusted status:

- constructing the public DTO (with or without `binding_gaps=()`),
- setting any boolean flag,
- copying ids or content hashes,
- reproducing a deterministic content hash,
- deserializing ordinary JSON into the public DTO,

because the trusted wrapper's constructor requires the module-private
resolver origin, and no public factory exposes it.  There is no trust flag.
"""

import hashlib
from dataclasses import dataclass

from v3_backend.agents.contracts import deterministic_json

from .contracts import ScenarioComparisonInvariant, ScenarioEvidenceBundle


class _ResolverToken:
    """Module-private token type whose instances cannot be fabricated."""

    __slots__ = ()

    def __new__(cls) -> "_ResolverToken":
        raise TypeError("resolver trust token cannot be fabricated")


_RESOLVER_TOKEN = object.__new__(_ResolverToken)


class _ResolverOrigin:
    """Module-private origin marker stamped only by the system resolver."""

    __slots__ = ("_token",)

    def __init__(self, token: object) -> None:
        if token is not _RESOLVER_TOKEN:
            raise TypeError("resolver origin can only be stamped by the system resolver")
        object.__setattr__(self, "_token", token)


_RESOLVER_ORIGIN = _ResolverOrigin(_RESOLVER_TOKEN)


@dataclass(frozen=True, slots=True, init=False)
class ResolvedScenarioEvidenceBundle:
    """Trusted scenario evidence produced exclusively by the system resolver.

    Frozen; the constructor is not a public trust path: it requires the
    module-private resolver origin object.  Callers can inspect the payload
    but cannot mint trusted status.
    """

    payload: ScenarioEvidenceBundle
    comparison_invariant: ScenarioComparisonInvariant | None

    def __init__(
        self,
        payload: ScenarioEvidenceBundle,
        comparison_invariant: ScenarioComparisonInvariant | None,
        origin: object,
    ) -> None:
        if origin is not _RESOLVER_ORIGIN:
            raise TypeError(
                "ResolvedScenarioEvidenceBundle is resolver-owned trusted evidence; "
                "manual construction is not a trust path"
            )
        if type(payload) is not ScenarioEvidenceBundle:
            raise TypeError(
                "trusted scenario evidence must wrap an exact ScenarioEvidenceBundle payload"
            )
        if comparison_invariant is not None and type(comparison_invariant) is not ScenarioComparisonInvariant:
            raise TypeError(
                "trusted scenario evidence comparison invariant must be an exact ScenarioComparisonInvariant"
            )
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "comparison_invariant", comparison_invariant)

    @property
    def deterministic_sha256(self) -> str:
        """Deterministic identity covering payload and comparison invariant."""

        return hashlib.sha256(
            deterministic_json(
                {
                    "payload_sha256": self.payload.deterministic_sha256,
                    "comparison_invariant_id": (
                        self.comparison_invariant.invariant_id
                        if self.comparison_invariant is not None
                        else None
                    ),
                }
            ).encode("utf-8")
        ).hexdigest()

    @property
    def binding_gaps(self) -> tuple[str, ...]:
        return self.payload.binding_gaps

    @property
    def intent(self) -> object:
        return self.payload.intent

    @property
    def construction_spec_version_id(self) -> str:
        return self.payload.construction_spec_version_id

    @property
    def construction_spec_content_sha256(self) -> str:
        return self.payload.construction_spec_content_sha256

    @property
    def risk_policy_set(self) -> object:
        return self.payload.risk_policy_set

    @property
    def cost_policy(self) -> object:
        return self.payload.cost_policy

    @property
    def target(self) -> object | None:
        return self.payload.target

    @property
    def risk_adjusted(self) -> object | None:
        return self.payload.risk_adjusted

    @property
    def backtest(self) -> object | None:
        return self.payload.backtest

    @property
    def analytics(self) -> object | None:
        return self.payload.analytics

    @property
    def reviewer_reports(self) -> tuple[object, ...]:
        return self.payload.reviewer_reports

    @property
    def treatment_context_key(self) -> tuple[tuple[str, str], ...]:
        return self.payload.treatment_context_key


__all__ = ["ResolvedScenarioEvidenceBundle"]
