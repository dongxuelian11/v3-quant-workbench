import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { ProductApp } from "./ProductApp";

const node = document.getElementById("app");
if (!node) throw new Error("Renderer root missing");
createRoot(node).render(<React.StrictMode><ProductApp /></React.StrictMode>);
