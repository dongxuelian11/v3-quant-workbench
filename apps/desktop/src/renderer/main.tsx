import React from "react";
import { createRoot } from "react-dom/client";
import "dockview-react/dist/styles/dockview.css";
import "@xyflow/react/dist/style.css";
import "./styles.css";
import { App } from "./App";

const node = document.getElementById("app");
if (!node) throw new Error("Renderer root missing");
createRoot(node).render(<React.StrictMode><App /></React.StrictMode>);
