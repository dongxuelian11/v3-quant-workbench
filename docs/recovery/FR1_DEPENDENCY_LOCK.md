# FR-1 frontend dependency lock

All packages below are exact-version bindings in `package-lock.json`. They are used only for the accepted frontend capability restoration.

| Package | Version | Role | License | Reason |
|---|---:|---|---|---|
| electron | 39.8.10 | Desktop runtime and secure main/preload boundary | MIT | Task runtime authority |
| react / react-dom | 19.2.7 | Componentized renderer | MIT | Restore the accepted React product form |
| vite | 6.4.3 | Production renderer build | MIT | Task build authority |
| typescript | 5.9.3 | Typed contracts and UI | Apache-2.0 | Task compiler authority |
| dockview-react | 7.0.4 | Real dockable, serializable Lab workspaces | MIT | Wave 1 interaction authority |
| echarts | 6.1.0 | Linked Research charts, zoom, brush, crosshair | Apache-2.0 | Wave 1 interaction authority |
| @xyflow/react | 12.11.2 | Typed Strategy Visual graph | MIT | Wave 1 interaction authority |
| monaco-editor | 0.56.0 | Python editor and Diff Editor | MIT | Wave 1 interaction authority |
| @tanstack/react-table | 8.21.3 | Controlled grid contract | MIT | Accepted table dependency |
| @tanstack/react-virtual | 3.14.9 | Virtual row contract | MIT | Accepted large-grid dependency |
| cmdk | 1.1.1 | Command palette | MIT | Accepted command interaction |
| ajv | 8.20.0 | JSON contract validation seam | MIT | Accepted typed contract dependency |
| electron-store | 10.1.0 | Approved durable-store dependency | MIT | Authority lock; current implementation uses an equivalent atomic file-backed main-process store |
| zustand | 5.0.14 | React workbench state | MIT | Durable frontend state coordination |
| lightweight-charts | 5.2.0 | Accepted future chart seam | Apache-2.0 | Dependency authority lock |
| @types/node | 22.20.1 | Node/Electron typing | MIT | Exact supporting type package |
| @types/react | 19.2.14 | React typing | MIT | Exact supporting type package |
| @types/react-dom | 19.2.3 | ReactDOM typing | MIT | Exact supporting type package |

No second package manager or lockfile is used. The quantitative backend is not implemented by this change.
