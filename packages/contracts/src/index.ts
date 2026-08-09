export const LAB_IDS = [
  "research",
  "strategy",
  "model",
  "backtest",
  "result"
] as const;

export type LabId = (typeof LAB_IDS)[number];

export type BackendAvailability = "unavailable" | "demo" | "formal";

export interface BackendStatus {
  availability: BackendAvailability;
  provider: "UnavailableBackendProvider" | "DemoProvider" | "CanonicalBackend";
  message: string;
  formalOutputAllowed: boolean;
}

export interface DockLayout {
  leftRail: boolean;
  inspector: boolean;
  bottomPanel: boolean;
}

export interface WorkspaceState {
  activeLab: LabId;
  inspectorOpen: boolean;
  layout: DockLayout;
  activeProject: string;
  selectedAsset: string | null;
}

export interface SaveWorkspaceRequest {
  state: WorkspaceState;
}

export type DesktopCommand =
  | "workspace.save"
  | "workspace.reset"
  | "inspector.toggle"
  | `lab.${LabId}`;

export interface DesktopBridge {
  getWorkspaceState(): Promise<WorkspaceState>;
  saveWorkspaceState(request: SaveWorkspaceRequest): Promise<WorkspaceState>;
  resetWorkspaceState(): Promise<WorkspaceState>;
  getBackendStatus(): Promise<BackendStatus>;
  sendCommand(command: DesktopCommand): Promise<void>;
}

export const DEFAULT_WORKSPACE_STATE: WorkspaceState = {
  activeLab: "research",
  inspectorOpen: true,
  layout: {
    leftRail: true,
    inspector: true,
    bottomPanel: true
  },
  activeProject: "Momentum Research / 2026 Q2",
  selectedAsset: "Universe / CN Large Cap"
};

export const UNAVAILABLE_BACKEND_STATUS: BackendStatus = {
  availability: "unavailable",
  provider: "UnavailableBackendProvider",
  message: "Canonical backend reconstruction is not part of FR-0 / FR-1.",
  formalOutputAllowed: false
};

