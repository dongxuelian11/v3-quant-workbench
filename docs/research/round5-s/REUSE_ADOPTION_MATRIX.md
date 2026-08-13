# Round 5 S Alpha Mining Reuse Adoption Matrix

Task: `V3-ROUND5-S-ALPHA-MINING-01`

Reviewed: 2026-08-13 (Asia/Shanghai)

Authorized V3 revision: `eda009b601b681c8a26d2a98a1093b3e6f33245e`

## Decision

Round 5 S uses a small V3-native, seeded, closed-world grammar and the already
accepted V3 evaluation/reviewer contracts. It adds no dependency, parser,
evaluator, experiment store, resource manager, or promotion authority.

The core path remains:

```text
MiningFactorCandidate (NON_CANONICAL / DRAFT)
  -> existing Canonical Factor IR validation
  -> existing FactorDefinitionVersion
  -> injected existing FactorEvaluation / Experiment / Reviewer evidence port
  -> S-owned deterministic reward projection
```

`FactorDefinitionVersion` remains the sole factor-math identity and the existing
factor evaluator remains the sole math executor. External symbolic programs are
not executed by S.

## Current evidence sources

Context7 was not callable in this execution environment. CURRENT checks therefore
used the exact local V3 revision plus official GitHub repository metadata and
official PyPI release metadata. No blog or secondary package index was used.

| Candidate | Exact reviewed revision / release | License | Maintenance and compatibility evidence | Round 5 S decision |
|---|---|---|---|---|
| V3 Canonical Factor IR and FactorEvaluation | V3 `eda009b601b681c8a26d2a98a1093b3e6f33245e` | repository license | `OperatorRegistry` is content-addressed; every operator binds PIT, determinism, type, parameters, lookback/lag, missing semantics and backend. `FactorDefinitionVersion` and `FactorEvaluationContext` already bind exact identities. Current repository runtime is Python 3.14.7 on Windows. | `ADOPT_CANONICAL` — use unchanged; never create a second IR/evaluator. |
| W0 `MiningFactorCandidate`, FactorAsset lifecycle and `ResearchLoopBudgetVersion` | V3 `eda009b601b681c8a26d2a98a1093b3e6f33245e` | repository license | Candidate is enforced `NON_CANONICAL/DRAFT`; generic asset creation cannot claim REVIEWED/PROMOTED; research budgets use explicit finite/unlimited modes and production execution binding remains unavailable. | `ADOPT_CANONICAL` — reuse unchanged. S job budgets are always finite and do not upgrade W0 production execution. |
| [AlphaGPT](https://github.com/imbue-bit/AlphaGPT) | `d851f2221dcaf4d53a707344f68ae6801e3e5af5` | Apache-2.0 | Repository was pushed 2026-06-12. Its token generation/VM is useful only as a conceptual decomposition; it does not provide V3 PIT, identity, evidence or authority boundaries. | `CONCEPT_ONLY / NO_CODE` — no fork, copy, VM, evaluator or dependency. |
| [RD-Agent](https://github.com/microsoft/RD-Agent) | `6762f84f9bc0f5c6486c50a00e128a57ac6c3683`; `rdagent==0.8.0` | MIT | Repository was pushed 2026-08-04. PyPI requires Python >=3.10 and classifies 3.10/3.11. Its autonomous research/code-execution loop would duplicate V3 Control Plane and is not the deterministic Windows-local core required here. | `DESIGN_REFERENCE` — proposal/experiment/feedback concept only; no runtime or cache authority. |
| [gplearn](https://github.com/trevorstephens/gplearn) | `0390aea8639ce5f6c0b388400e07b58c05acad6a`; `gplearn==0.4.3` | BSD-3-Clause | PyPI requires Python >=3.11 and explicitly classifies Windows and Python 3.11-3.14. It is maintained and compatible, but would add an external symbolic program/execution surface for a search space small enough to express with the existing V3 IR. | `NOT_ADOPTED_NO_GAP` — a future adapter may translate programs into V3 IR, but S needs no dependency and never executes a gplearn program. |
| [PySR](https://github.com/astroautomata/PySR) | `4f17f44fdff76be46e0a598f1404b8115320ff3f`; `pysr==1.5.10` | Apache-2.0 | Repository was pushed 2026-08-13; PyPI requires Python >=3.9. PySR adds a Julia runtime/toolchain and an external search/checkpoint lifecycle. | `REJECT_FOR_S` — heavy runtime and second execution state are unnecessary for the bounded CI-sized engine. |
| [DEAP](https://github.com/DEAP/deap) | `8a96fd3a75026f7b30e835f595a5199c75634ddf`; `deap==1.4.4` | LGPL-3.0 | Repository/release were updated in 2026. Strongly typed GP and bloat controls are useful ideas, but S requires only a small deterministic grammar and the LGPL dependency adds no authority-safe capability gap. | `DESIGN_REFERENCE` — typed grammar and bloat-control ideas only; no source extraction or dependency. |
| [Qlib](https://github.com/microsoft/qlib) | `79633dd9506ea689e5400dea0197717b5b3d74b7`; `pyqlib==0.9.7` | MIT | PyPI classifies Windows and Python 3.8-3.12, not the repository's Python 3.14.7. Qlib includes its own expression, provider/cache, workflow and evaluation abstractions. | `FUTURE_ISOLATED_REFERENCE` — no direct dependency, evaluator, provider, cache or workflow authority in S. |

## Capability adoption

| Capability | Owner used by S | Decision |
|---|---|---|
| Search-space identity | S content-addressed policy over exact existing `OperatorRegistry` | Native, bounded and versioned. |
| Candidate generation/mutation | S seeded closed grammar | Native; output is only `MiningFactorCandidate` plus a typed IR proposal. |
| Canonical validation and identity | Existing V3 Factor IR / `FactorDefinitionVersion` | Reuse unchanged. |
| Factor math | Existing evaluator behind an injected exact-evidence port | Reuse unchanged; S never computes factor values. |
| Evaluation/experiment identity | Existing `FactorEvaluation`, Dataset, Experiment Run/Attempt | Reuse unchanged and validate exact bindings on return. |
| Reviewer evidence | Existing `ReviewerEvidence` / `ReviewerFinding` | Reuse unchanged. |
| Reward projection | S `AlphaMiningRewardPolicyVersion` | Native deterministic projection over actually present exact evidence; missing components remain explicit. |
| Resource governance | Existing `ResourceGovernor` plus finite S job budgets | Reuse unchanged. |
| Agent role | Draft only | Agent cannot construct the explicit user trigger and cannot start a job. |
| Promotion | Existing FactorAsset lifecycle authority | No promotion call; S output contains no REVIEWED/PROMOTED transition. |

## Rejected authority transfers

- No Python `eval`, dynamic user code, third-party symbolic execution, or opaque
  formula runtime.
- No future/LEAD operator, unresolved data field, implicit full-history
  normalization, or third-party label creation.
- No hidden metric substitution. Missing reward evidence is `NOT_AVAILABLE` or a
  policy-identified explicit zero rule.
- No Agent L2 execution, generic Control Plane authority change, automatic
  FactorAsset promotion, or automatic publication.
