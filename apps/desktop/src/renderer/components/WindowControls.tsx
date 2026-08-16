import React, { useEffect, useState } from "react";

export function WindowControls() {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    let active = true;
    void window.v3Desktop.windowState().then((state) => { if (active) setMaximized(state.maximized); });
    const unsubscribe = window.v3Desktop.onWindowStateChanged((state) => { if (active) setMaximized(state.maximized); });
    return () => { active = false; unsubscribe(); };
  }, []);

  const run = (action: "minimize" | "toggle-maximize" | "close") => {
    void window.v3Desktop.windowControl(action).then((state) => setMaximized(state.maximized));
  };

  return <div className="window-controls" aria-label="窗口控制" data-testid="window-controls">
    <button data-window-control="minimize" onClick={() => run("minimize")} aria-label="最小化窗口" title="最小化窗口"><span aria-hidden="true">―</span></button>
    <button data-window-control="toggle-maximize" onClick={() => run("toggle-maximize")} aria-label={maximized ? "还原窗口" : "最大化窗口"} title={maximized ? "还原窗口" : "最大化窗口"}><span aria-hidden="true">{maximized ? "❐" : "□"}</span></button>
    <button className="window-close" data-window-control="close" onClick={() => run("close")} aria-label="关闭窗口" title="关闭窗口"><span aria-hidden="true">×</span></button>
  </div>;
}
