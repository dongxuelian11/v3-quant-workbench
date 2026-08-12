# Round 5 W0 TDX Compatibility Contract

## Execution architecture

TDX support is a source adapter only:

`TDX source → parser → normalized AST → compatibility/data profiles → Canonical Factor IR → FactorDefinitionVersion → DeterministicReferenceEvaluator`

There is no TDX evaluator, generic Formula VM, truthiness conversion, or second factor authority. TA-Lib remains a registered non-authoritative compute backend for canonical `SMA@1.0.0`.

## Grammar and compatibility

The V0 parser supports multi-statement scripts, `:=`, `:`, `;`, arithmetic, comparisons, `AND/OR/NOT`, parentheses, canonical numeric literals, unary minus, ASCII/Chinese identifiers, function calls, named outputs, and drawing metadata.

Supported exact mappings:

| TDX | Canonical operator | Output | Warmup/lookback |
|---|---|---|---|
| `MA(X,N)` | `SMA@1.0.0` | `FLOAT_SERIES` | `N-1` |
| `CROSS(A,B)` | `CROSS@1.0.0` | `BOOLEAN_SERIES` | one prior observation |

`CROSS@1.0.0` is true only when previous `A <= B` and current `A > B`. First observation or missing prior/current data is `None`, never `0` or `False` by fallback.

`EMA`, `REF`, `HHV`, `LLV`, `SUM`, `STD`, `COUNT`, `EVERY`, `EXIST`, `IF`, `MAX`, `MIN`, and `ABS` are `UNSUPPORTED_CANONICAL_OPERATOR`. TDX `SMA(X,N,M)` is `SEMANTICS_UNRESOLVED`; it is not inferred from the existing simple moving average. Unsupported calls fail with `UNSUPPORTED_TDX_OPERATOR`.

`DRAWTEXT`, `DRAWLINE`, `STICKLINE`, `COLOR*`, and `LINETHICK*` remain drawing/style metadata or explicit non-computational statements and do not affect factor identity.

## Data-semantics gate

Every profile must provide evidence-backed mappings for `OPEN/HIGH/LOW/CLOSE`, `VOL`, and `AMOUNT/AMO`.

- TDX `VOL` means hands. Canonical shares require exact conversion `shares × 0.01 → hands`; canonical hands require multiplier `1`.
- TDX `AMOUNT/AMO` means CNY and requires canonical CNY evidence with multiplier `1`.
- OHLC require CNY-per-share evidence.

Missing fields/evidence, incompatible units, non-canonical conversion text, or name-only `VOL → volume` mapping fail with `TDX_DATA_SEMANTIC_UNRESOLVED` before any definition/import admission.

For the required source `AMOUNT/VOL/100`, a shares profile yields `amount_cny / (volume_shares × 0.01) / 100 = CNY/share`; the user source is unchanged.

## Hard fixture result

The exact five-statement user fixture produces separate definitions for `MJ`, `MA5`, `MA20`, `MA60`, and `GOLDEN`. `MA5/20/60` are `FLOAT_SERIES`; `GOLDEN` is `BOOLEAN_SERIES`, has maximum lookback 60, and executes through the existing evaluator as `bool/None`. No effectiveness, Dataset admission, Strategy signal, review, or publication claim is made.
