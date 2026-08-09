# Canonical Backend Foundation

This directory contains the accepted Backend Foundation: typed contracts, the 56-table Control Catalog and repositories, artifact storage/publication boundaries, task and worker control planes, resource governance, and supervised local transport.

It does **not** implement formal market Data Truth, Research, Model, Portfolio/Risk, Backtest, or Result domain capabilities. DuckDB and Parquet ports remain explicitly unavailable until later admission. The Foundation currently uses only the Python standard library and is governed by the Core runtime authority in `docs/runtime/`.

The transport modules are not wired into the current desktop main/preload entrypoints in this baseline.
