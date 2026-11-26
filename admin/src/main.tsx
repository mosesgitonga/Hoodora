import "antd/dist/reset.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { cspNonce } from "./config";
import { tagCreatedStyles } from "./csp";

// Before anything renders, so every style element is created with the nonce.
tagCreatedStyles(cspNonce());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
