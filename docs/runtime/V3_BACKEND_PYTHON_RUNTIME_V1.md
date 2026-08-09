# V3 Backend Python Runtime V1

Decision date: 2026-08-09

## Decision

The Canonical Core runtime authority is **CPython 3.14.7 (64-bit, GIL build)**.

The repository pins the exact development/CI patch in `.python-version`. Backend code should declare compatibility with the 3.14 minor line only until a later runtime-authority review changes that decision.

## Why 3.14.7

Python.org records 3.14.7 and 3.13.15 as maintenance releases published on 2026-08-05, both with official Windows 64-bit installers. Python 3.14 remains in regular bugfix support through October 2027 and security support through October 2030; Python 3.13 reaches its final regular bugfix release in October 2026 and security support ends in October 2029.

Current PyPI metadata checked on 2026-08-09 shows a complete Windows x86-64 wheel intersection for the intended near-term Core/Data stack on both CPython 3.13 and 3.14:

| Package | Observed version | Python requirement | CPython 3.14 Windows wheel evidence |
|---|---:|---|---|
| pydantic | 2.13.4 | `>=3.9` | universal wheel; pydantic-core 2.48.0 has `cp314` and `cp314t` wheels |
| numpy | 2.5.1 | `>=3.12` | `cp314` and `cp314t` wheels |
| pandas | 3.0.5 | `>=3.11` | `cp314` and `cp314t` wheels |
| duckdb | 1.5.5 | `>=3.10.0` | `cp314` wheel |
| pyarrow | 25.0.0 | `>=3.10` | `cp314` and `cp314t` wheels |
| polars | 1.43.2 | `>=3.10` | universal Python wheel plus `cp310-abi3` Windows runtime wheel |
| scikit-learn | 1.9.0 | `>=3.11` | `cp314` and `cp314t` wheels; SciPy 1.18.0 also supplies both |

Because both candidates satisfy the dependency intersection, the newer 3.14 line wins on lifecycle and forward support. Python 3.13.15 is rejected as Core authority because it offers no required compatibility advantage and has a shorter remaining support horizon.

## Foundation dependency boundary

The merged Backend Foundation remains standard-library-only. NumPy, pandas, DuckDB, PyArrow/Polars, scikit-learn, Qlib, RQData, RQAlpha, and GPU frameworks are not current committed Python runtime dependencies.

Data and Model workers may later receive isolated, locked Environment Profiles. Optional or externally blocked adapters cannot force a downgrade of the Canonical Core ABI.

## Official sources

- Python 3.14.7 release and Windows installers: https://www.python.org/downloads/release/python-3147/
- Python 3.13.15 release and Windows installers: https://www.python.org/downloads/release/python-31315/
- Python 3.14 release lifecycle: https://peps.python.org/pep-0745/
- Python 3.13 release lifecycle: https://peps.python.org/pep-0719/
- Current package and wheel metadata: `https://pypi.org/pypi/<package>/json`

The local verification host had Python 3.14.5 installed, and the stdlib-only Foundation passed there. CI is pinned to 3.14.7; the local host was not mutated and no Python packages were installed during this decision.
