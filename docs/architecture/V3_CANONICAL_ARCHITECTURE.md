# V3 Canonical Architecture

Authority version: `1.0.1`
Status: target canonical architecture and owner map; not a claim that all integrations or product connections exist.

## 1. Mandatory cross-owner flow

Every formal computation path uses:

```text
Canonical Ref
→ Resolver
→ Verified Payload
→ Deterministic Engine
→ Content-addressed Result
→ Artifact/Provenance Receipt
```

An ID owner is not necessarily the actual numeric payload owner. The architecture must bind both. A valid-looking reference plus independently supplied values is rejected unless the values are resolved from, or verified byte-for-byte against, the canonical owner or verified Artifact Store.

## 2. Runtime layer separation

Every capability is described and evidenced separately at these layers:

```text
Domain Module
→ Semantic Owner
→ Integration Adapter
→ Production Runtime Handler
→ Desktop Bridge
→ Product Surface
```

The presence of one layer does not imply the next. A module is not a handler, a handler name is not a bound runtime, and a visible surface is not proof of canonical computation.

## 3. Global ownership rules

- Canonical owners validate, persist, and own truth. Callers supply intent and references, not authoritative numeric payloads.
- Resolvers validate owner identity, content identity, schema/version, relationship bindings, PIT/as-of context, and actual bytes/values before computation.
- Deterministic engines have closed inputs and emit content-addressed results. They do not perform ambient database, UI, network, or LLM lookups.
- Artifact/Provenance receipts bind exact inputs, actual payload hashes, engine/runtime versions, outputs, and admission state.
- Downstream truth/admission cannot exceed the meet of upstream truth/admission.
- Missing production wiring remains `NOT_AVAILABLE`; a development fixture remains explicitly development-only.

## 4. Canonical owner map

### 4.1 Data Truth

- **Owner:** Data Truth semantic owner and canonical market-data repositories.
- **Responsibility:** Admit source observations, normalize instruments/calendars/fields, preserve raw capture and PIT/as-of knowledge, and publish immutable snapshots.
- **Canonical Inputs:** Source identity, raw capture/artifact, field semantics, calendar, observation time, available time, adjustment policy.
- **Canonical Payload Owner:** Data Truth repositories plus verified raw/snapshot artifacts own actual market values and availability metadata.
- **Required Resolver:** Snapshot/data resolver that retrieves and verifies actual series/rows by canonical refs and knowledge boundary.
- **Deterministic Engine:** Provider ingestion, normalization, PIT policy, snapshot construction, and canonical hashing.
- **Canonical Outputs:** Admitted observations, `DataSnapshotVersion`, calendars, instruments, availability and rejection receipts.
- **Artifact/Provenance:** Raw capture hash, normalized payload hash, provider/source version, field mapping, timestamps, calendar and admission receipt.
- **Truth/PIT Boundary:** No later observation, current membership, or inferred adjustment may enter an earlier as-of context.
- **Runtime Surface:** Provider adapters, repositories, snapshot resolver, ingestion worker, and health/capability surface.
- **Product Surface:** Data/source status, snapshot selector, PIT/as-of visibility, unavailable/degraded state.
- **Forbidden Shortcuts:** Caller-supplied prices under a valid snapshot ID; current data substituted for historical data; Demo data as formal truth.
- **Current Implementation Notes (conservative):** Current main contains Data Truth domain, provider-ingestion, PIT, migration, repository and adapter seams. External/provider admission and full production connection require current evidence; systemic payload/integration re-audit is `PENDING`.

### 4.2 Universe

- **Owner:** Universe semantic owner.
- **Responsibility:** Define immutable Universe versions and exact historical membership under a named knowledge/effective-time policy.
- **Canonical Inputs:** Instrument master, membership events, index/industry/listing/ST/suspension facts, calendar, as-of/effective time.
- **Canonical Payload Owner:** Universe repository and membership artifact own the actual member set and per-member eligibility facts.
- **Required Resolver:** Universe resolver that verifies membership artifact bytes, version identity, time scope, and Data Truth bindings.
- **Deterministic Engine:** Membership/filter evaluator over verified historical facts.
- **Canonical Outputs:** `UniverseVersion`, ordered membership artifact, exclusions and resolution receipt.
- **Artifact/Provenance:** Exact member-set hash, rule/version hash, source fact refs, as-of/effective boundary and exclusion reasons.
- **Truth/PIT Boundary:** Historical membership only; no survivorship-biased current constituent substitution.
- **Runtime Surface:** Universe repository/resolver and deterministic construction handler.
- **Product Surface:** Universe Builder, membership inspection, exclusions, PIT status and evidence.
- **Forbidden Shortcuts:** Caller-created symbol list presented as a canonical Universe; current index members used for past dates.
- **Current Implementation Notes (conservative):** Current main contains Universe contracts and Data Truth membership policies/tests. Exact maturity beyond those bounded slices is `PENDING` systemic re-audit.

### 4.3 Factor

- **Owner:** `FactorDefinitionVersion` and canonical Factor semantic owner.
- **Responsibility:** Own Factor IR, operator semantics, validation, deterministic evaluation and immutable evaluation/materialization outputs.
- **Canonical Inputs:** Factor definition/IR, verified Data Truth series, Universe membership, calendar, runtime/operator profile, PIT context.
- **Canonical Payload Owner:** Data Truth/Universe own actual inputs; Factor owner owns definition semantics and resulting values.
- **Required Resolver:** Factor input resolver that retrieves actual input series and membership from canonical owners and verifies bindings.
- **Deterministic Engine:** The sole canonical Factor evaluator; TDX lowers to the same IR/evaluator.
- **Canonical Outputs:** Factor evaluation, `FeatureMaterialization`, diagnostics, content-addressed values and receipts.
- **Artifact/Provenance:** IR hash, operator/runtime versions, exact input payload hashes, Universe/Snapshot refs, output hash and diagnostics.
- **Truth/PIT Boundary:** Evaluation must use only data available under the bound as-of context and historical membership.
- **Runtime Surface:** Factor resolver/evaluator handler, optional isolated third-party adapters, task/worker boundary.
- **Product Surface:** Factor Lab/library/editor/evidence, exact unavailable and draft states.
- **Forbidden Shortcuts:** Frontend math; second TDX VM; caller-provided series with a valid Factor/Snapshot ID; third-party output minting truth.
- **Current Implementation Notes (conservative):** Current main contains canonical Factor IR/evaluator, Factor assets/library, TDX translation, adapters, tests, and merged P Factor Agent/Library work. Production Agent execution remains `NOT_AVAILABLE / NOT_RUN`; payload and product maturity re-audit is `PENDING`.

### 4.4 Dataset

- **Owner:** Dataset semantic owner.
- **Responsibility:** Bind immutable features, labels, samples, splits and leakage controls into a reproducible Dataset version.
- **Canonical Inputs:** Verified FeatureMaterializations, labels from canonical data, Universe/Snapshot refs, sampling/split policy, knowledge times.
- **Canonical Payload Owner:** Dataset/materialization store owns actual sample and label bytes; upstream owners retain source truth.
- **Required Resolver:** Dataset resolver that retrieves actual feature/label materializations and verifies membership, time, schema and hashes.
- **Deterministic Engine:** Dataset assembly, alignment, split and leakage validation.
- **Canonical Outputs:** `DatasetVersion`, split manifests, sample/label artifacts, exclusion and leakage reports.
- **Artifact/Provenance:** Exact materialization hashes, row keys, time boundaries, split policy/version, schema and output hash.
- **Truth/PIT Boundary:** Features and labels obey their distinct observation/availability windows; future leakage is rejected.
- **Runtime Surface:** Dataset construction/resolution handler and isolated storage adapters.
- **Product Surface:** Dataset inspector, split/leakage evidence and unavailable state.
- **Forbidden Shortcuts:** Training from caller arrays while citing a Dataset ID; relabeling without a new version; implicit row alignment.
- **Current Implementation Notes (conservative):** Current main contains Dataset domain models/contracts and accepted historical tests. Resolver-backed actual payload and product/runtime maturity remain `PENDING` re-audit.

### 4.5 Experiment

- **Owner:** Experiment semantic owner.
- **Responsibility:** Define comparable context, treatments, runs, metrics, rewards and evidence without cross-context ranking.
- **Canonical Inputs:** Exact Dataset/Model/Strategy/Portfolio/Backtest/result refs, controlled-treatment declaration, runtime profile and context.
- **Canonical Payload Owner:** Referenced canonical owners and Artifact Store own actual inputs/results; Experiment owns comparison context and run record.
- **Required Resolver:** Experiment resolver that verifies every referenced payload/result and comparability context.
- **Deterministic Engine:** Run identity, metric derivation where owned, controlled comparison and reward computation.
- **Canonical Outputs:** Experiment run/result, metric/reward artifacts and `INCOMPARABLE_CONTEXT` decisions.
- **Artifact/Provenance:** Context hash, treatment delta, all exact input/result hashes, engine versions and comparison receipt.
- **Truth/PIT Boundary:** Material context mismatch is `INCOMPARABLE_CONTEXT` unless explicitly controlled.
- **Runtime Surface:** Experiment coordinator backed by canonical Task/Worker and Artifact owners.
- **Product Surface:** Experiment table, comparison view, context diff, metrics and evidence.
- **Forbidden Shortcuts:** Context-free “best” ranking; metrics accepted only from caller summaries; missing runs treated as zero.
- **Current Implementation Notes (conservative):** Current main contains Experiment domain models/metrics and historical acceptance evidence. Systemic payload/comparison/product re-audit is `PENDING`.

### 4.6 Model

- **Owner:** Model semantic owner and immutable Model versions.
- **Responsibility:** Own training/prediction specifications, deterministic/declared runtime, model artifacts and prediction lineage.
- **Canonical Inputs:** Resolved Dataset samples/splits, model definition/hyperparameters, seed, runtime/dependency profile.
- **Canonical Payload Owner:** Dataset owns actual samples/labels; verified Artifact Store owns model bytes; Model owner owns training/prediction semantics.
- **Required Resolver:** Dataset/model artifact resolver that retrieves and verifies actual sample/model bytes and exact bindings.
- **Deterministic Engine:** Versioned training/prediction worker behind an isolated adapter/API/CLI boundary.
- **Canonical Outputs:** Model version, training result, prediction materialization, diagnostics and receipts.
- **Artifact/Provenance:** Dataset/split hashes, code/dependency/runtime hashes, seed, parameters, model bytes hash, prediction hash.
- **Truth/PIT Boundary:** Training and prediction data must respect bound availability time, split, and reproducibility profile.
- **Runtime Surface:** Model worker adapter, task handler, artifact resolver and resource governance.
- **Product Surface:** Model Lab, Study/Trial inspection, training/prediction evidence and unavailable state.
- **Forbidden Shortcuts:** Caller arrays under a Dataset ID; unpinned environment; Q candidate treated as current-main authority; model prose as result.
- **Current Implementation Notes (conservative):** Current main contains Model domain/runtime and subprocess worker seams. Q Model Agent PR #27 is OPEN and unmerged; production Agent execution is `NOT_AVAILABLE / NOT_RUN`; broader maturity is `PENDING`.

### 4.7 Strategy

- **Owner:** Strategy definition/evaluation semantic owner.
- **Responsibility:** Own canonical Strategy IR, component semantics, validation, deterministic evaluation and intent production without owning execution.
- **Canonical Inputs:** Strategy definition, verified Factor/Model/score artifacts, Dataset/Universe/Snapshot context, evaluation profile.
- **Canonical Payload Owner:** Factor/Model/Data owners own actual scores/data; Strategy owner owns IR semantics and emitted Signal/Selection/Intent.
- **Required Resolver:** Strategy binding resolver that retrieves and verifies actual score/input artifacts against canonical refs.
- **Deterministic Engine:** Canonical Strategy compiler/evaluator over closed verified inputs.
- **Canonical Outputs:** Strategy evaluation, Signal/Selection and `PortfolioIntent` artifacts; never orders/fills.
- **Artifact/Provenance:** IR/compiler/runtime hashes, exact input payload hashes, evaluation binding and output hashes.
- **Truth/PIT Boundary:** Explicit decision time and upstream PIT truth; downstream truth cannot exceed upstream admission.
- **Runtime Surface:** Strategy evaluator handler and isolated custom-code worker profile when separately accepted.
- **Product Surface:** Strategy visual/code/split views, drafts, validation, evidence and handoff intent.
- **Forbidden Shortcuts:** Strategy-owned broker/account state; independent caller score vectors; UI execution; hidden custom-code capabilities.
- **Current Implementation Notes (conservative):** Current main contains Strategy IR, binding, evaluator and artifact modules with historical tests. Resolver-backed score authority and complete product/runtime connection are `PENDING` re-audit.

### 4.8 Signal / Selection

- **Owner:** Signal/Selection semantic owner, normally emitted by the accepted Strategy evaluation.
- **Responsibility:** Preserve exact scored/ranked decisions, tie-breaking, eligibility and decision-time context for downstream sizing.
- **Canonical Inputs:** Verified Strategy/Factor/Model output payloads, Universe membership and decision context.
- **Canonical Payload Owner:** Upstream canonical output artifact owns actual scores; Signal/Selection owner owns filtered/ranked result semantics.
- **Required Resolver:** Resolver for the exact upstream score/prediction artifact and membership artifact.
- **Deterministic Engine:** Closed filter/rank/select evaluator with canonical tie-breaking.
- **Canonical Outputs:** Immutable Signal/Selection artifact and exclusions.
- **Artifact/Provenance:** Source output hash, rule/version, Universe/time binding, selected-set/order hash and exclusions.
- **Truth/PIT Boundary:** Decision-time availability and historical eligibility are explicit.
- **Runtime Surface:** Strategy/selection handler feeding Portfolio intent construction.
- **Product Surface:** Ranked candidates, exclusions, evidence and handoff.
- **Forbidden Shortcuts:** Caller score vector paired with a valid prediction ref; nondeterministic tie-breaking; current eligibility substituted historically.
- **Current Implementation Notes (conservative):** Current main contains relevant contracts and Strategy artifacts/evaluator seams. Standalone end-to-end maturity is not inferred and remains `PENDING` re-audit.

### 4.9 Portfolio

- **Owner:** Portfolio construction semantic owner.
- **Responsibility:** Convert verified intent/scores and portfolio state into target weights under explicit constraints, cash and lot policies.
- **Canonical Inputs:** Resolved Signal/Selection/Intent payload, verified portfolio state, prices where required, constraints and effective time.
- **Canonical Payload Owner:** Upstream artifacts and Portfolio state owner own actual numeric inputs; Portfolio owner owns target-weight semantics.
- **Required Resolver:** Resolver for score/intent, portfolio state, eligible Universe and required market payloads.
- **Deterministic Engine:** Canonical allocation/sizing engine.
- **Canonical Outputs:** `TargetWeightVector`, allocation diagnostics and receipt.
- **Artifact/Provenance:** Exact input hashes, constraint/profile version, effective time, target-weight hash and residual-cash policy.
- **Truth/PIT Boundary:** Portfolio state and prices are as-of bound; no future fills or valuation leakage.
- **Runtime Surface:** Portfolio construction handler and canonical artifact publication.
- **Product Surface:** Portfolio intent/weights, constraints, diagnostics and evidence.
- **Forbidden Shortcuts:** Caller weights/scores accepted under valid refs; account/broker mutation; silent normalization or cash assumptions.
- **Current Implementation Notes (conservative):** Current main contains weight and Portfolio construction domain/runtime modules with historical acceptance. Systemic actual-payload and production integration re-audit is `PENDING`.

### 4.10 Risk

- **Owner:** Risk semantic owner.
- **Responsibility:** Apply explicit risk constraints/models to verified target weights and market/portfolio context without changing upstream identity silently.
- **Canonical Inputs:** Resolved target weights, risk model/data, portfolio state, Universe, constraints and effective time.
- **Canonical Payload Owner:** Portfolio/Data/Risk-model owners own actual inputs; Risk owner owns adjusted-weight and risk-report semantics.
- **Required Resolver:** Resolver for exact target vector, risk payloads, holdings/market context and constraint versions.
- **Deterministic Engine:** Canonical risk application engine with fail-closed constraint evaluation.
- **Canonical Outputs:** `RiskAdjustedWeightVector`, `RiskApplicationReceipt`, diagnostics and violations.
- **Artifact/Provenance:** Input/output hashes, rule/model versions, effective time, binding chain and reason codes.
- **Truth/PIT Boundary:** Risk inputs and portfolio state must be available at the effective decision time.
- **Runtime Surface:** Risk handler, task/worker, artifact publication and read-only Agent evidence adapter.
- **Product Surface:** Risk constraints, before/after weights, violations, evidence and unavailable state.
- **Forbidden Shortcuts:** Caller-adjusted weights with a valid target ref; UI/model override minting canonical risk output; implicit pass-through.
- **Current Implementation Notes (conservative):** Current main contains Risk runtime and merged R Portfolio/Risk Agent owner work. Production Agent execution remains `NOT_AVAILABLE / NOT_RUN`; full product/runtime maturity is `PENDING`.

### 4.11 Backtest

- **Owner:** Backtest semantic owner.
- **Responsibility:** Simulate versioned portfolio decisions against verified historical market state and explicit A-share execution/valuation semantics.
- **Canonical Inputs:** Resolved scheduled risk-adjusted weights, `DailyMarketState`, calendar, corporate actions, costs, execution/valuation profiles and starting state.
- **Canonical Payload Owner:** Data Truth owns actual market/calendar/action values; Portfolio/Risk own weights; Backtest owns simulation state and results.
- **Required Resolver:** Backtest market-state resolver that retrieves or verifies actual daily market data, calendar and corporate-action payloads against canonical refs.
- **Deterministic Engine:** Canonical A-share backtest engine.
- **Canonical Outputs:** Run spec/result, orders/fills/ledger/valuation artifacts, diagnostics and rejection receipts.
- **Artifact/Provenance:** Exact market/weight/profile hashes, engine version, schedule/effective times, result/ledger hashes and resolution receipts.
- **Truth/PIT Boundary:** No future prices/actions; explicit suspension, ST, board/limit, lot, cash, costs, execution and valuation timing.
- **Runtime Surface:** Backtest handler/worker with verified Data Truth and Artifact Store access.
- **Product Surface:** Backtest Lab configuration, progress, ledger, failure evidence and honest availability.
- **Forbidden Shortcuts:** Caller-created `DailyMarketState` accepted by reference alone; omitted corporate actions/costs presented as formal; Demo market state as production.
- **Current Implementation Notes (conservative):** Current main contains Backtest runtime engine/model and A-share semantics tests/docs. Systemic market-payload resolver and production connection re-audit is `PENDING`.

### 4.12 Result Analytics

- **Owner:** Result Analytics semantic owner.
- **Responsibility:** Derive metrics, risk, attribution and comparisons from the exact verified Backtest/result payload.
- **Canonical Inputs:** Resolved Backtest result/ledger, benchmark payload, metric definitions and comparison context.
- **Canonical Payload Owner:** Backtest/Artifact Store own actual ledger/result bytes; Data Truth owns benchmark data; Analytics owns derived metrics.
- **Required Resolver:** Result/ledger/benchmark resolver with exact payload and context verification.
- **Deterministic Engine:** Versioned metric, attribution and comparison engine.
- **Canonical Outputs:** Metric/series/attribution artifacts, comparison decision and evidence.
- **Artifact/Provenance:** Source result/benchmark hashes, metric definition/version, context hash and output hashes.
- **Truth/PIT Boundary:** Metrics inherit upstream truth; mismatched contexts are `INCOMPARABLE_CONTEXT`.
- **Runtime Surface:** Analytics handler and artifact publisher.
- **Product Surface:** Result Lab, ledger/performance/risk/attribution/comparison and evidence.
- **Forbidden Shortcuts:** Caller summary metrics; missing benchmark as zero; comparison across materially different contexts.
- **Current Implementation Notes (conservative):** Current main contains Result Analytics engine/model and historical accepted tests. Complete product/production connection is not established and remains `PENDING`.

### 4.13 Artifact Store

- **Owner:** Artifact identity, storage and publication owner.
- **Responsibility:** Store immutable content-addressed bytes, verify reachability/integrity, and publish exact artifact/provenance references.
- **Canonical Inputs:** Bytes, media/schema metadata, producing owner/result, expected hash and provenance manifest.
- **Canonical Payload Owner:** Verified Artifact Store owns stored bytes; producing semantic owner owns their meaning.
- **Required Resolver:** Artifact resolver that streams exact bytes and verifies digest, size, schema, ownership and reachability.
- **Deterministic Engine:** Canonical hashing, identity, publication, reachability and integrity verification.
- **Canonical Outputs:** Artifact ref, immutable payload, publication and resolution receipts.
- **Artifact/Provenance:** Artifact hash is intrinsic; provenance binds producer, inputs, runtime/code and admission.
- **Truth/PIT Boundary:** Artifact integrity does not upgrade semantic truth; provenance and upstream admission remain required.
- **Runtime Surface:** Filesystem/SQLite/object-store adapter behind canonical port and product-safe streaming bridge.
- **Product Surface:** Evidence Explorer, artifact metadata/preview/download and integrity status.
- **Forbidden Shortcuts:** Trusting path/name/ID without bytes; mutable overwrite under the same hash; artifact existence treated as semantic acceptance.
- **Current Implementation Notes (conservative):** Current main contains artifact domain, repositories, filesystem and SQLite publication seams plus runtime evidence projection. Production storage profile and all product flows require exact evidence.

### 4.14 Reviewer

- **Owner:** Reviewer policy and evidence-decision owner; never the underlying financial truth owner.
- **Responsibility:** Evaluate exact scope, evidence, payload/computation integrity, truth ceiling and policy findings.
- **Canonical Inputs:** Resolved artifacts/payloads, provenance, owner receipts, task/change scope and review policy version.
- **Canonical Payload Owner:** Underlying canonical owners/Artifact Store own reviewed bytes; Reviewer owns findings and review decision only.
- **Required Resolver:** Evidence resolver that retrieves actual bytes/data and validates bindings before review.
- **Deterministic Engine:** Deterministic checks plus bounded human/AI-assisted analysis whose claims remain evidence-linked.
- **Canonical Outputs:** Findings, evidence map, acceptance/rejection for the named gate and unresolved states.
- **Artifact/Provenance:** Exact reviewed SHA/path/payload hashes, policy/tool versions, findings and decision receipt.
- **Truth/PIT Boundary:** Reviewer cannot infer missing payload, upgrade upstream truth, or accept an ID-only graph.
- **Runtime Surface:** Review handler integrated with Artifact/Provenance and task scope.
- **Product Surface:** Findings/evidence UI, diff and exact status; no confidence-as-truth display.
- **Forbidden Shortcuts:** Reviewing caller summaries instead of payload; generic PASS; AI confidence minting acceptance.
- **Current Implementation Notes (conservative):** Current main contains Reviewer Integration engine/model and round3 adapter with historical acceptance. System-wide actual-payload coverage remains `PENDING` re-audit.

### 4.15 Control Plane / Task / Worker

- **Owner:** Control Plane semantic owner.
- **Responsibility:** Own task state, leases, retries, checkpoints, cancellation, event logs, worker supervision and durable recovery.
- **Canonical Inputs:** Authorized task spec, capability profile, resource policy, immutable input refs and current durable state.
- **Canonical Payload Owner:** Canonical repositories own task/event/checkpoint payloads; referenced domain owners own business inputs.
- **Required Resolver:** Task/input resolver that validates refs, authority and capability profile before dispatch.
- **Deterministic Engine:** Task state machine, lease/retry/checkpoint/event-replay policies.
- **Canonical Outputs:** Task/events/checkpoints/terminal state and worker receipts.
- **Artifact/Provenance:** Task spec hash, input refs/hashes, worker/runtime identity, state transitions and output refs.
- **Truth/PIT Boundary:** Task success cannot upgrade domain truth; incomplete/failed/cancelled states remain literal.
- **Runtime Surface:** Supervisor, persistence, framed transport and worker boundary.
- **Product Surface:** Task timeline, progress, cancellation/retry/resume and exact failure state.
- **Forbidden Shortcuts:** UI-local task truth; worker success without persisted receipt; silent retry changing inputs.
- **Current Implementation Notes (conservative):** Current main contains task/control-plane state machines, persistence, supervision, event replay and runtime transport with historical foundation evidence.

### 4.16 Resource Governance

- **Owner:** Resource Governance policy owner.
- **Responsibility:** Admit and enforce CPU, memory, GPU, process, time, filesystem, network and concurrency capabilities per task/worker profile.
- **Canonical Inputs:** Task identity, worker/runtime profile, declared requirements, quotas and policy version.
- **Canonical Payload Owner:** Control Plane owns task identity/state; Resource Governance owns grants, denials and usage receipts.
- **Required Resolver:** Policy/identity resolver that verifies task, worker and requested capability bindings.
- **Deterministic Engine:** Admission, quota, lease and enforcement policy.
- **Canonical Outputs:** Capability grant/denial, lease, usage/termination receipt.
- **Artifact/Provenance:** Policy/version, task/worker hashes, requested/granted capabilities, usage and reason codes.
- **Truth/PIT Boundary:** A resource grant authorizes resources only; it does not authorize financial truth or user action.
- **Runtime Surface:** Resource governor integrated with supervisor and isolated workers.
- **Product Surface:** Resource status, queue, denial/degraded reason and operator controls.
- **Forbidden Shortcuts:** Worker self-grant; ambient network/secrets/filesystem; resource success treated as domain acceptance.
- **Current Implementation Notes (conservative):** Current main contains resource-governor and supervisor components with foundation tests. Production enforcement scope must be evidenced per worker profile.

### 4.17 Agent Plane

- **Owner:** Shared Agent policy and user-action authority; Agents do not own domain truth.
- **Responsibility:** Provide evidence-bound L0 READ and non-canonical L1 DRAFT orchestration; gate L2 EXECUTE/L3 PUBLISH through shared canonical authority.
- **Canonical Inputs:** Resolved read evidence, allowed tool registry, session/task scope, policy and explicit user-action authority when available.
- **Canonical Payload Owner:** Domain owners/Artifact Store own actual evidence; shared authority owns execution/publish authorization; Agent owns only proposal/draft artifacts.
- **Required Resolver:** Pre-model evidence and relationship resolver; pre-action authority resolver.
- **Deterministic Engine:** Domain engines remain separate; Agent orchestration and structured proposal generation are not financial engines.
- **Canonical Outputs:** Read explanation, draft/proposal, tool trace, denial or authorized action request; never truth by prose.
- **Artifact/Provenance:** Exact evidence hashes, prompt/model/tool/policy versions, scope, draft hash and authorization receipt if applicable.
- **Truth/PIT Boundary:** Cross-binding validation occurs before model/action; model output cannot upgrade truth or authority.
- **Runtime Surface:** Bounded Agent workers/tools behind Control Plane and canonical resolvers.
- **Product Surface:** Agent Workspace, evidence, drafts, confirmations/denials and trace.
- **Forbidden Shortcuts:** Agent-local approval; caller token granting execution; hidden write tool; evidence lookup after model assertion.
- **Current Implementation Notes (conservative):** Current main contains L0/L1 Agent/evidence modules, Factor and Portfolio/Risk Agent owner work, and an Agent Workspace read-only evidence path. L2 production execution is `NOT_AVAILABLE / NOT_RUN`; Q/S candidates are not main authority.

### 4.18 Alpha Mining

- **Owner:** Alpha Mining orchestration owner constrained by canonical Factor authority.
- **Responsibility:** Search/propose candidate Factor definitions and experiments while reusing canonical IR/evaluator, Dataset/Experiment and evidence owners.
- **Canonical Inputs:** Search space, canonical operator/data profile, resolved Dataset/context, budget/policy and prior evidence.
- **Canonical Payload Owner:** Factor/Dataset/Data Truth owners retain all math/data truth; Alpha Mining owns search proposal/run records only.
- **Required Resolver:** Factor/Dataset/evidence resolver plus allowed search-space and resource-policy verification.
- **Deterministic Engine:** Search/scheduling logic invokes the canonical Factor evaluator; it is not a second Factor engine.
- **Canonical Outputs:** Candidate drafts, evaluated run refs, comparable experiment records and evidence.
- **Artifact/Provenance:** Search policy/seed/budget, canonical IR/input/result hashes, rejected candidates and run lineage.
- **Truth/PIT Boundary:** Candidates remain drafts until canonical Factor admission; comparisons obey exact context/PIT.
- **Runtime Surface:** Isolated Alpha Mining worker coordinated by Control Plane and Resource Governance.
- **Product Surface:** Mining workspace, candidate/evidence inspection, budgets and honest unavailable state.
- **Forbidden Shortcuts:** Second evaluator/TDX VM; bulk third-party formula truth; model-selected candidate auto-published; caller score arrays.
- **Current Implementation Notes (conservative):** Current main contains shared Agent request vocabulary and Factor foundations. S Alpha Mining PR #30 is OPEN and unmerged; its candidate source is not current-main authority and production availability is not claimed.

### 4.19 Desktop / Product Runtime

- **Owner:** Desktop runtime and Product UX integration owner; never the financial semantic owner.
- **Responsibility:** Bind accepted handlers through a closed Electron main/preload/renderer bridge, preserve session scope, and present truthful capability/degraded states.
- **Canonical Inputs:** Runtime capability/health, task/evidence/artifact views, product/session state and exact typed contracts.
- **Canonical Payload Owner:** Backend/domain owners and Artifact Store own actual payloads; desktop owns presentation/session state only.
- **Required Resolver:** Production runtime handler plus closed bridge that resolves typed read models and rejects stale/cross-session data.
- **Deterministic Engine:** No financial engine in renderer; presentation derivation is bounded and must not mint canonical results.
- **Canonical Outputs:** Product read models, commands/intents, session-scoped UI state and user-visible availability.
- **Artifact/Provenance:** Backend/source object refs, session/view identity, bridge/runtime version and displayed evidence bindings.
- **Truth/PIT Boundary:** UI state cannot upgrade backend truth; stale, disconnected, no-evidence and fixture states remain distinct.
- **Runtime Surface:** Electron main, production handler, preload bridge, renderer registry and supervised backend runtime.
- **Product Surface:** Agent-first shell and five professional Labs, Chinese-first and low-chrome/no-box.
- **Forbidden Shortcuts:** Renderer finance math; second IPC; fake connected state; hidden fixture/demo fallback; cross-session artifact leakage.
- **Current Implementation Notes (conservative):** Current main contains a supervised `backendRuntime` bridge and read-only canonical evidence flow, plus an explicitly named development fixture path. This is not proof that all domain handlers are product-connected or production-available. T PR #29 remains OPEN and unmerged; full `USER_VISUAL_ACCEPTED` is not established.

## 5. Architecture acceptance questions

For any new path, the design and review must identify the semantic owner, actual payload owner, resolver, deterministic engine, output owner, provenance receipt, PIT boundary, runtime handler, desktop bridge, product surface, and forbidden shortcuts. A missing field is a design blocker, not permission to infer the layer.
