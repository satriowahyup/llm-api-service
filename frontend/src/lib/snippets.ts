import type { MessageItem, ProviderName, SessionSummary } from "../types/api";

export interface SnippetParams {
  sessionId: string | null;
  provider: ProviderName;
  model: string;
  systemPrompt: string;
  temperature: string;
  maxTokens: string;
  promptText: string;
}

function buildRequestBody(params: SnippetParams): Record<string, unknown> {
  const body: Record<string, unknown> = {
    message: params.promptText.trim() || "Compare SQLite WAL mode and PostgreSQL in 3 points.",
    provider: params.provider,
  };
  if (params.model.trim()) {
    body.model = params.model.trim();
  }
  if (params.sessionId) {
    body.session_id = params.sessionId;
  }
  if (params.systemPrompt.trim()) {
    body.system_prompt = params.systemPrompt.trim();
  }
  const temp = Number(params.temperature);
  if (params.temperature.trim() !== "" && !Number.isNaN(temp)) {
    body.temperature = temp;
  }
  const maxTok = Number(params.maxTokens);
  if (params.maxTokens.trim() !== "" && !Number.isNaN(maxTok)) {
    body.max_tokens = maxTok;
  }
  return body;
}

export function buildCurlSnippet(params: SnippetParams): string {
  const origin =
    typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000";
  const bodyJson = JSON.stringify(buildRequestBody(params), null, 2);
  return [
    `curl -N -X POST ${origin}/v1/chat/stream \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '${bodyJson}'`,
  ].join("\n");
}

export function buildPythonSnippet(params: SnippetParams): string {
  const origin =
    typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000";
  const payload = JSON.stringify(buildRequestBody(params), null, 4)
    .replace(/\btrue\b/g, "True")
    .replace(/\bfalse\b/g, "False")
    .replace(/\bnull\b/g, "None");

  return [
    "import httpx",
    "",
    `payload = ${payload}`,
    "",
    `with httpx.stream("POST", "${origin}/v1/chat/stream", json=payload, timeout=60.0) as res:`,
    "    for line in res.iter_lines():",
    '        if line.startswith("data:"):',
    "            print(line)",
  ].join("\n");
}

export function downloadTextFile(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function formatSessionAsMarkdown(
  session: SessionSummary | null,
  messages: MessageItem[],
): string {
  const lines: string[] = [
    `# ${session?.title || "LLM API Service Session"}`,
    "",
    `- **Session ID**: \`${session?.id || "unsaved"}\``,
    `- **Active Provider / Model**: \`${session?.provider || "n/a"} / ${session?.model || "n/a"}\``,
    `- **Total Tokens**: ${session?.total_tokens ?? 0}`,
    `- **Total Cost (USD)**: $${(session?.total_cost_usd ?? 0).toFixed(6)}`,
    "",
    "---",
    "",
  ];

  for (const msg of messages) {
    const header =
      msg.role === "user"
        ? "## User"
        : `## Assistant (${msg.provider || "unknown"} / ${msg.model || "unknown"})`;
    lines.push(header, "", msg.content, "");
    if (msg.role === "assistant" && (msg.latency_ms !== null || msg.total_tokens > 0)) {
      lines.push(
        `> TTFT: ${msg.ttft_ms ?? "n/a"} ms | Latency: ${msg.latency_ms ?? "n/a"} ms | Speed: ${msg.tokens_per_sec ?? "n/a"} tok/s | Tokens: ${msg.input_tokens} in / ${msg.output_tokens} out | Cost: $${msg.estimated_cost_usd.toFixed(6)}`,
        "",
      );
    }
  }

  return lines.join("\n");
}
