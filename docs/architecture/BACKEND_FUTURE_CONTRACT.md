# Future backend contract

This document records the frozen architecture boundary for later work. It is not an implementation claim.

The future canonical backend is a modular monolith plus isolated workers behind one Application Service Layer. Electron Main will supervise a local Python backend. The design reserves a SQLite Control Catalog, content-addressed Parquet and Artifact Store, DuckDB query execution, and a durable Task / Run / Attempt / Event model.

WS-F implements the provider-independent point-in-time, historical Universe, calendar, adjustment/corporate-action boundary, and survivorship guards. External provider admission, execution costs, short/suspension execution rules, and the Backtest Core remain later work. No second Registry or database authority is introduced.

The frontend remains unwired and can only observe the typed `unavailable` state until a separately authorized integration task is completed and reviewed.
