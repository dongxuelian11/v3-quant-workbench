# Future backend contract (not rebuilt)

This document records the frozen architecture boundary for later work. It is not an implementation claim.

The future canonical backend is a modular monolith plus isolated workers behind one Application Service Layer. Electron Main will supervise a local Python backend. The design reserves a SQLite Control Catalog, content-addressed Parquet and Artifact Store, DuckDB query execution, and a durable Task / Run / Attempt / Event model.

The future backend must fail closed for point-in-time, Universe, time, adjustment, cost, short/suspension, and survivorship truth. It must not create a second Backtest Core, parallel Registry truth, or silent fallback to the old runtime.

FR-0 / FR-1 intentionally implements none of these domains. The frontend can only observe the typed `unavailable` state until a separately authorized backend task is completed and reviewed.

