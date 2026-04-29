import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import {
  PersistQueryClientProvider,
  removeOldestQuery,
} from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { UnitsProvider } from "./hooks/useUnits";
import {
  APP_GC_TIME_MS,
  APP_STALE_TIME_MS,
  QUERY_CACHE_BUSTER,
  QUERY_CACHE_STORAGE_KEY,
  QUERY_CACHE_THROTTLE_MS,
  shouldPersistAppQuery,
} from "./lib/queryCache";
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

function getQueryCacheStorage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

const queryPersister = createSyncStoragePersister({
  storage: getQueryCacheStorage(),
  key: QUERY_CACHE_STORAGE_KEY,
  throttleTime: QUERY_CACHE_THROTTLE_MS,
  retry: removeOldestQuery,
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister: queryPersister,
        maxAge: APP_GC_TIME_MS,
        buster: QUERY_CACHE_BUSTER,
        dehydrateOptions: {
          shouldDehydrateQuery: shouldPersistAppQuery,
        },
      }}
    >
      <BrowserRouter>
        <UnitsProvider>
          <App />
        </UnitsProvider>
      </BrowserRouter>
    </PersistQueryClientProvider>
  </React.StrictMode>
);
