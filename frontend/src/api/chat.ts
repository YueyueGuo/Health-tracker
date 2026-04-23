import { fetchJson } from "./http";

export interface ChatResponse {
  answer: string;
  model: string;
  tokens_used?: number | null;
}

export function askQuestion(question: string, model?: string) {
  return fetchJson<ChatResponse>("/chat/ask", {
    method: "POST",
    body: JSON.stringify({ question, model: model || undefined }),
  });
}

export function fetchAvailableModels() {
  return fetchJson<{ models: string[] }>("/chat/models");
}
