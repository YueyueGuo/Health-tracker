import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
      },
    },
  });
}

export interface RenderWithQueryOptions extends Omit<RenderOptions, "wrapper"> {
  /**
   * Optional shared `QueryClient` so multiple renders in the same test can
   * exercise cache behavior. When omitted a fresh client is created per call.
   */
  queryClient?: QueryClient;
}

export function renderWithQuery(
  ui: ReactElement,
  options?: RenderWithQueryOptions,
) {
  const { queryClient: injected, ...renderOptions } = options ?? {};
  const queryClient = injected ?? createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  return render(ui, { wrapper: Wrapper, ...renderOptions });
}
