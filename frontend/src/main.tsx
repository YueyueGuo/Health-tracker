import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { UnitsProvider } from "./hooks/useUnits";
import "./styles/globals.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <UnitsProvider>
        <App />
      </UnitsProvider>
    </BrowserRouter>
  </React.StrictMode>
);
