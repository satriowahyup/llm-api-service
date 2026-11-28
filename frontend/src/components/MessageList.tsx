import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { formatMs, formatTimestamp, formatTps, formatUsd } from "../lib/format";
import type { MessageItem } from "../types/api";
import { MarkdownPre } from "./CodeBlock";

export interface DisplayMessage extends MessageItem {
  isStreaming?: boolean;
}

interface MessageListProps {
  messages: DisplayMessage[];
  loadingSession: boolean;
  onPickStarter: (prompt: string) => void;
}

const FEATURED_STARTER = {
  tag: "SSE Streaming & Latency",
  title: "SQLite WAL vs PostgreSQL 17 for async FastAPI",
  prompt:
    "Compare SQLite WAL mode and PostgreSQL for async FastAPI workloads in 3 concise engineering points.",
};

const SECONDARY_STARTERS = [
  {
    tag: "Code Generation",
    title: "Async backoff retry helper (Python 3.12)",
    prompt:
      "Write a short Python 3.12 async retry helper using exponential backoff with jitter and Retry-After handling.",
  },
  {
    tag: "Protocol Trade-Off",
    title: "SSE vs WebSockets for token streaming",
    prompt:
      "Explain why Server-Sent Events (SSE) are often preferred over WebSockets for LLM token streaming.",
  },
];

export function MessageList({ messages, loadingSession, onPickStarter }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "auto" });
  }, [messages.length, messages[messages.length - 1]?.content]);

  const handleCopyMessage = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      window.setTimeout(() => setCopiedId((prev) => (prev === id ? null : prev)), 1800);
    } catch {
      // Clipboard API unavailable
    }
  };

  if (loadingSession) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <p className="text-sm" style={{ color: "var(--ink-secondary)" }}>
          Loading conversation history...
        </p>
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-5 py-10">
        <div className="w-full max-w-2xl">
          <p
            className="font-mono-tech text-xs font-medium"
            style={{ color: "var(--accent)" }}
          >
            Live Telemetry &amp; Multi-Provider Routing
          </p>
          <h2
            className="font-display mt-2 text-3xl font-medium tracking-tight sm:text-4xl"
            style={{ color: "var(--ink-primary)" }}
          >
            Inspect live multi-provider LLM streams.
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
            Route turns across Google Gemini, Anthropic Claude, OpenAI, DeepSeek, Groq, or local
            Ollama. Switch providers mid-session while monitoring live TTFT, decode speed, and USD
            cost.
          </p>

          <div className="mt-7 space-y-3">
            <button
              type="button"
              onClick={() => onPickStarter(FEATURED_STARTER.prompt)}
              className="block min-h-[44px] w-full rounded-lg border px-4 py-3.5 text-left transition-colors hover:brightness-[0.98]"
              style={{
                backgroundColor: "var(--bg-surface)",
                borderColor: "var(--border-strong)",
                borderLeftWidth: "3px",
                borderLeftColor: "var(--accent)",
              }}
            >
              <span
                className="font-mono-tech text-[11px] font-medium"
                style={{ color: "var(--accent)" }}
              >
                {FEATURED_STARTER.tag}
              </span>
              <p className="mt-1 text-sm font-semibold" style={{ color: "var(--ink-primary)" }}>
                {FEATURED_STARTER.title}
              </p>
              <p className="mt-0.5 text-xs leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
                {FEATURED_STARTER.prompt}
              </p>
            </button>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {SECONDARY_STARTERS.map((item) => (
                <button
                  key={item.title}
                  type="button"
                  onClick={() => onPickStarter(item.prompt)}
                  className="block min-h-[44px] rounded-lg border px-4 py-3 text-left transition-colors hover:brightness-[0.98]"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border-subtle)",
                  }}
                >
                  <span
                    className="font-mono-tech text-[11px] font-medium"
                    style={{ color: "var(--ink-muted)" }}
                  >
                    {item.tag}
                  </span>
                  <p className="mt-1 text-sm font-semibold" style={{ color: "var(--ink-primary)" }}>
                    {item.title}
                  </p>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  let lastAssistantSig: string | null = null;

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
      <div className="mx-auto max-w-3xl space-y-5">
        {messages.map((msg) => {
          const isUser = msg.role === "user";
          const currentSig =
            !isUser && msg.provider && msg.model ? `${msg.provider} / ${msg.model}` : null;
          const switchedFrom =
            currentSig && lastAssistantSig && currentSig !== lastAssistantSig
              ? lastAssistantSig
              : null;
          if (currentSig) {
            lastAssistantSig = currentSig;
          }

          const hasSplitBar =
            !isUser &&
            !msg.isStreaming &&
            msg.ttft_ms !== null &&
            msg.latency_ms !== null &&
            msg.latency_ms > 0;
          const ttftPct = hasSplitBar
            ? Math.min(96, Math.max(4, Math.round(((msg.ttft_ms ?? 0) / (msg.latency_ms ?? 1)) * 100)))
            : 0;

          return (
            <div key={msg.id} className="space-y-3">
              {switchedFrom && currentSig && (
                <div
                  className="font-mono-tech flex items-center gap-3 py-1 text-[11px]"
                  style={{ color: "var(--ink-secondary)" }}
                >
                  <span className="h-px flex-1" style={{ backgroundColor: "var(--border-subtle)" }} />
                  <span
                    className="rounded border px-2.5 py-0.5"
                    style={{
                      borderColor: "var(--accent)",
                      backgroundColor: "var(--accent-soft)",
                      color: "var(--ink-primary)",
                    }}
                  >
                    Provider handoff: {switchedFrom} -&gt; {currentSig}
                  </span>
                  <span className="h-px flex-1" style={{ backgroundColor: "var(--border-subtle)" }} />
                </div>
              )}

              <article
                className="rounded-lg border p-4"
                style={{
                  backgroundColor: isUser ? "var(--bg-subtle)" : "var(--bg-surface)",
                  borderColor: isUser ? "var(--border-subtle)" : "var(--border-strong)",
                }}
              >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div className="flex items-center gap-2">
                    {!isUser && (
                      <span
                        className="inline-block h-2 w-2 rounded-full"
                        style={{ backgroundColor: "var(--accent)" }}
                        aria-hidden="true"
                      />
                    )}
                    <span
                      className={isUser ? "font-semibold" : "font-mono-tech text-xs font-medium"}
                      style={{ color: "var(--ink-primary)" }}
                    >
                      {isUser
                        ? "You"
                        : msg.provider
                          ? `${msg.provider} / ${msg.model}`
                          : "Assistant"}
                    </span>
                    <span className="text-[11px]" style={{ color: "var(--ink-muted)" }}>
                      {formatTimestamp(msg.created_at)}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {msg.isStreaming ? (
                      <span
                        className="font-mono-tech text-[11px] font-medium"
                        style={{ color: "var(--accent)" }}
                      >
                        streaming...
                      </span>
                    ) : (
                      !isUser &&
                      msg.content.length > 0 && (
                        <button
                          type="button"
                          onClick={() => void handleCopyMessage(msg.id, msg.content)}
                          className="font-mono-tech min-h-[28px] rounded border px-2 py-0.5 text-[11px] font-medium"
                          style={{
                            borderColor:
                              copiedId === msg.id ? "var(--accent)" : "var(--border-subtle)",
                            backgroundColor:
                              copiedId === msg.id ? "var(--accent-soft)" : "var(--bg-canvas)",
                            color: "var(--ink-primary)",
                          }}
                        >
                          {copiedId === msg.id ? "Copied" : "Copy"}
                        </button>
                      )
                    )}
                  </div>
                </div>

                {isUser ? (
                  <p
                    className="whitespace-pre-wrap text-sm leading-relaxed"
                    style={{ color: "var(--ink-primary)" }}
                  >
                    {msg.content}
                  </p>
                ) : (
                  <div className="chat-prose text-sm" style={{ color: "var(--ink-primary)" }}>
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        pre: ({ children }) => <MarkdownPre>{children}</MarkdownPre>,
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                    {msg.isStreaming && <span className="stream-caret" aria-hidden="true" />}
                  </div>
                )}

                {!isUser && !msg.isStreaming && (msg.latency_ms !== null || msg.total_tokens > 0) && (
                  <div
                    className="mt-3 space-y-2 border-t pt-2.5"
                    style={{ borderColor: "var(--border-subtle)" }}
                  >
                    {hasSplitBar && (
                      <div
                        className="flex h-1.5 w-full overflow-hidden rounded-sm"
                        style={{ backgroundColor: "var(--bg-subtle)" }}
                        title={`TTFT ${formatMs(msg.ttft_ms)} (${ttftPct}%) vs Decode ${formatMs((msg.latency_ms ?? 0) - (msg.ttft_ms ?? 0))} (${100 - ttftPct}%)`}
                      >
                        <div
                          style={{
                            width: `${ttftPct}%`,
                            backgroundColor: "var(--accent)",
                          }}
                        />
                        <div
                          style={{
                            width: `${100 - ttftPct}%`,
                            backgroundColor: "var(--bar-decode)",
                          }}
                        />
                      </div>
                    )}

                    <div
                      className="font-mono-tech flex flex-wrap gap-x-4 gap-y-1 text-[11px]"
                      style={{ color: "var(--ink-secondary)" }}
                    >
                      <span>TTFT: {formatMs(msg.ttft_ms)}</span>
                      <span>Latency: {formatMs(msg.latency_ms)}</span>
                      <span>Speed: {formatTps(msg.tokens_per_sec)}</span>
                      <span>
                        Tokens: {msg.input_tokens} in / {msg.output_tokens} out
                      </span>
                      <span>Cost: {formatUsd(msg.estimated_cost_usd)}</span>
                    </div>
                  </div>
                )}
              </article>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
