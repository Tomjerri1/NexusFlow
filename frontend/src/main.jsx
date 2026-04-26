import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { LangProvider } from "./i18n.js";
import { NodeSchemaProvider } from "./nodeSchema.js";
import "@xyflow/react/dist/style.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <LangProvider>
      <NodeSchemaProvider>
        <App />
      </NodeSchemaProvider>
    </LangProvider>
  </React.StrictMode>
);
