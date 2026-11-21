import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { applyTheme, storedTheme } from "./theme";
import "./styles.css";
import "./product.css";

// 首帧前落下主题，避免深色页面先闪一下再变浅。
applyTheme(storedTheme());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
