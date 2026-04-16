import { useState, useRef, useEffect } from "react";
import { askQuestion, fetchAvailableModels } from "../api/client";
import { useApi } from "../hooks/useApi";

interface Message {
  role: "user" | "assistant";
  content: string;
  model?: string;
}

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { data: modelsData } = useApi(fetchAvailableModels);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const question = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);

    try {
      const result = await askQuestion(question, selectedModel || undefined);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: result.answer, model: result.model },
      ]);
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${e.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const quickQuestions = [
    "How did my sleep affect my last workout?",
    "Should I go hard or easy today?",
    "What's my training load trend this week?",
    "Summarize my fitness progress this month",
  ];

  return (
    <div>
      <div className="page-header">
        <h1>Ask AI</h1>
        <p>Chat with your health data using AI</p>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
        <label style={{ color: "var(--text-muted)", fontSize: 13 }}>Model:</label>
        <select
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
        >
          <option value="">Default</option>
          {modelsData?.models?.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      <div className="chat-container">
        <div className="chat-messages">
          {messages.length === 0 && (
            <div style={{ textAlign: "center", color: "var(--text-muted)", padding: 40 }}>
              <p style={{ marginBottom: 20 }}>Ask anything about your health data</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
                {quickQuestions.map((q) => (
                  <button
                    key={q}
                    className="btn"
                    style={{ fontSize: 12, padding: "8px 14px", background: "var(--bg-hover)" }}
                    onClick={() => {
                      setInput(q);
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`chat-message ${msg.role}`}>
              <div style={{ whiteSpace: "pre-wrap" }}>{msg.content}</div>
              {msg.model && (
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
                  Model: {msg.model}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="chat-message assistant">
              <div style={{ color: "var(--text-muted)" }}>Thinking...</div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <form className="chat-input" onSubmit={handleSubmit}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your workouts, sleep, recovery..."
            disabled={loading}
          />
          <button type="submit" disabled={loading || !input.trim()}>
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
