import { useCallback, useEffect, useRef, useState } from "react";
import {
  InspectorPanel,
  type InspectorTab,
  type StreamTraceState,
} from "./components/InspectorPanel";
import { MessageList, type DisplayMessage } from "./components/MessageList";
import { SessionSidebar } from "./components/SessionSidebar";
import {
  ApiClientError,
  deleteSession,
  fetchHealth,
  getSessionDetail,
  listSessions,
  streamChat,
} from "./lib/api";
import { downloadTextFile, formatSessionAsMarkdown } from "./lib/snippets";
import type { HealthResponse, ProviderName, SessionSummary } from "./types/api";

type ThemeMode = "light" | "dark";

const INITIAL_TRACE: StreamTraceState = {
  status: "idle",
  requestId: null,
  provider: null,
  model: null,
  deltaCount: 0,
  charsReceived: 0,
  ttftMs: null,
  latencyMs: null,
  tokensPerSec: null,
  errorMessage: null,
};

function readInitialTheme(): ThemeMode {
  try {
    const saved = localStorage.getItem("llm-workbench-theme");
    if (saved === "light" || saved === "dark") {
      return saved;
    }
  } catch {
    // Ignore storage access restrictions
  }
  return "light";
}

export default function App() {
  const [theme, setTheme] = useState<ThemeMode>(readInitialTheme);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState<boolean>(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [loadingSession, setLoadingSession] = useState<boolean>(false);

  const [provider, setProvider] = useState<ProviderName>("gemini");
  const [model, setModel] = useState<string>("gemini-4-hydrogen");
  const [systemPrompt, setSystemPrompt] = useState<string>("");
  const [temperature, setTemperature] = useState<string>("");
  const [maxTokens, setMaxTokens] = useState<string>("");

  const [draft, setDraft] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [streamTrace, setStreamTrace] = useState<StreamTraceState>(INITIAL_TRACE);
  const [chatError, setChatError] = useState<{
    code: string;
    message: string;
    requestId?: string | null;
  } | null>(null);

  const [mobileDrawerOpen, setMobileDrawerOpen] = useState<boolean>(false);
  const [inspectorOpen, setInspectorOpen] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.innerWidth >= 1280 : true,
  );
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("inspector");
  const [exportMenuOpen, setExportMenuOpen] = useState<boolean>(false);

  const abortRef = useRef<AbortController | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("llm-workbench-theme", theme);
    } catch {
      // Ignore storage restrictions
    }
  }, [theme]);

  const loadHealth = useCallback(async () => {
    try {
      const data = await fetchHealth();
      setHealth(data);
      setHealthError(null);
      setProvider((current) => current || data.default_provider);
      setModel((current) => current || data.default_model);
    } catch (err) {
      setHealth(null);
      setHealthError(err instanceof Error ? err.message : "Backend unreachable");
    }
  }, []);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    setSessionsError(null);
    try {
      const data = await listSessions(50, 0);
      setSessions(data.items);
    } catch (err) {
      setSessionsError(err instanceof Error ? err.message : "Failed to load sessions");
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHealth();
    void loadSessions();
  }, [loadHealth, loadSessions]);

  const handleNewSession = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
      setIsStreaming(false);
    }
    setActiveSessionId(null);
    setMessages([]);
    setChatError(null);
    setStreamTrace(INITIAL_TRACE);
    composerRef.current?.focus();
  }, []);

  // Global keyboard shortcuts: Ctrl/Cmd+K (new session), Ctrl/Cmd+I (inspector), Escape (export menu)
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        handleNewSession();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "i") {
        event.preventDefault();
        setInspectorOpen((prev) => !prev);
      } else if (event.key === "Escape") {
        setExportMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleNewSession]);

  const handleSelectSession = useCallback(async (sessionId: string) => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
      setIsStreaming(false);
    }
    setActiveSessionId(sessionId);
    setLoadingSession(true);
    setChatError(null);
    setExportMenuOpen(false);
    try {
      const detail = await getSessionDetail(sessionId);
      setMessages(detail.messages);
      setProvider(detail.provider as ProviderName);
      setModel(detail.model);
      setSystemPrompt(detail.system_prompt ?? "");
      setStreamTrace(INITIAL_TRACE);
    } catch (err) {
      setChatError({
        code: err instanceof ApiClientError ? err.code : "load_failed",
        message: err instanceof Error ? err.message : "Failed to load session messages.",
        requestId: err instanceof ApiClientError ? err.requestId : null,
      });
    } finally {
      setLoadingSession(false);
    }
  }, []);

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((item) => item.id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
        setStreamTrace(INITIAL_TRACE);
      }
    },
    [activeSessionId],
  );

  const handleStopStream = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setIsStreaming(false);
    setStreamTrace((prev) => ({ ...prev, status: "aborted" }));
    setMessages((prev) =>
      prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m)),
    );
  };

  const handleSend = async (overrideMessage?: string) => {
    const text = (overrideMessage ?? draft).trim();
    if (!text || isStreaming) return;

    setChatError(null);
    if (!overrideMessage) {
      setDraft("");
    }

    const tempUserId = `temp-user-${Date.now()}`;
    const tempAssistantId = `temp-assistant-${Date.now()}`;
    const nowIso = new Date().toISOString();
    const requestStartedMs = performance.now();
    let firstTokenRecorded = false;

    const optimisticUser: DisplayMessage = {
      id: tempUserId,
      role: "user",
      content: text,
      provider: null,
      model: null,
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      estimated_cost_usd: 0,
      ttft_ms: null,
      latency_ms: null,
      tokens_per_sec: null,
      created_at: nowIso,
    };

    const optimisticAssistant: DisplayMessage = {
      id: tempAssistantId,
      role: "assistant",
      content: "",
      provider,
      model: model.trim() || null,
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      estimated_cost_usd: 0,
      ttft_ms: null,
      latency_ms: null,
      tokens_per_sec: null,
      created_at: nowIso,
      isStreaming: true,
    };

    setMessages((prev) => [...prev, optimisticUser, optimisticAssistant]);
    setIsStreaming(true);
    setStreamTrace({
      status: "streaming",
      requestId: null,
      provider,
      model: model.trim() || null,
      deltaCount: 0,
      charsReceived: 0,
      ttftMs: null,
      latencyMs: null,
      tokensPerSec: null,
      errorMessage: null,
    });

    const controller = new AbortController();
    abortRef.current = controller;

    const parsedTemp = temperature.trim() !== "" ? Number(temperature) : undefined;
    const parsedMaxTokens = maxTokens.trim() !== "" ? Number(maxTokens) : undefined;

    try {
      await streamChat(
        {
          session_id: activeSessionId,
          message: text,
          provider,
          model: model.trim() || undefined,
          system_prompt: systemPrompt.trim() || undefined,
          temperature:
            parsedTemp !== undefined && !Number.isNaN(parsedTemp) ? parsedTemp : undefined,
          max_tokens:
            parsedMaxTokens !== undefined && !Number.isNaN(parsedMaxTokens)
              ? parsedMaxTokens
              : undefined,
        },
        {
          onHeaders: ({ requestId }) => {
            setStreamTrace((prev) => ({ ...prev, requestId }));
          },
          onMeta: (meta) => {
            setActiveSessionId(meta.session_id);
            setStreamTrace((prev) => ({
              ...prev,
              provider: meta.provider,
              model: meta.model,
            }));
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempAssistantId
                  ? { ...m, provider: meta.provider, model: meta.model }
                  : m,
              ),
            );
          },
          onDelta: (delta) => {
            const observedTtft = !firstTokenRecorded
              ? Math.round(performance.now() - requestStartedMs)
              : null;
            if (!firstTokenRecorded) {
              firstTokenRecorded = true;
            }
            setStreamTrace((prev) => ({
              ...prev,
              deltaCount: prev.deltaCount + 1,
              charsReceived: prev.charsReceived + delta.text.length,
              ttftMs: observedTtft ?? prev.ttftMs,
            }));
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempAssistantId ? { ...m, content: m.content + delta.text } : m,
              ),
            );
          },
          onDone: (done) => {
            setActiveSessionId(done.session_id);
            setStreamTrace((prev) => ({
              ...prev,
              status: "completed",
              provider: done.provider,
              model: done.model,
              ttftMs: done.metrics.ttft_ms,
              latencyMs: done.metrics.latency_ms,
              tokensPerSec: done.metrics.tokens_per_sec,
            }));
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempAssistantId
                  ? {
                      ...m,
                      id: done.message_id,
                      provider: done.provider,
                      model: done.model,
                      input_tokens: done.usage.input_tokens,
                      output_tokens: done.usage.output_tokens,
                      total_tokens: done.usage.total_tokens,
                      estimated_cost_usd: done.usage.estimated_cost_usd,
                      ttft_ms: done.metrics.ttft_ms,
                      latency_ms: done.metrics.latency_ms,
                      tokens_per_sec: done.metrics.tokens_per_sec,
                      isStreaming: false,
                    }
                  : m,
              ),
            );
            void loadSessions();
          },
          onError: (err) => {
            setChatError({
              code: err.code,
              message: err.message,
              requestId: err.request_id,
            });
            setStreamTrace((prev) => ({
              ...prev,
              status: "error",
              requestId: err.request_id ?? prev.requestId,
              errorMessage: `${err.code}: ${err.message}`,
            }));
            setMessages((prev) =>
              prev.map((m) => (m.id === tempAssistantId ? { ...m, isStreaming: false } : m)),
            );
          },
        },
        controller.signal,
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        void loadSessions();
        return;
      }
      setMessages((prev) =>
        prev.filter((m) => !(m.id === tempAssistantId && m.content.length === 0)),
      );
      const errMsg = err instanceof Error ? err.message : "Failed to reach LLM API service.";
      const errCode = err instanceof ApiClientError ? err.code : "network_error";
      const reqId = err instanceof ApiClientError ? err.requestId : null;
      setChatError({ code: errCode, message: errMsg, requestId: reqId });
      setStreamTrace((prev) => ({
        ...prev,
        status: "error",
        requestId: reqId ?? prev.requestId,
        errorMessage: `${errCode}: ${errMsg}`,
      }));
    } finally {
      abortRef.current = null;
      setIsStreaming(false);
    }
  };

  const activeSessionSummary = sessions.find((s) => s.id === activeSessionId) ?? null;

  const handleExport = (format: "json" | "markdown") => {
    const slug = (activeSessionId || "session").slice(0, 8);
    if (format === "json") {
      downloadTextFile(
        `llm-session-${slug}.json`,
        JSON.stringify({ session: activeSessionSummary, messages }, null, 2),
        "application/json",
      );
    } else {
      downloadTextFile(
        `llm-session-${slug}.md`,
        formatSessionAsMarkdown(activeSessionSummary, messages),
        "text/markdown;charset=utf-8",
      );
    }
    setExportMenuOpen(false);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header
        className="flex items-center justify-between gap-3 border-b px-4 py-2"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={() => setMobileDrawerOpen(true)}
            aria-label="Open sessions sidebar"
            className="flex min-h-[44px] items-center rounded-md border px-3 text-xs font-semibold lg:hidden"
            style={{
              borderColor: "var(--border-strong)",
              backgroundColor: "var(--bg-canvas)",
              color: "var(--ink-primary)",
            }}
          >
            Sessions
          </button>

          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <h1
                className="truncate text-sm font-bold tracking-tight sm:text-base"
                style={{ color: "var(--ink-primary)" }}
              >
                LLM API Service
              </h1>
              {health ? (
                <span
                  className="font-mono-tech hidden items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] sm:inline-flex"
                  style={{
                    borderColor: "var(--border-subtle)",
                    backgroundColor: "var(--bg-canvas)",
                    color: "var(--ink-secondary)",
                  }}
                >
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: "var(--success)" }}
                    aria-hidden="true"
                  />
                  {health.database_dialect}
                </span>
              ) : healthError ? (
                <span
                  className="font-mono-tech text-[11px]"
                  style={{ color: "var(--danger)" }}
                >
                  offline
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <div className="relative">
              <button
                type="button"
                aria-expanded={exportMenuOpen}
                aria-haspopup="menu"
                onClick={() => setExportMenuOpen((prev) => !prev)}
                className="min-h-[44px] rounded-md border px-3 text-xs font-semibold"
                style={{
                  borderColor: "var(--border-strong)",
                  backgroundColor: "var(--bg-canvas)",
                  color: "var(--ink-primary)",
                }}
              >
                Export
              </button>
              {exportMenuOpen && (
                <div
                  role="menu"
                  className="absolute right-0 z-30 mt-1.5 w-40 rounded-md border p-1 shadow-md"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border-strong)",
                  }}
                >
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => handleExport("json")}
                    className="block min-h-[38px] w-full rounded px-2.5 py-1.5 text-left text-xs font-medium hover:brightness-95"
                    style={{ color: "var(--ink-primary)" }}
                  >
                    Download JSON
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => handleExport("markdown")}
                    className="block min-h-[38px] w-full rounded px-2.5 py-1.5 text-left text-xs font-medium hover:brightness-95"
                    style={{ color: "var(--ink-primary)" }}
                  >
                    Download Markdown
                  </button>
                </div>
              )}
            </div>
          )}

          <button
            type="button"
            aria-pressed={inspectorOpen}
            onClick={() => setInspectorOpen((prev) => !prev)}
            className="min-h-[44px] rounded-md border px-3 text-xs font-semibold transition-colors"
            style={{
              borderColor: inspectorOpen ? "var(--accent)" : "var(--border-strong)",
              backgroundColor: inspectorOpen ? "var(--accent-soft)" : "var(--bg-canvas)",
              color: "var(--ink-primary)",
            }}
          >
            Inspector
          </button>

          <button
            type="button"
            onClick={() => setTheme((prev) => (prev === "light" ? "dark" : "light"))}
            aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
            className="min-h-[44px] rounded-md border px-3 text-xs font-semibold transition-colors"
            style={{
              borderColor: "var(--border-strong)",
              backgroundColor: "var(--bg-canvas)",
              color: "var(--ink-primary)",
            }}
          >
            {theme === "light" ? "Dark" : "Light"}
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <SessionSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          loading={sessionsLoading}
          error={sessionsError}
          mobileOpen={mobileDrawerOpen}
          onCloseMobile={() => setMobileDrawerOpen(false)}
          onNewSession={handleNewSession}
          onSelectSession={(id) => void handleSelectSession(id)}
          onDeleteSession={handleDeleteSession}
          onRetryLoad={() => void loadSessions()}
        />

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <MessageList
            messages={messages}
            loadingSession={loadingSession}
            onPickStarter={(prompt) => {
              setDraft(prompt);
              composerRef.current?.focus();
            }}
          />

          {chatError && (
            <div
              role="alert"
              className="mx-4 mb-2 rounded-md border px-4 py-2.5 text-xs sm:mx-6"
              style={{
                borderColor: "var(--danger)",
                backgroundColor: "var(--danger-soft)",
                color: "var(--ink-primary)",
              }}
            >
              <div className="mx-auto flex max-w-3xl items-start justify-between gap-3">
                <div>
                  <p className="font-semibold">
                    Error ({chatError.code}): {chatError.message}
                  </p>
                  {chatError.requestId && (
                    <p
                      className="font-mono-tech mt-0.5 text-[11px]"
                      style={{ color: "var(--ink-secondary)" }}
                    >
                      Request ID: {chatError.requestId}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setChatError(null)}
                  className="min-h-[32px] rounded px-2 text-xs font-semibold underline"
                  style={{ color: "var(--ink-primary)" }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}

          {/* Unified Docked Composer */}
          <div className="px-4 pb-4 pt-2 sm:px-6">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void handleSend();
              }}
              className="composer-shell mx-auto max-w-3xl overflow-hidden rounded-lg border"
              style={{
                backgroundColor: "var(--bg-surface)",
                borderColor: "var(--border-strong)",
              }}
            >
              <label htmlFor="prompt-composer" className="sr-only">
                Message prompt
              </label>
              <textarea
                ref={composerRef}
                id="prompt-composer"
                rows={2}
                value={draft}
                disabled={isStreaming}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void handleSend();
                  }
                }}
                placeholder="Write a prompt... (Enter to send, Shift+Enter for newline)"
                className="block w-full resize-none bg-transparent px-4 pt-3 pb-2 text-sm leading-relaxed focus:outline-none"
                style={{ color: "var(--ink-primary)" }}
              />

              <div
                className="flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2"
                style={{
                  borderColor: "var(--border-subtle)",
                  backgroundColor: "var(--bg-canvas)",
                }}
              >
                <button
                  type="button"
                  onClick={() => {
                    setInspectorTab("config");
                    setInspectorOpen(true);
                  }}
                  aria-label="Open model and parameter configuration"
                  className="font-mono-tech flex min-h-[36px] max-w-full items-center gap-1.5 truncate rounded border px-2.5 py-1 text-[11px] font-medium"
                  style={{
                    borderColor: "var(--border-subtle)",
                    backgroundColor: "var(--bg-surface)",
                    color: "var(--ink-primary)",
                  }}
                >
                  <span
                    className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ backgroundColor: "var(--accent)" }}
                    aria-hidden="true"
                  />
                  <span className="truncate">
                    {provider} / {model || "default"}
                  </span>
                  {temperature.trim() !== "" && (
                    <span style={{ color: "var(--ink-secondary)" }}>t={temperature}</span>
                  )}
                  {maxTokens.trim() !== "" && (
                    <span style={{ color: "var(--ink-secondary)" }}>max={maxTokens}</span>
                  )}
                </button>

                <div className="flex items-center gap-2.5">
                  <span
                    className="font-mono-tech hidden text-[11px] sm:inline"
                    style={{ color: "var(--ink-muted)" }}
                  >
                    {draft.length} chars
                  </span>

                  {isStreaming ? (
                    <button
                      type="button"
                      onClick={handleStopStream}
                      className="min-h-[40px] rounded-md px-4 py-1.5 text-xs font-semibold"
                      style={{
                        backgroundColor: "var(--danger)",
                        color: "#ffffff",
                      }}
                    >
                      Stop
                    </button>
                  ) : (
                    <button
                      type="submit"
                      disabled={draft.trim().length === 0}
                      className="min-h-[40px] rounded-md px-4 py-1.5 text-xs font-semibold transition-colors"
                      style={{
                        backgroundColor: "var(--accent)",
                        color: "var(--accent-ink)",
                      }}
                    >
                      Send
                    </button>
                  )}
                </div>
              </div>
            </form>
          </div>
        </main>

        <InspectorPanel
          open={inspectorOpen}
          activeTab={inspectorTab}
          onTabChange={setInspectorTab}
          onClose={() => setInspectorOpen(false)}
          sessionId={activeSessionId}
          messages={messages}
          streamTrace={streamTrace}
          provider={provider}
          model={model}
          systemPrompt={systemPrompt}
          temperature={temperature}
          maxTokens={maxTokens}
          draftPrompt={draft}
          disabled={isStreaming}
          onProviderChange={setProvider}
          onModelChange={setModel}
          onSystemPromptChange={setSystemPrompt}
          onTemperatureChange={setTemperature}
          onMaxTokensChange={setMaxTokens}
        />
      </div>
    </div>
  );
}
