import { useEffect, useMemo, useState } from "react";
import { formatMs, formatTps, formatUsd } from "../lib/format";
import { buildCurlSnippet, buildPythonSnippet } from "../lib/snippets";
import { PROVIDER_PRESETS, type MessageItem, type ProviderName } from "../types/api";

export type InspectorTab = "inspector" | "config";

export interface StreamTraceState {
  status: "idle" | "streaming" | "completed" | "aborted" | "error";
  requestId: string | null;
  provider: string | null;
  model: string | null;
  deltaCount: number;
  charsReceived: number;
  ttftMs: number | null;
  latencyMs: number | null;
  tokensPerSec: number | null;
  errorMessage: string | null;
}

interface InspectorPanelProps {
  open: boolean;
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  onClose: () => void;
  sessionId: string | null;
  messages: MessageItem[];
  streamTrace: StreamTraceState;
  provider: ProviderName;
  model: string;
  systemPrompt: string;
  temperature: string;
  maxTokens: string;
  draftPrompt: string;
  disabled: boolean;
  onProviderChange: (provider: ProviderName) => void;
  onModelChange: (model: string) => void;
  onSystemPromptChange: (value: string) => void;
  onTemperatureChange: (value: string) => void;
  onMaxTokensChange: (value: string) => void;
}

export function InspectorPanel({
  open,
  activeTab,
  onTabChange,
  onClose,
  sessionId,
  messages,
  streamTrace,
  provider,
  model,
  systemPrompt,
  temperature,
  maxTokens,
  draftPrompt,
  disabled,
  onProviderChange,
  onModelChange,
  onSystemPromptChange,
  onTemperatureChange,
  onMaxTokensChange,
}: InspectorPanelProps) {
  const [snippetLang, setSnippetLang] = useState<"curl" | "python">("curl");
  const [copiedSnippet, setCopiedSnippet] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && window.innerWidth < 1280) {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  const currentPreset =
    PROVIDER_PRESETS.find((item) => item.id === provider) ?? PROVIDER_PRESETS[0];

  const sessionStats = useMemo(() => {
    const assistantMsgs = messages.filter((m) => m.role === "assistant");
    let inputTokens = 0;
    let outputTokens = 0;
    let totalCost = 0;
    const ttfts: number[] = [];
    let lastSpeed: number | null = null;
    const providersUsed = new Set<string>();

    for (const msg of assistantMsgs) {
      inputTokens += msg.input_tokens;
      outputTokens += msg.output_tokens;
      totalCost += msg.estimated_cost_usd;
      if (msg.ttft_ms !== null) ttfts.push(msg.ttft_ms);
      if (msg.tokens_per_sec !== null) lastSpeed = msg.tokens_per_sec;
      if (msg.provider) providersUsed.add(msg.provider);
    }

    const totalTokens = inputTokens + outputTokens;
    const avgTtft =
      ttfts.length > 0 ? ttfts.reduce((sum, val) => sum + val, 0) / ttfts.length : null;
    const inputPct = totalTokens > 0 ? Math.round((inputTokens / totalTokens) * 100) : 0;

    return {
      inputTokens,
      outputTokens,
      totalTokens,
      totalCost,
      avgTtft,
      lastSpeed,
      inputPct,
      providersUsed: Array.from(providersUsed),
    };
  }, [messages]);

  const snippetText = useMemo(() => {
    const params = {
      sessionId,
      provider,
      model,
      systemPrompt,
      temperature,
      maxTokens,
      promptText: draftPrompt,
    };
    return snippetLang === "curl" ? buildCurlSnippet(params) : buildPythonSnippet(params);
  }, [snippetLang, sessionId, provider, model, systemPrompt, temperature, maxTokens, draftPrompt]);

  const handleCopySnippet = async () => {
    try {
      await navigator.clipboard.writeText(snippetText);
      setCopiedSnippet(true);
      window.setTimeout(() => setCopiedSnippet(false), 1800);
    } catch {
      // Ignore restricted clipboard
    }
  };

  const handleProviderSelect = (nextProvider: ProviderName) => {
    onProviderChange(nextProvider);
    const preset = PROVIDER_PRESETS.find((item) => item.id === nextProvider);
    if (preset) {
      onModelChange(preset.defaultModel);
    }
  };

  if (!open) return null;

  const panelBody = (
    <aside
      aria-label="Telemetry inspector and model configuration"
      className="flex h-full flex-col border-l"
      style={{
        backgroundColor: "var(--bg-rail)",
        borderColor: "var(--border-subtle)",
      }}
    >
      <div
        className="flex min-w-0 items-center justify-between gap-2 border-b p-2.5"
        style={{
          borderColor: "var(--border-subtle)",
          backgroundColor: "var(--bg-surface)",
        }}
      >
        <div
          role="tablist"
          aria-label="Inspector views"
          className="grid min-w-0 flex-1 grid-cols-2 gap-1 rounded-md p-1"
          style={{ backgroundColor: "var(--bg-subtle)" }}
        >
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "inspector"}
            onClick={() => onTabChange("inspector")}
            className="min-h-[36px] truncate rounded px-1.5 text-xs font-semibold transition-colors"
            style={{
              backgroundColor: activeTab === "inspector" ? "var(--bg-surface)" : "transparent",
              color: "var(--ink-primary)",
            }}
          >
            Inspector
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "config"}
            onClick={() => onTabChange("config")}
            className="min-h-[36px] truncate rounded px-1.5 text-xs font-semibold transition-colors"
            style={{
              backgroundColor: activeTab === "config" ? "var(--bg-surface)" : "transparent",
              color: "var(--ink-primary)",
            }}
          >
            Config
          </button>
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label="Close inspector panel"
          className="min-h-[36px] shrink-0 rounded-md border px-2.5 text-xs font-semibold"
          style={{
            borderColor: "var(--border-strong)",
            backgroundColor: "var(--bg-canvas)",
            color: "var(--ink-primary)",
          }}
        >
          Hide
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3.5">
        {activeTab === "inspector" ? (
          <div className="space-y-4">
            {/* Session Telemetry KPI Grid */}
            <section>
              <h2
                className="text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: "var(--ink-muted)" }}
              >
                Session Telemetry
              </h2>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div
                  className="rounded-md border p-2.5"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border-subtle)",
                  }}
                >
                  <p className="text-[11px]" style={{ color: "var(--ink-secondary)" }}>
                    Session Cost
                  </p>
                  <p
                    className="font-mono-tech mt-1 text-sm font-semibold"
                    style={{ color: "var(--ink-primary)" }}
                  >
                    {formatUsd(sessionStats.totalCost)}
                  </p>
                </div>

                <div
                  className="rounded-md border p-2.5"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border-subtle)",
                  }}
                >
                  <p className="text-[11px]" style={{ color: "var(--ink-secondary)" }}>
                    Avg TTFT
                  </p>
                  <p
                    className="font-mono-tech mt-1 text-sm font-semibold"
                    style={{ color: "var(--ink-primary)" }}
                  >
                    {formatMs(sessionStats.avgTtft)}
                  </p>
                </div>

                <div
                  className="rounded-md border p-2.5"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border-subtle)",
                  }}
                >
                  <p className="text-[11px]" style={{ color: "var(--ink-secondary)" }}>
                    Last Speed
                  </p>
                  <p
                    className="font-mono-tech mt-1 text-sm font-semibold"
                    style={{ color: "var(--ink-primary)" }}
                  >
                    {formatTps(sessionStats.lastSpeed)}
                  </p>
                </div>

                <div
                  className="rounded-md border p-2.5"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border-subtle)",
                  }}
                >
                  <p className="text-[11px]" style={{ color: "var(--ink-secondary)" }}>
                    Total Tokens
                  </p>
                  <p
                    className="font-mono-tech mt-1 text-sm font-semibold"
                    style={{ color: "var(--ink-primary)" }}
                  >
                    {sessionStats.totalTokens.toLocaleString()}
                  </p>
                </div>
              </div>

              {sessionStats.totalTokens > 0 && (
                <div
                  className="mt-2 rounded-md border p-2.5"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border-subtle)",
                  }}
                >
                  <div
                    className="font-mono-tech flex justify-between text-[11px]"
                    style={{ color: "var(--ink-secondary)" }}
                  >
                    <span>Input: {sessionStats.inputTokens}</span>
                    <span>Output: {sessionStats.outputTokens}</span>
                  </div>
                  <div
                    className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-sm"
                    style={{ backgroundColor: "var(--bg-subtle)" }}
                  >
                    <div
                      style={{
                        width: `${sessionStats.inputPct}%`,
                        backgroundColor: "var(--bar-decode)",
                      }}
                    />
                    <div
                      style={{
                        width: `${100 - sessionStats.inputPct}%`,
                        backgroundColor: "var(--accent)",
                      }}
                    />
                  </div>
                </div>
              )}

              {sessionStats.providersUsed.length > 0 && (
                <p
                  className="font-mono-tech mt-2 text-[11px]"
                  style={{ color: "var(--ink-secondary)" }}
                >
                  Providers used: {sessionStats.providersUsed.join(", ")}
                </p>
              )}
            </section>

            {/* Live SSE Wire Inspector */}
            <section
              className="border-t pt-4"
              style={{ borderColor: "var(--border-subtle)" }}
            >
              <div className="flex items-center justify-between">
                <h2
                  className="text-[11px] font-semibold uppercase tracking-wider"
                  style={{ color: "var(--ink-muted)" }}
                >
                  Live SSE Stream Trace
                </h2>
                <span
                  className="font-mono-tech text-[11px] font-medium"
                  style={{
                    color:
                      streamTrace.status === "streaming"
                        ? "var(--accent)"
                        : streamTrace.status === "error"
                          ? "var(--danger)"
                          : "var(--ink-secondary)",
                  }}
                >
                  {streamTrace.status}
                </span>
              </div>

              <div
                className="font-mono-tech mt-2 space-y-1.5 rounded-md border p-3 text-[11px]"
                style={{
                  backgroundColor: "var(--bg-surface)",
                  borderColor: "var(--border-subtle)",
                  color: "var(--ink-secondary)",
                }}
              >
                {streamTrace.status === "idle" ? (
                  <p>Send a prompt to inspect live SSE frames, TTFT, and request correlation IDs.</p>
                ) : (
                  <>
                    <div className="flex justify-between gap-2">
                      <span>Route</span>
                      <span style={{ color: "var(--ink-primary)" }}>POST /v1/chat/stream</span>
                    </div>
                    {streamTrace.provider && (
                      <div className="flex justify-between gap-2">
                        <span>Target</span>
                        <span className="truncate" style={{ color: "var(--ink-primary)" }}>
                          {streamTrace.provider}/{streamTrace.model}
                        </span>
                      </div>
                    )}
                    <div className="flex justify-between gap-2">
                      <span>Delta Frames</span>
                      <span style={{ color: "var(--ink-primary)" }}>
                        {streamTrace.deltaCount} ({streamTrace.charsReceived} chars)
                      </span>
                    </div>
                    <div className="flex justify-between gap-2">
                      <span>TTFT / Total</span>
                      <span style={{ color: "var(--ink-primary)" }}>
                        {formatMs(streamTrace.ttftMs)} / {formatMs(streamTrace.latencyMs)}
                      </span>
                    </div>
                    {streamTrace.requestId && (
                      <div className="truncate border-t pt-1.5" style={{ borderColor: "var(--border-subtle)" }}>
                        Req ID: {streamTrace.requestId}
                      </div>
                    )}
                    {streamTrace.errorMessage && (
                      <p className="pt-1" style={{ color: "var(--danger)" }}>
                        {streamTrace.errorMessage}
                      </p>
                    )}
                  </>
                )}
              </div>
            </section>

            {/* Copy as cURL / Python Snippet */}
            <section
              className="border-t pt-4"
              style={{ borderColor: "var(--border-subtle)" }}
            >
              <div className="flex items-center justify-between gap-2">
                <h2
                  className="text-[11px] font-semibold uppercase tracking-wider"
                  style={{ color: "var(--ink-muted)" }}
                >
                  API Request Snippet
                </h2>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setSnippetLang("curl")}
                    className="font-mono-tech min-h-[28px] rounded border px-2 text-[11px] font-medium"
                    style={{
                      borderColor:
                        snippetLang === "curl" ? "var(--accent)" : "var(--border-subtle)",
                      backgroundColor:
                        snippetLang === "curl" ? "var(--accent-soft)" : "var(--bg-surface)",
                      color: "var(--ink-primary)",
                    }}
                  >
                    cURL
                  </button>
                  <button
                    type="button"
                    onClick={() => setSnippetLang("python")}
                    className="font-mono-tech min-h-[28px] rounded border px-2 text-[11px] font-medium"
                    style={{
                      borderColor:
                        snippetLang === "python" ? "var(--accent)" : "var(--border-subtle)",
                      backgroundColor:
                        snippetLang === "python" ? "var(--accent-soft)" : "var(--bg-surface)",
                      color: "var(--ink-primary)",
                    }}
                  >
                    Python
                  </button>
                </div>
              </div>

              <div
                className="mt-2 overflow-hidden rounded-md border"
                style={{
                  backgroundColor: "var(--bg-surface)",
                  borderColor: "var(--border-subtle)",
                }}
              >
                <pre
                  className="font-mono-tech max-h-48 overflow-auto p-2.5 text-[11px] leading-relaxed"
                  style={{ color: "var(--ink-primary)" }}
                >
                  {snippetText}
                </pre>
                <div
                  className="flex justify-end border-t px-2.5 py-1.5"
                  style={{ borderColor: "var(--border-subtle)" }}
                >
                  <button
                    type="button"
                    onClick={() => void handleCopySnippet()}
                    className="font-mono-tech min-h-[30px] rounded border px-2.5 text-[11px] font-semibold"
                    style={{
                      borderColor: copiedSnippet ? "var(--accent)" : "var(--border-strong)",
                      backgroundColor: copiedSnippet ? "var(--accent-soft)" : "var(--bg-canvas)",
                      color: "var(--ink-primary)",
                    }}
                  >
                    {copiedSnippet ? "Copied" : `Copy ${snippetLang === "curl" ? "cURL" : "Python"}`}
                  </button>
                </div>
              </div>
            </section>
          </div>
        ) : (
          /* Config Tab */
          <div className="space-y-4">
            <div>
              <label
                htmlFor="provider-select"
                className="mb-1.5 block text-xs font-semibold"
                style={{ color: "var(--ink-secondary)" }}
              >
                LLM Provider
              </label>
              <select
                id="provider-select"
                value={provider}
                disabled={disabled}
                onChange={(e) => handleProviderSelect(e.target.value as ProviderName)}
                className="min-h-[44px] w-full rounded-md border px-3 py-2 text-sm font-medium"
                style={{
                  backgroundColor: "var(--bg-surface)",
                  borderColor: "var(--border-strong)",
                  color: "var(--ink-primary)",
                }}
              >
                {PROVIDER_PRESETS.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="model-input"
                className="mb-1.5 block text-xs font-semibold"
                style={{ color: "var(--ink-secondary)" }}
              >
                Model Identifier
              </label>
              <input
                id="model-input"
                type="text"
                list="model-suggestions"
                value={model}
                disabled={disabled}
                onChange={(e) => onModelChange(e.target.value)}
                placeholder={currentPreset.defaultModel}
                className="font-mono-tech min-h-[44px] w-full rounded-md border px-3 py-2 text-xs"
                style={{
                  backgroundColor: "var(--bg-surface)",
                  borderColor: "var(--border-strong)",
                  color: "var(--ink-primary)",
                }}
              />
              <datalist id="model-suggestions">
                {currentPreset.suggestedModels.map((modelName) => (
                  <option key={modelName} value={modelName} />
                ))}
              </datalist>

              <div className="mt-2 flex flex-wrap gap-1.5">
                {currentPreset.suggestedModels.map((presetModel) => {
                  const selected = model === presetModel;
                  return (
                    <button
                      key={presetModel}
                      type="button"
                      disabled={disabled}
                      onClick={() => onModelChange(presetModel)}
                      className="font-mono-tech min-h-[30px] rounded border px-2 py-0.5 text-[11px]"
                      style={{
                        borderColor: selected ? "var(--accent)" : "var(--border-subtle)",
                        backgroundColor: selected ? "var(--accent-soft)" : "var(--bg-surface)",
                        color: "var(--ink-primary)",
                      }}
                    >
                      {presetModel}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="border-t pt-4" style={{ borderColor: "var(--border-subtle)" }}>
              <label
                htmlFor="system-prompt-input"
                className="mb-1.5 block text-xs font-semibold"
                style={{ color: "var(--ink-secondary)" }}
              >
                System Prompt (optional)
              </label>
              <textarea
                id="system-prompt-input"
                rows={4}
                value={systemPrompt}
                disabled={disabled}
                onChange={(e) => onSystemPromptChange(e.target.value)}
                placeholder="e.g. Respond concisely with production Python examples."
                className="w-full rounded-md border px-3 py-2 text-xs leading-relaxed"
                style={{
                  backgroundColor: "var(--bg-surface)",
                  borderColor: "var(--border-strong)",
                  color: "var(--ink-primary)",
                }}
              />
            </div>

            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <label
                  htmlFor="temperature-input"
                  className="text-xs font-semibold"
                  style={{ color: "var(--ink-secondary)" }}
                >
                  Temperature (0.0 to 2.0)
                </label>
                {temperature.trim() !== "" && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onTemperatureChange("")}
                    className="text-[11px] font-medium underline"
                    style={{ color: "var(--ink-secondary)" }}
                  >
                    Reset
                  </button>
                )}
              </div>
              <div className="flex items-center gap-2.5">
                <input
                  aria-label="Temperature slider"
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  disabled={disabled}
                  value={temperature.trim() === "" ? "0.7" : temperature}
                  onChange={(e) => onTemperatureChange(e.target.value)}
                  className="flex-1 accent-[var(--accent)]"
                />
                <input
                  id="temperature-input"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  value={temperature}
                  disabled={disabled}
                  onChange={(e) => onTemperatureChange(e.target.value)}
                  placeholder="Auto"
                  className="font-mono-tech min-h-[40px] w-20 rounded-md border px-2.5 py-1.5 text-xs"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border-strong)",
                    color: "var(--ink-primary)",
                  }}
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="max-tokens-input"
                className="mb-1.5 block text-xs font-semibold"
                style={{ color: "var(--ink-secondary)" }}
              >
                Max Output Tokens
              </label>
              <input
                id="max-tokens-input"
                type="number"
                min="1"
                max="65536"
                step="64"
                value={maxTokens}
                disabled={disabled}
                onChange={(e) => onMaxTokensChange(e.target.value)}
                placeholder="1024 (provider default)"
                className="font-mono-tech min-h-[44px] w-full rounded-md border px-3 py-2 text-xs"
                style={{
                  backgroundColor: "var(--bg-surface)",
                  borderColor: "var(--border-strong)",
                  color: "var(--ink-primary)",
                }}
              />
            </div>
          </div>
        )}
      </div>
    </aside>
  );

  return (
    <>
      <div className="hidden w-80 shrink-0 xl:block">{panelBody}</div>
      <div
        className="fixed inset-0 z-40 flex justify-end xl:hidden"
        role="dialog"
        aria-modal="true"
        aria-label="Inspector and configuration panel"
      >
        <button
          type="button"
          aria-label="Dismiss inspector drawer"
          onClick={onClose}
          className="flex-1 bg-black/45"
        />
        <div className="w-84 max-w-[90vw]">{panelBody}</div>
      </div>
    </>
  );
}
