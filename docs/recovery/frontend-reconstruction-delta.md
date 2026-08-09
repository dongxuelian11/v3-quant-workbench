# Frontend reconstruction delta

Exact historical frontend source was unavailable, so this document records material reconstruction choices:

1. The shell and Lab surfaces are new TypeScript/CSS implementations derived from the accepted contract, not byte-for-byte restorations.
2. The dock behavior is represented by a persistent left navigation rail and contextual right Inspector with save/reset state. A future review may refine exact docking affordances if stronger evidence is recovered.
3. Research chart geometry and Model/Strategy examples are non-financial illustrative UI fixtures. They are not connected to market data or a formal provider.
4. Backtest and Result expose structure plus an explicit unavailable provider banner. They do not show invented metrics, trades, or risk results.
5. The desktop shell uses a single compiled renderer document rather than the lost historical bundler/runtime, while preserving the required Electron and typed IPC boundary.

