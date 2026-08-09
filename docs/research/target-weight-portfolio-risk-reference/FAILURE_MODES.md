# Failure modes

## Failure policy

Every formal stage returns either an immutable success artifact or a typed failure/blocked result. Warnings may supplement but never replace machine-readable truth. No stage silently invents prices, remaps identifiers, reuses previous weights, changes the universe, renormalizes a vector or falls back from FORMAL to DEMO.

## Contract and identity failures

| Failure | Detection | Required outcome | Disposition |
|---|---|---|---|
| Duplicate `instrument_id` rows | canonicalization | reject; report duplicates | **ADOPT** |
| NaN, Infinity, negative zero or noncanonical decimal | schema/canonicalizer | reject before hashing | **ADOPT** |
| Hash mismatch or order-dependent hash | artifact admission | quarantine/reject | **ADOPT** |
| Unsupported `schema_version`/profile | compatibility gate | typed incompatibility | **ADOPT** |
| Missing exact universe/constraints/source ref | admission | reject incomplete provenance | **ADOPT** |
| Same ID with different content | registry | integrity incident; never overwrite | **ADOPT** |
| Bare map/DataFrame crosses public boundary | boundary validation | reject or require explicit import conversion | **ADAPT** |

## Weight and cash failures

| Failure | Example | Required outcome | Disposition |
|---|---|---|---|
| Sum mismatch | long-only rows + cash = 0.97 | fail, unless an explicitly versioned normalizer is the current construction step | **ADOPT** |
| Hidden residual | omitted cash treated differently by consumers | reject missing cash | **ADOPT** |
| Unauthorized short | weight = -0.1 under long-only profile | reject | **ADOPT** |
| Gross/net breach | market-neutral target gross exceeds limit | construction/risk infeasible with evidence | **ADOPT** |
| Weight outside per-name bounds | 25% where max is 10% | reject or explicit risk projection | **ADOPT** |
| Ambiguous omission | missing row might mean zero or unchanged | reject sparse semantics | **ADOPT** |
| Tiny numerical residual | solver returns 1 + 2e-9 | validate against pinned tolerance; record repair if policy permits | **ADAPT** |
| Automatic proportional renormalization | violating vector silently sums to 1 | prohibit | **REJECT** |

## Temporal and provenance failures

| Failure | Required outcome | Disposition |
|---|---|---|
| `as_of` after source data cutoff or future leakage | reject with PIT violation | **ADOPT** |
| Rebalance time outside pinned calendar | reject or explicit calendar adjustment policy | **ADOPT** |
| Target expired before planning | `STALE_TARGET`, no orders | **ADOPT** |
| Signal/universe/snapshot dates incompatible | fail construction/admission | **ADOPT** |
| Mutable “latest” model/universe/risk policy reference | reject formal publication | **ADOPT** |
| Missing solver/code/environment version | reject formal optimized vector | **ADOPT** |
| Mutable human annotation changes content ID | exclude nonsemantic annotation from hash but audit its revision separately | **ADAPT** |

## Portfolio and optimizer failures

| Failure | Reference lesson | Required outcome | Disposition |
|---|---|---|---|
| Infeasible constraint set | skfolio exposes rich budgets/bounds; solvers can fail | typed infeasibility and diagnostics | **ADOPT** |
| Inaccurate/time-limited solver status | approximate result may violate constraints | do not publish formal target unless an explicit acceptance policy passes independent validation | **ADOPT** |
| Optimizer returns no/NaN weights | skfolio can set `weights_=None` under a warning mode | reject candidate; warning-only is insufficient | **ADOPT** |
| Fallback to equal/previous weights | can hide algorithm failure | only an explicit separate candidate and policy can use it | **ADAPT** |
| Current holdings required but not pinned | turnover/cost objective becomes irreproducible | fail input validation | **ADOPT** |
| Classification/identifier mapping incomplete | sector/asset constraints become wrong | reject or explicit out-of-scope set; no fuzzy mapping | **ADOPT** |

## Risk composition failures

| Failure | Required outcome | Disposition |
|---|---|---|
| Policy order changes result | order is semantic and versioned; new order creates new policy-set/result identity | **ADOPT** |
| Two policies conflict | return infeasible with conflict evidence; no last-writer-wins mutation | **ADOPT** |
| Clip creates cash/exposure breach | run declared residual rule or reject | **ADOPT** |
| Risk model stale/missing/non-PSD | apply only an explicitly pinned repair/degraded policy; otherwise fail | **ADOPT** |
| Risk output changes source target or StrategyVersion | integrity violation | **REJECT** |
| Risk returns original target after internal exception | typed failure, never “unchanged” | **REJECT** |
| Emergency all-cash fallback | separately versioned `REPLACE` policy with high-visibility evidence | **ADAPT** |

## Execution failures

| Failure | Reference lesson | Required outcome | Disposition |
|---|---|---|---|
| Missing/zero/stale price | LEAN percentage conversion can fail; FinRL-X has a default-price path | reject/blocked instrument; never invent price | **ADOPT** |
| Insufficient buying power/cash | conversion is account-dependent | resize only under explicit execution policy or block plan | **ADAPT** |
| Lot/tick rounding consumes excess cash | quantity conversion detail | deterministic rounding plus residual cash/report | **ADOPT** |
| Suspended/ST/restricted/limit instrument | WonderTrader tests trading restrictions | blocked residual with rule snapshot | **ADOPT** |
| T+1/frozen holdings prevent sale | current position is not fully sellable | partial plan and residual | **ADOPT** |
| Short locate unavailable | desired short not executable | block/reject without rewriting target | **ADOPT** |
| Duplicate target delivery | retry/race | idempotency prevents duplicate order effect | **ADOPT** |
| Target superseded during partial execution | real state has already changed | cancellation/replacement chain preserves both plans and fills | **ADOPT** |
| Partial fills or cancellation | target not realized | ledger plus residual/reconciliation artifacts | **ADOPT** |
| Engine silently drops instrument | loss of intent/provenance | prohibit | **REJECT** |

## Cross-stage ownership failures

| Anti-pattern | Why it fails | Disposition |
|---|---|---|
| Strategy queries DB or account to choose current holdings | hidden state breaks reproducibility and conflates evaluation with portfolio/execution | **REJECT** |
| Strategy calls Backtest/Execution | cyclic ownership and nonportable strategy identity | **REJECT** |
| Risk mutates Strategy or SignalArtifact | destroys causal comparison | **REJECT** |
| Backtest recomputes portfolio intent from source code | can diverge from reviewed/published artifacts | **REJECT** |
| Execution chooses optimizer objectives | policy leak across domains | **REJECT** |
| One mutable “portfolio” object represents intent, target, orders, fills and holdings | time and ownership become ambiguous | **REJECT** |

## Operational failures

Artifact-store outage, registry conflict, cancelled task, worker crash and retry are not mathematical fallbacks. A retry creates a new attempt and preserves prior attempts. Changed semantic inputs create a new run/vector identity. Partial publication never exposes a FORMAL vector before rows, diagnostics, provenance and registry commit are atomically admitted.

**FUTURE:** disaster-recovery and cross-region artifact replication rules belong to platform design, not this contract study.
