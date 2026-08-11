# Track G AI Research Evidence Integration V1 — Reuse and Adoption

## Decision

Track G keeps the current `pydantic-ai-slim==2.27.0` runtime and reuses the exact
current-main Track B/C/A0/Track D objects. It adds a V3-native, read-only composition
adapter because current main has no query port spanning `ResearchDataSnapshot`,
`DatasetVersion`, `ExperimentRun` / `ExperimentAttempt`, `RewardVector`, and
`ReviewerEvidence`.

The adapter is not a repository and does not persist, publish, allocate canonical IDs,
or mutate truth. It holds references to existing typed owner objects and returns bounded
metadata views. This avoids a second storage or semantic authority.

## Implementation-critical verification

| Candidate | Coverage | License / maintenance / tests | Windows / Python 3.14 | Determinism, API, dependency weight, isolation | PIT, identity, provenance, missing/error, artifact safety | Silent fallback / second authority | Adoption |
|---|---|---|---|---|---|---|---|
| Current-main PydanticAI Slim `2.27.0` | Typed Pydantic output plus registered Python function tools used by the accepted Track D worker | MIT; production/stable PyPI metadata; release `v2.27.0` dated 2026-08-07; active upstream CI and signed GitHub release | PyPI declares Python `>=3.10`, includes Python 3.14 classifier, and publishes a pure `py3-none-any` wheel; installed and imported under local CPython 3.14.5 | Existing direct dependency; exact pin and runtime version check; no provider SDK or second Agent framework | Pydantic validates typed output and tool schemas, but V3 still owns exact object IDs, truth, provenance, bounded receipts, NaN/error policy, and artifact authority | No upgrade and no provider/network fallback; PydanticAI is an execution adapter, never canonical authority | **KEEP DIRECT DEPENDENCY at exact 2.27.0** |
| Current-main Track B/C typed objects and A0 truth types | Exact Snapshot, Dataset, FactorEvaluation, Experiment, Attempt, RewardVector, ReviewerEvidence, truth/admission and provenance fields | Repository Apache-2.0; already accepted owner code with dedicated tests | Current canonical runtime is CPython 3.14; baseline A0/B/C suites passed locally | Frozen dataclasses, content-derived IDs and deterministic `to_wire()` methods; zero new dependency | Exact IDs and upstream ceilings already exist; explicit missing/PIT/revision states; content-addressed Artifact refs | Direct owner reuse; no fallback and no shadow contract | **DIRECT REUSE** |
| Existing repository ports | Snapshot and Dataset catalog operations exist; no complete read API for Track B runtime Snapshot plus Track C Experiment/Attempt/RewardVector graph | Repository-owned and tested where implemented | Native project runtime | Adding write/query semantics here would broaden shared owner scope | Row mappings can expose storage shape and do not supply all typed Track C relationships | Extending them in Track G risks a second partial authority | **REJECT AS TRACK G QUERY AUTHORITY** |
| V3-native read-only composition adapter | Exact typed lookups, bounded metadata, role-specific tool registration and system receipts | Repository Apache-2.0; Track G tests cover trust and permission boundaries | Standard Python/Pydantic only; tested on CPython 3.14.5 Windows | Deterministic sorted/capped responses and hashes; no persistence, filesystem, subprocess, arbitrary DB, or network | Reuses owner truth and provenance; explicit `MISSING`; no raw bytes or paths; records only response hashes and refs | Exact registered callable required; out-of-scope IDs and unregistered names fail closed | **ADOPT THIN NATIVE ADAPTER** |
| Pydantic Evals or another Agent framework | Could add evaluation/workflow features, but none are required for typed read integration | Upstream packages are maintained, but would add another runtime surface | Compatibility is not needed because capability is out of scope | Adds dependency and API weight without reducing V3-owned evidence semantics | Does not own V3 PIT/truth/identity/provenance | High second-runtime/second-authority risk | **REJECT NOT V3 FIT** |

## Trusted tool boundary

The V3-owned composition factory registers only:

- `get_snapshot_evidence`
- `get_dataset_evidence`
- `get_experiment_evidence`
- `get_reward_vector_evidence`
- `get_provenance_refs`
- `get_known_reviewer_evidence`

Every tool is `L0_READ` / `READ`. The model receives no callable-registration input.
During an Agent run, each tool accepts only the exact object IDs placed in the
system-owned request. Extra IDs, duplicate calls, missing required calls, forged
descriptors, alternate callables, and non-registered tools fail closed.

Tool responses are typed and capped. They contain exact IDs, truth/admission ceilings,
provenance references, split/Attempt/metric summaries, and explicit missing/truncation
states. They contain no arbitrary query, filesystem path, raw artifact bytes, subprocess,
or network operation.

The model output type contains only draft narrative. The final input hash,
`AgentProvenance`, permission decision, evidence IDs, and tool receipts are constructed
by V3 after tool execution. Research/Data/Reviewer outputs remain `NON_CANONICAL` /
`DRAFT`; reviewer findings are not admission decisions.

## Sources

- PydanticAI `v2.27.0` release: https://github.com/pydantic/pydantic-ai/releases/tag/v2.27.0
- PyPI exact metadata: https://pypi.org/pypi/pydantic-ai-slim/2.27.0/json
- PydanticAI function tools: https://pydantic.dev/docs/ai/tools-toolsets/tools/
- PydanticAI structured output: https://pydantic.dev/docs/ai/core-concepts/output/
