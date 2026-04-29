import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { UnitsProvider } from "./hooks/useUnits";
import { APP_GC_TIME_MS, APP_STALE_TIME_MS } from "./lib/queryCache";
import "./styles/globals.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: APP_STALE_TIME_MS,
      gcTime: APP_GC_TIME_MS,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <UnitsProvider>
          <App />
        </UnitsProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
