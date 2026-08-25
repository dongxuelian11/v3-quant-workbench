# V3 V1.1 Usable Research Product candidate

Status: `LOCAL CANDIDATE / UNPUSHED / C4 IN_PROGRESS / PRE_ALPHA / RESEARCH_ONLY / NOT_FORMAL`

Package version: `1.0.0` (`1.1.0` bump gated)

This document records the current V1.1 candidate without promoting local evidence into hosted, clean-machine, provider, review, or release evidence. The exact execution truth and complete history remain in [`V1_1_USABLE_RESEARCH_PRODUCT_STATE_LEDGER.md`](V1_1_USABLE_RESEARCH_PRODUCT_STATE_LEDGER.md).

## Candidate identity

| Field | Current value |
|---|---|
| admitted base/main | `02c5b8748170569ffc436f3bf5d2f682c21d2811` |
| local branch | `codex/v1-1-usable-research-product-01` |
| local committed HEAD/tree | `ffb441590e1efb442ec8c1c20f68e74004ae177c` / `b07ab828634bd71f8232d0265f12b9cf35eb4eb8` |
| candidate state | DIRTY local C4 worktree; the changes described here are not represented by the committed HEAD alone |
| remote task branch / PR | `NOT_CREATED` / `NOT_CREATED` |
| hosted exact-head Jobs A-F | `NOT_RUN` |
| independent review | `PENDING` |

## Connected product scope

The packaged Product entry supports the following research-only journey through real bridge/handler calls and canonical owner readback:

```text
Project create/open/switch
→ local CSV/Parquet import
→ ProjectContext + Snapshot + Universe
→ canonical Factor evaluation/materialization/analysis
→ research Strategy and decision chain
→ research Backtest Task/Run
→ VALID Result + Analytics + Lineage Artifacts
→ full process exit and cold rediscovery
```

All stages retain `PRODUCT_CONNECTED / PRE_ALPHA / RESEARCH_ONLY / NOT_FORMAL`. The legacy Formal `BacktestService` remains `UNAVAILABLE / FORMAL_EXECUTION_CONTRACT_NOT_CLOSED`. A VALID Result means the research publication completed and passed its bounded policy; it is not Formal market truth.

## Current package evidence

The exact current unpacked Windows x64 package was built from the local candidate with embedded CPython 3.14.5 and AKShare 1.18.84:

| Evidence | Result |
|---|---|
| package identity | 1,049,994,307 bytes; 13,904 files; SHA-256 `973e8b78c31320f8d26893104922df6c0da11e74bd8e20d8fc5325233db01932` |
| package source identity | committed source SHA `ffb441590e1efb442ec8c1c20f68e74004ae177c`; BuildManifest `bmanifest_sha256_aca1317479cd41b019d12e8d45ca659f971d53955ea75fdb781edac23d6930eb` marked DIRTY |
| Journey A | `PASS_CANDIDATE / PACKAGED_SAME_MACHINE`: 600519-shaped local CSV, full Data→Factor→Strategy→VALID Result path, exact identity preservation after a new process |
| Journey B | `PASS_CANDIDATE / PACKAGED_SAME_MACHINE`: 20-symbol local cross-section, independent IC/Rank IC/quantile/spread equality before and after restart |
| package mutation / shutdown | package hash unchanged, graceful backend shutdown, zero orphan package processes |
| `verify:release` | expected `FAIL`: release BuildManifest is not CLEAN |

The retained local evidence is under ignored D-drive `artifacts/v3-v1-1-release-current-final` and `artifacts/package`. It is not committed release evidence and cannot substitute for Job E.

## Admitted date and board matrix

This matrix describes only the local acceptance inputs. It does not claim that the rows came from an exchange/provider or that historical board/status semantics were verified.

| Case | Input identity | Date coverage | Board/status meaning | Admission |
|---|---|---|---|---|
| Journey A | user-supplied `600519`-shaped daily CSV; 3,195 rows | 2018-01-01 through 2026-09-30 | SSE main-board-shaped identifier only; listing/ST/suspension/price-limit/corporate-action history is not admitted | `LOCAL_USER_SUPPLIED / PIT_UNPROVABLE / PRE_ALPHA / NOT_FORMAL` |
| Journey B | 20 user-supplied `600000`-`600019`-shaped symbols; 600 rows | 2026-01-01 through 2026-01-30 | deterministic cross-sectional acceptance input; not live SSE observations and not historical membership evidence | `LOCAL_USER_SUPPLIED / PIT_UNPROVABLE / PRE_ALPHA / NOT_FORMAL` |
| Live AKShare | `stock_zh_a_hist` exact-package provider path | `NOT_RUN` | no provider bytes admitted | `NOT_RUN` |

## CI and clean-machine design

- Jobs A-C validate the exact candidate head across authority/contracts/quality, backend runtime, and Windows Product/Electron integration.
- Job D builds the exact Windows package/installer and transfer hashes.
- Job E has no checkout and consumes only Job D artifacts/drivers on a distinct runner.
- Job F executes the exact package against the real AKShare provider with deterministic/fallback provider modes removed from the child environment. Only exact `PROVIDER_ACQUISITION_UNAVAILABLE` becomes `BLOCKED_PROVIDER_ACCEPTANCE`; a hang or any other nonzero exit is FAIL.
- Every repository Action invocation is pinned to an audited immutable commit SHA.

The workflow source, YAML, embedded PowerShell, and local validation gates pass. The hosted jobs themselves remain `NOT_RUN` until an exact remote head exists.

## Non-promoted gates and known limits

- clean exact-head BuildManifest/release manifest: `NOT_RUN`;
- NSIS install/uninstall on Job E: `NOT_RUN`;
- distinct no-checkout clean-machine Journey A/B: `NOT_RUN`;
- real live-provider acquisition: `NOT_RUN`;
- physical Windows scaling: `NOT_RUN`;
- keyboard-complete Golden Journey through the native file chooser: `NOT_RUN`;
- user visual acceptance: `PENDING`;
- remote PR checks and non-author independent approval: `NOT_RUN` / `PENDING`;
- complete PIT, available-time, revision, suspension, ST, listing/delisting, board-specific price-limit, and corporate-action truth: `NOT_AVAILABLE` for Formal admission;
- Agent L2 EXECUTE / L3 PUBLISH: `NOT_AVAILABLE / NOT_RUN`;
- live trading and paper trading: not included.

## Version gate

The repository, Product status, installer name, verification scripts, and generated package remain `1.0.0`. The plan allows a coordinated `1.1.0` change only after every applicable C4 acceptance has real evidence. Local documentation reconciliation or source tests alone do not satisfy that gate.
