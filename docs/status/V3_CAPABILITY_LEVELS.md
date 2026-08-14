# V3 Capability Levels

Authority version: `1.0.1`
Status vocabulary: mandatory for repository documentation, Ledgers, PRs, reviews, CI reports, and product-state claims.

Capability maturity is evidence-based and monotonic only when every promotion rule is met. Levels are not synonyms for task progress, code volume, confidence, or a generic PASS.

## Positive maturity levels

| Level | What it proves | What it does not prove | Minimum evidence | Promotion rule |
|---|---|---|---|---|
| `DESIGNED` | A bounded contract, authority owner, inputs/outputs, failure modes, and acceptance evidence are specified. | No implementation, runtime binding, or product surface. | Reviewed design artifact with named owner and forbidden shortcuts. | Promote only when the design is internally consistent with P0 authority and unresolved decisions are explicit. |
| `MODULE_IMPLEMENTED` | Source implementing the bounded module exists. | Correctness, acceptance, integration, product connection, or production availability. | Exact source paths and build/import evidence. | Promote only after the implementation is present on the referenced exact SHA. |
| `MODULE_ACCEPTED` | The module passes its bounded correctness, determinism, negative, and contract tests on an exact SHA. | Semantic ownership across the whole system, downstream integration, UI, or production runtime. | Exact-SHA test results and scope-specific review with no unresolved blocking finding. | Promote only when the module acceptance gate is fully evidenced; green unit tests alone are insufficient if required negative or semantic tests are absent. |
| `SEMANTIC_OWNER_ACCEPTED` | The canonical owner and its truth/admission rules are accepted for the stated scope. | That callers resolve actual payload correctly, that integrations are wired, or that the product exposes the capability. | Accepted owner contract, authority tests, persistence/provenance evidence, and exact-SHA review. | Promote only when no competing owner/second engine exists and truth boundaries fail closed. |
| `INTEGRATION_ACCEPTED` | Named upstream and downstream owners exchange verified payloads through the canonical adapter/transport for the stated scenarios. | Desktop/product connection, user-visible acceptance, packaging, or all production environments. | End-to-end integration tests with actual payload resolution, negative cross-binding tests, provenance receipts, and exact-SHA evidence. | Promote only when the complete named path is tested without shadow contracts or hidden fallbacks. |
| `PRODUCT_CONNECTED` | The production-shaped product surface is connected through its real bridge/handler to the accepted integration and shows truthful unavailable/degraded states. | User visual acceptance, deployability, operational readiness, or production availability. | Real runtime/DOM evidence, handler/bridge mapping, failure-state tests, and exact-SHA product-flow proof. | Promote only when the product uses the canonical path and cannot silently fall back to a demo or fixture. |
| `USER_VISUAL_ACCEPTED` | The stated product flows have been reviewed and accepted for visual hierarchy, Chinese-first language, low-chrome/no-box behavior, accessibility, and relevant viewport/state coverage. | Backend authority, numeric correctness, integration acceptance, or production availability. | Current exact-SHA visual evidence across required states/viewports plus human acceptance. | Promote only after the required user-visual review; screenshots alone do not supply semantic authority. |
| `PRODUCTION_AVAILABLE` | The capability is genuinely usable in the packaged production profile through canonical owners, verified payloads, supported dependencies, operational controls, and truthful product surfaces. | Broader capability not named by the claim, live trading, or future environments. | All upstream levels as applicable, packaging/deployment evidence, real production-runtime health, security/operations evidence, and current exact-SHA verification. | Promotion requires every applicable upstream owner, integration, product, operational, and evidence gate to be satisfied. |

## Orthogonal negative and unknown states

These states do not form a lower-to-higher ladder. They describe a separate fact and must remain literal.

| State | Meaning | Required handling |
|---|---|---|
| `NOT_AVAILABLE` | The capability cannot be used in the named context. | State the missing owner, handler, dependency, authority, or evidence; do not substitute a fixture. |
| `NOT_RUN` | The action or validation has not been executed. | Do not report PASS, failure, or completion; name the exact next action if authorized. |
| `PENDING` | Work or evidence has begun or is expected but has no terminal result. | Preserve the dependency and current observed state. |
| `BLOCKED` | A named condition prevents authorized progress. | Record the blocker and use `STOP_FOR_REVIEW` where authority, source truth, or scope conflicts. |
| `UNKNOWN` | Current evidence cannot determine the state. | Refresh authoritative sources; do not infer a favorable state. |
| `DEPRECATED` | The capability or contract remains identifiable but must not be used for new work. | Point to the replacement and preserve migration/provenance truth. |

`PRE_ALPHA` and `FORMAL` are truth/admission classifications used by their owning contracts; they are not substitutes for capability maturity levels. `PRE_ALPHA` never promotes itself to `FORMAL` through a capability claim.

## Evidence and promotion rules

1. Every claim names the capability, scope, exact level/state, exact SHA or artifact identity, and evidence source.
2. The downstream claim cannot exceed the meet of required upstream truth/admission and capability levels.
3. Promotion requires new evidence. Rewording, a branch name, a PR merge, or a UI label cannot promote maturity.
4. A higher level does not erase orthogonal states for other paths or environments.
5. A merged backend PR may prove `SEMANTIC_OWNER_ACCEPTED` for its stated owner, but not `PRODUCTION_AVAILABLE`.
6. Green unit tests may prove `MODULE_ACCEPTED`, but not `PRODUCT_CONNECTED`.
7. Visual screenshot review may prove `USER_VISUAL_ACCEPTED`, but not backend authority.
8. A runtime capability name or advertised port does not prove that a production handler exists or is bound.

## PASS and COMPLETE language

`PASS` is permitted only for a named gate with exact evidence, such as “authority validator PASS on SHA …”. It is not a maturity level.

Generic `COMPLETE` is forbidden. A document may use the word only when it states exactly what is complete, for example:

- `MODULE_ACCEPTED complete for Factor IR parser v1 on <sha>`;
- `INTEGRATION_ACCEPTED complete for canonical evidence read-only path on <sha>`.

It must also state what the claim does not prove. `NOT_RUN`, `PENDING`, `BLOCKED`, `UNKNOWN`, and `NOT_AVAILABLE` cannot be upgraded by generic completion language.
