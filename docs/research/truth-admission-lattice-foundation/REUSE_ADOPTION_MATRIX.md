# Truth / Admission Lattice Reuse Adoption Matrix

Task: `V3-TRACK-A0-TRUTH-ADMISSION-LATTICE-FOUNDATION-01`
Evidence snapshot: 2026-08-11
Baseline: `57591d02716b88aeff10cf372e8dc4ad1a89385f`

## Decision

Adopt Python 3.14 standard-library primitives directly and implement the V3 semantic contract natively.

Selected primitives:

- `Enum` for explicit typed vocabulary, without relying on member values for ordering;
- `@dataclass(frozen=True)` for immutable value contracts;
- `frozenset` and `MappingProxyType` for immutable explicit order and meet tables;
- sorted immutable tuples for deterministic upstream aggregation.

V3 remains the sole owner of truth/admission vocabulary, valid state combinations, partial-order semantics, meet, downstream ceilings, fail-closed behavior, and canonical-claim rules. No upstream implementation code or tests were copied.

## Adoption matrix

| Candidate | Coverage | License | Maintenance / tests | Windows / Python 3.14 | Determinism / isolation / provenance | Silent fallback / second Authority risk | Disposition |
|---|---|---|---|---|---|---|---|
| Python 3.14 standard library (`enum`, `dataclasses`, immutable built-ins) | Supplies typed enums, frozen records, immutable sets/maps; V3 still owns the lattice tables and rules | PSF-2.0; documentation examples additionally 0BSD | Maintained with CPython and covered by the CPython test suite | Native project runtime; repo pins Python 3.14.7 | In-process, dependency-free, explicit tables; provenance is the Python 3.14 library contract | No fallback or external semantic authority when V3 validates exact types | **ADOPT — direct primitive reuse** |
| Pydantic 2.13.4 | Strong typed validation and immutable-model options; does not supply V3 lattice semantics | MIT | Active; latest release 2026-05-06; pytest, type-check and benchmark suites | Declares Python 3.14 and OS-independent support; requires `pydantic-core` plus helper packages | Deterministic validation is possible, but adds runtime/package provenance and a second validation layer | Validators/config could become a parallel contract authority; no reduction in V3-owned semantic work | **REJECT direct dependency/adapter/worker/selective reuse; design reference only** |
| NetworkX 3.6.1 | General graph algorithms can represent a partial order, but are far broader than the fixed A0 product lattice | BSD-3-Clause | Active; extensive pytest suite and current development | Supports Windows and Python 3.14, excluding Python 3.14.1 | Pure-Python base and deterministic use are possible, but graph/backend abstraction is unnecessary here | Disproportionate API surface and backend semantics could obscure the canonical explicit order | **REJECT_NOT_V3_FIT** |
| transitions 0.9.3 | Mature finite-state-machine transitions and callbacks; does not model meet or partial-order ceilings | MIT | Maintained; pytest CI covers Python 3.10–3.13 | Windows is plausible, but upstream metadata/CI does not claim or test Python 3.14 | In-process, but transition callbacks are a different semantic model | Would create a workflow/state-transition authority and offers no lattice advantage | **REJECT_NOT_V3_FIT** |

## Adoption Gate by integration level

| Level | Decision | Reason |
|---|---|---|
| Direct dependency | Reject | No external package can own V3 vocabulary/rules, and the required fixed lattice is smaller than the dependency surface. |
| Thin adapter | Reject | There is no external service contract to adapt; an adapter would only wrap semantics V3 must define itself. |
| Isolated worker / API / CLI | Reject | The operation is pure, deterministic, local, and latency-sensitive; process isolation adds failure modes without authority isolation benefit. |
| Selective module reuse | Reject | Copying a third-party graph/FSM/validation module is unnecessary and expands license/provenance obligations. |
| Design / algorithm reference | Adopt narrowly | Use standard product-order and greatest-lower-bound concepts, expressed as V3-owned explicit tables and tests. |
| V3 native implementation | Adopt | Required for canonical vocabulary, valid combinations, ceilings, claim boundaries, and fail-closed behavior. |

## Primary evidence

- Python 3.14 data types and `enum`: https://docs.python.org/3.14/library/datatypes.html
- Python 3.14 `dataclasses`: https://docs.python.org/3.14/library/dataclasses.html
- Pydantic repository and release: https://github.com/pydantic/pydantic and https://github.com/pydantic/pydantic/releases/tag/v2.13.4
- Pydantic project metadata: https://github.com/pydantic/pydantic/blob/main/pyproject.toml
- NetworkX repository and release: https://github.com/networkx/networkx and https://github.com/networkx/networkx/releases/tag/networkx-3.6.1
- NetworkX project metadata: https://github.com/networkx/networkx/blob/main/pyproject.toml
- transitions repository, metadata, and CI: https://github.com/pytransitions/transitions, https://github.com/pytransitions/transitions/blob/master/setup.py, and https://github.com/pytransitions/transitions/blob/master/.github/workflows/pytest.yml

## Canonical boundary retained

Publication and validation evidence remain separate from admission. `PUBLISHED + STRICT_PIT` cannot construct `FORMAL_ADMITTED`; `UNKNOWN` meets fail closed; a `PRE_ALPHA` required upstream caps downstream output; a proposal remains a proposal even when its proof state is strong. The implementation exposes no automatic promotion or nearest-state coercion.

## Internal truth vocabulary compatibility

The existing `CapabilityTruthState` and `OperationalTruthState` contracts describe whether an operation or capability is available in its declared product mode. They are not canonical market-truth evidence and are not aliases of `TruthAdmissionState`. In particular, the shared spelling `FORMAL` does not establish strict-PIT proof, canonical admission, formal market truth, or admitted canonical truth.

The bounded compatibility design combines wire separation with an explicit typed adapter:

- canonical state wires use `canonical_truth_state` and `canonical_admission_state`; existing capability DTOs retain `truth_state` and therefore cannot be silently parsed as canonical state;
- the adapter accepts only the exact existing enum type, never strings or a different same-named enum;
- capability or operational `FORMAL` yields at most `NOT_FORMAL / UNKNOWN`, explicitly recording that capability formality is not canonical truth;
- `DEMO`, `UNAVAILABLE`, and operational `DEGRADED` yield `UNKNOWN / UNKNOWN` and therefore fail closed;
- every compatibility result is met with an explicitly supplied canonical upstream ceiling, so it cannot exceed canonical upstream evidence.

This is an ingress compatibility boundary, not a second authority: the legacy vocabularies remain unchanged, the canonical lattice remains the only owner of canonical truth/admission semantics, and the adapter can only preserve or lower the canonical ceiling. No DataSnapshot, Dataset, provider, or downstream runtime migration is included.
