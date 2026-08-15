import React, { useEffect } from "react";
import { useProductRuntime } from "../productRuntimeStore";

/**
 * Compact header chip summarizing the LIVE B3 product connection. It reflects
 * canonical read state only; backend task events are treated as hints that
 * trigger a re-query, never as the product truth itself.
 */
export function ProductRuntimeStatusChip() {
  const surface = useProductRuntime((state) => state.surface);
  const boundProject = useProductRuntime((state) => state.boundProject);
  const refresh = useProductRuntime((state) => state.refresh);

  useEffect(() => {
    void refresh();
    // Event notifications are hints: schedule a canonical re-query.
    const bridge = window.v3BackendRuntime;
    if (!bridge) return;
    const stop = bridge.onEvidenceEvent(() => { void useProductRuntime.getState().refresh(); });
    const stopConnection = bridge.onConnectionState(() => { void useProductRuntime.getState().refresh(); });
    return () => { stop(); stopConnection(); };
  }, [refresh]);

  const label = boundProject
    ? `已绑定 · ${boundProject.projectId.slice(0, 12)}…`
    : surface === "BACKEND_DISCONNECTED" ? "后端未连接"
    : surface === "BACKEND_STARTING" ? "后端启动中"
    : "未绑定项目";
  return <span className="product-status-chip" data-bound={boundProject !== null} title={`产品运行时状态 · ${surface}`}>{label}</span>;
}
