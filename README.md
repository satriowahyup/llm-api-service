# llm-api-service

Production-grade, asynchronous multi-provider LLM REST & Server-Sent Events (SSE) API built with **FastAPI**, **SQLAlchemy 2.0 Async**, **Alembic**, and **uv**.

## Key Capabilities

- **Multi-Provider Adapter Pattern (3 Distinct Wire Protocols)**:
  - **Google Gemini (Default)**: `google-genai` async Interactions API (`gemini-4-hydrogen` default, stateless `store=False` history).
  - **Anthropic Claude**: Messages API (`POST /v1/messages`) via `httpx.AsyncClient` with SSE parsing and HTTP `529 Overloaded` retry support.
  - **OpenAI-Compatible**: `/chat/completions` adapter supporting **OpenAI**, **DeepSeek**, **Groq**, and local **Ollama** via configurable `base_url`.
- **3-Tier Dynamic Provider & Model Resolution**:
  - Defaults globally to `gemini` (`gemini-4-hydrogen`), overridable per request or via `.env`.
  - **Mid-Session Switch Safeguard**: Switching providers inside an existing `session_id` without passing `model` automatically resolves to the new provider's default model while carrying over full conversation history.
- **Dual-Backend Persistence (Twelve-Factor Backing Service)**:
  - **Local Dev / Fast CI**: Async SQLite (`aiosqlite` with `WAL`, `foreign_keys=ON`, `busy_timeout=5000`).
  - **Production**: Async PostgreSQL (`asyncpg` with connection pooling) + versioned **Alembic** async migrations.
- **Observability & Resilience**:
  - Tracks **TTFT (`ttft_ms`)**, end-to-end **latency (`latency_ms`)**, **throughput (`tokens_per_sec`)**, token usage (`input`/`output`/`total`), and **estimated USD cost** per message and aggregated per session.
  - Async **exponential backoff with jitter** and `Retry-After` handling for transient errors (`429`, `500`, `502`, `503`, `504`, `529`, timeouts) with fail-fast on `400`/`401`/`403`/`422`.
  - Structured JSON logs with `X-Request-ID` correlation and secret redaction.

---

## Architecture Overview

```text
Client (curl / SPA / SDK)
   │
   ▼
FastAPI + Uvicorn (X-Request-ID, X-Latency-Ms, Global Error Envelope)
   ├── GET    /health
   ├── POST   /v1/chat           (JSON completion)
   ├── POST   /v1/chat/stream    (SSE: meta -> delta -> done / error)
   ├── GET    /v1/sessions       (Paginated list + aggregated tokens & USD cost)
   ├── GET    /v1/sessions/{id}  (Session detail + chronological messages)
   └── DELETE /v1/sessions/{id}  (Cascade delete)
   │
   ▼
ChatService (3-tier provider resolution, short-lived DB transactions, metrics, cost engine)
   ├── GeminiProvider            (google-genai Interactions API)
   ├── AnthropicProvider         (Anthropic Messages API via httpx)
   ├── OpenAICompatibleProvider  (OpenAI / DeepSeek / Groq / Ollama via httpx)
   └── SQLAlchemy 2.0 Async + Alembic (SQLite default / PostgreSQL production)
```

---

## Quickstart

### 1. Local Development (SQLite, Zero DB Setup)

```bash
cp .env.example .env
# Add at least GEMINI_API_KEY (or another provider key / local Ollama)

uv sync
uv run alembic upgrade head
uv run uvicorn llm_api_service.main:app --reload
```

Interactive OpenAPI docs are available at `http://localhost:8000/docs`.

### 2. Production Stack (Docker Compose + PostgreSQL 17)

```bash
cp .env.example .env
# Set your provider API keys in .env

docker compose up --build
```

The API container automatically runs `alembic upgrade head` against PostgreSQL 17 before starting Uvicorn on port `8000`.

---

## Multi-Provider Configuration

Configure credentials in `.env` (see [`.env.example`](.env.example)):

| Provider | Env Key | Default Base URL | Default Model |
|---|---|---|---|
| `gemini` *(default)* | `GEMINI_API_KEY` | Managed by `google-genai` | `gemini-4-hydrogen` |
| `anthropic` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com` | `claude-sonnet-4-6` |
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` | `gpt-4o-mini` |
| `deepseek` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `groq` | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| `ollama` | *(not required)* | `http://localhost:11434/v1` | `llama3.2` |

---

## API Usage Examples

### Health Check
```bash
curl http://localhost:8000/health
```

### Non-Streaming Chat (Default Gemini)
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Explain asyncio.TaskGroup in 3 bullet points."
  }'
```

### Switch Provider Mid-Session (e.g., to Anthropic Claude or Local Ollama)
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<SESSION_ID_FROM_PREVIOUS_TURN>",
    "provider": "anthropic",
    "message": "Now show a concise Python 3.14 example."
  }'
```

### Streaming Chat via SSE
```bash
curl -N -X POST http://localhost:8000/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Compare SQLite WAL mode and PostgreSQL for async APIs.",
    "provider": "gemini"
  }'
```

### List & Inspect Sessions
```bash
curl "http://localhost:8000/v1/sessions?limit=20&offset=0"
curl "http://localhost:8000/v1/sessions/<SESSION_ID>"
curl -X DELETE "http://localhost:8000/v1/sessions/<SESSION_ID>"
```

---

## Testing, Linting & Quality Gates

```bash
# Run full unit + integration test suite with coverage
uv run pytest -v --cov=llm_api_service --cov-report=term-missing

# Lint & format verification
uv run ruff check .
uv run ruff format --check .

# Run integration tests against PostgreSQL
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/llm_api_service_test" \
  uv run pytest -v tests/integration
```

> **Windows Smart App Control note:** If Windows blocks unsigned venv `.exe` shims, use your signed system Python with `uv run --python-preference only-system python -m pytest` (and `python -m alembic`, `python -m uvicorn`).
