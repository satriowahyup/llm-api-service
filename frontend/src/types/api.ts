export type ProviderName =
  | "gemini"
  | "anthropic"
  | "openai"
  | "deepseek"
  | "groq"
  | "ollama";

export interface ProviderPreset {
  id: ProviderName;
  label: string;
  defaultModel: string;
  suggestedModels: string[];
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "gemini",
    label: "Google Gemini",
    defaultModel: "gemini-4-hydrogen",
    suggestedModels: ["gemini-4-hydrogen", "gemini-3.5-flash-lite", "gemini-4-argon", "gemini-4-neon"],
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    defaultModel: "claude-sonnet-4-6",
    suggestedModels: ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6"],
  },
  {
    id: "openai",
    label: "OpenAI",
    defaultModel: "gpt-4o-mini",
    suggestedModels: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    defaultModel: "deepseek-chat",
    suggestedModels: ["deepseek-chat", "deepseek-reasoner"],
  },
  {
    id: "groq",
    label: "Groq",
    defaultModel: "llama-3.3-70b-versatile",
    suggestedModels: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
  },
  {
    id: "ollama",
    label: "Ollama (Local)",
    defaultModel: "llama3.2",
    suggestedModels: ["llama3.2", "qwen2.5:7b", "mistral"],
  },
];

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  database_dialect: string;
  default_provider: ProviderName;
  default_model: string;
}

export interface ChatRequest {
  session_id?: string | null;
  message: string;
  system_prompt?: string | null;
  provider?: ProviderName | null;
  model?: string | null;
  temperature?: number | null;
  max_tokens?: number | null;
}

export interface UsageStats {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

export interface LatencyMetrics {
  ttft_ms: number | null;
  latency_ms: number;
  tokens_per_sec: number | null;
}

export interface MessageItem {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  provider: string | null;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  ttft_ms: number | null;
  latency_ms: number | null;
  tokens_per_sec: number | null;
  created_at: string;
}

export interface SessionSummary {
  id: string;
  title: string | null;
  provider: string;
  model: string;
  system_prompt: string | null;
  message_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
  created_at: string;
  updated_at: string;
}

export interface SessionListResponse {
  items: SessionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface SessionDetailResponse extends SessionSummary {
  messages: MessageItem[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id?: string | null;
}

export interface SseMetaEvent {
  session_id: string;
  provider: ProviderName;
  model: string;
}

export interface SseDeltaEvent {
  text: string;
}

export interface SseDoneEvent {
  session_id: string;
  message_id: string;
  provider: ProviderName;
  model: string;
  usage: UsageStats;
  metrics: LatencyMetrics;
}

export interface SseErrorEvent {
  code: string;
  message: string;
  request_id?: string | null;
}
