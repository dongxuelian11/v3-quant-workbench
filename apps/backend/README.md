# Canonical Backend Foundation

This directory contains the accepted Backend Foundation: typed contracts, the 67-table Control Catalog and repositories, artifact storage/publication boundaries, task and worker control planes, resource governance, supervised local transport, and WS-F Data Truth.

WS-F adds provider-independent Data Truth objects and fail-closed financial invariants, but no external provider is admitted and no real market dataset is bundled. Research, Model, Portfolio/Risk, Backtest, and Result capabilities remain unavailable. DuckDB and Parquet ports remain explicitly unavailable until later admission. The Core currently uses only the Python standard library and is governed by the runtime authority in `docs/runtime/`.

The transport modules are not wired into the current desktop main/preload entrypoints in this baseline.
