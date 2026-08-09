# Desktop application

Electron main, preload, and React/Vite renderer sources for the recovered continuous V3 workbench. The renderer uses real Dockview, ECharts, React Flow, Monaco, cmdk, and Zustand. A narrow typed IPC bridge persists Lab layouts, StrategyDraft, Model Study state, and exactly-once command receipts to an atomic file in Electron `userData`; the renderer has no direct filesystem access.
