import type {
  ApiErrorBody,
  ChatRequest,
  HealthResponse,
  SessionDetailResponse,
  SessionListResponse,
  SseDeltaEvent,
  SseDoneEvent,
  SseErrorEvent,
  SseMetaEvent,
} from "../types/api";

export class ApiClientError extends Error {
  status: number;
  code: string;
  requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null = null) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

async function parseErrorResponse(response: Response): Promise<ApiClientError> {
  try {
    const data = (await response.json()) as { error?: ApiErrorBody };
    if (data?.error) {
      return new ApiClientError(
        response.status,
        data.error.code || "api_error",
        data.error.message || `Request failed with HTTP ${response.status}`,
        data.error.request_id ?? response.headers.get("X-Request-ID"),
      );
    }
  } catch {
    // Fallback when body is not JSON
  }
  return new ApiClientError(
    response.status,
    "http_error",
    `Request failed with HTTP ${response.status}`,
    response.headers.get("X-Request-ID"),
  );
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const res = await fetch("/health", { signal });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return (await res.json()) as HealthResponse;
}

export async function listSessions(
  limit = 50,
  offset = 0,
  signal?: AbortSignal,
): Promise<SessionListResponse> {
  const res = await fetch(`/v1/sessions?limit=${limit}&offset=${offset}`, { signal });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return (await res.json()) as SessionListResponse;
}

export async function getSessionDetail(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionDetailResponse> {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}`, { signal });
  if (!res.ok) {
    throw await parseErrorResponse(res);
  }
  return (await res.json()) as SessionDetailResponse;
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204) {
    throw await parseErrorResponse(res);
  }
}

export interface StreamChatCallbacks {
  onHeaders?: (headers: { requestId: string | null }) => void;
  onMeta?: (event: SseMetaEvent) => void;
  onDelta?: (event: SseDeltaEvent) => void;
  onDone?: (event: SseDoneEvent) => void;
  onError?: (event: SseErrorEvent) => void;
}

export async function streamChat(
  payload: ChatRequest,
  callbacks: StreamChatCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/v1/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  if (!res.ok) {
    throw await parseErrorResponse(res);
  }

  if (!res.body) {
    throw new ApiClientError(500, "stream_unavailable", "Response body stream is not available.");
  }

  callbacks.onHeaders?.({
    requestId: res.headers.get("X-Request-ID"),
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const processBlock = (rawBlock: string) => {
    const trimmed = rawBlock.trim();
    if (!trimmed) return;

    let eventName = "message";
    const dataLines: string[] = [];

    for (const line of trimmed.split(/\r?\n/)) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }

    if (dataLines.length === 0) return;
    const rawData = dataLines.join("\n");

    let parsed: unknown;
    try {
      parsed = JSON.parse(rawData);
    } catch {
      return;
    }

    if (eventName === "meta") {
      callbacks.onMeta?.(parsed as SseMetaEvent);
    } else if (eventName === "delta") {
      callbacks.onDelta?.(parsed as SseDeltaEvent);
    } else if (eventName === "done") {
      callbacks.onDone?.(parsed as SseDoneEvent);
    } else if (eventName === "error") {
      callbacks.onError?.(parsed as SseErrorEvent);
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        processBlock(block);
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      processBlock(buffer);
    }
  } finally {
    reader.releaseLock();
  }
}
