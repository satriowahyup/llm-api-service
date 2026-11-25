# llm-api-service

[![CI](https://github.com/satriowahyup/llm-api-service/actions/workflows/ci.yml/badge.svg)](https://github.com/satriowahyup/llm-api-service/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-%3E%3D3.12%20(3.12%20%7C%203.14%20tested)-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy%202.0-SQLite%20%7C%20PostgreSQL%2017-336791)
![Ruff](https://img.shields.io/badge/lint-Ruff-261230)

Asynchronous multi-provider LLM REST and Server-Sent Events (SSE) API service built with **FastAPI**, **SQLAlchemy 2.0 Async**, **Alembic**, and **uv**.

---

## Key Capabilities

- **Multi-Provider Adapter Pattern (3 Distinct Wire Protocols)**:
  - **Google Gemini (Default)**: `google-genai` async Interactions API (`gemini-4-hydrogen` default, stateless `store=False` history).
  - **Anthropic Claude**: Messages API (`POST /v1/messages`) via `httpx.AsyncClient` with SSE parsing (`message_start`, `content_block_delta`, `message_delta`, `message_stop`) and HTTP `529 Overloaded` retry support.
  - **OpenAI-Compatible**: `/chat/completions` adapter supporting **OpenAI**, **DeepSeek**, **Groq**, and local **Ollama** via configurable `base_url`.
- **3-Tier Dynamic Provider & Model Resolution**:
  - Resolves `(provider, model)` in strict precedence: `request override > session context > global default (gemini / gemini-4-hydrogen)`.
  - **Mid-Session Switch Safeguard**: Switching providers inside an existing `session_id` without passing `model` automatically resolves to the new provider's default model while preserving full conversation history.
- **Dual-Backend Persistence (Twelve-Factor Backing Service)**:
  - **Local Dev / Fast CI**: Async SQLite (`aiosqlite` with `WAL`, `foreign_keys=ON`, `busy_timeout=5000`).
  - **Production**: Async PostgreSQL (`asyncpg` with connection pooling) + versioned **Alembic** async migrations.
- **Observability & Resilience**:
  - Tracks **TTFT (`ttft_ms`)**, end-to-end **latency (`latency_ms`)**, **throughput (`tokens_per_sec`)**, token usage (`input`/`output`/`total`), and **estimated USD cost** per message and aggregated per session.
  - Async **exponential backoff with jitter** and `Retry-After` handling for transient failures (`429`, `500`, `502`, `503`, `504`, `529`, network timeouts), with fail-fast on `400`/`401`/`403`/`422`.
  - Structured JSON logs with `X-Request-ID` correlation and automatic secret redaction.

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
   └── SQLAlchemy 2.0 Async + Alembic (SQLite default / PostgreSQL 17 production)
```

---

## Engineering & Architectural Decisions

1. **Three Wire Protocols + Local Stateless History**: Keeping conversation history in our own relational database (`store=False` on Gemini) makes sessions 100% provider-agnostic. A single conversation can start on Gemini, switch to Anthropic Claude on turn 2, and continue on local Ollama without vendor lock-in.
2. **Direct `httpx.AsyncClient` for Anthropic & OpenAI-Compatible Adapters**: Avoids heavy extra SDK layers, gives direct control over timeouts, headers, SSE framing, and HTTP `529` handling, and enables deterministic transport-level mocking via `httpx.MockTransport` in `pytest`.
3. **Dual-Backend via `DATABASE_URL` + Alembic**: SQLite (`aiosqlite`) gives zero-setup local development and fast unit/integration tests, while PostgreSQL (`asyncpg` + connection pool) handles concurrent writers and horizontal multi-worker scaling in production without changing application code.
4. **Short-Lived DB Transactions**: `ChatService` validates the session/provider, persists the user message, and closes the DB transaction *before* awaiting the upstream LLM response or SSE stream. This prevents SQLite write locks and PostgreSQL pool exhaustion under concurrent streaming load.
5. **Stream-Safe Retries**: Exponential backoff retries apply only *before* the first token is sent to the client. If an upstream failure happens mid-stream, the API emits an `event: error` frame and terminates cleanly instead of duplicating partial output.

---

## Prerequisites

- **Python**: `>= 3.12` (CI verified on Python `3.12` and `3.14`)
- **Package Manager**: [`uv`](https://docs.astral.sh/uv/)
- **Optional**: Docker & Docker Compose (for PostgreSQL 17 production stack) and/or [Ollama](https://ollama.com/) (for local inference)

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

Configure credentials and defaults in `.env` (see [`.env.example`](.env.example)):

| Provider | Env Key | Default Base URL | Default Model |
|---|---|---|---|
| `gemini` *(default)* | `GEMINI_API_KEY` | Managed by `google-genai` | `gemini-4-hydrogen` |
| `anthropic` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com` | `claude-sonnet-4-6` |
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` | `gpt-4o-mini` |
| `deepseek` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `groq` | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| `ollama` | *(not required)* | `http://localhost:11434/v1` | `llama3.2` |

---

## API Usage & Response Contracts

### Health Check
```bash
curl http://localhost:8000/health
```

### Non-Streaming Chat (`POST /v1/chat`)
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Explain asyncio.TaskGroup in 3 bullet points."
  }'
```

Example `200 OK` response:
```json
{
  "session_id": "3c7f8c2e-8a91-4d7d-9b34-61e0c4f8a102",
  "message_id": "a92b1e04-2d13-4c88-a5e1-09f34bc1e711",
  "provider": "gemini",
  "model": "gemini-4-hydrogen",
  "content": "...",
  "usage": {
    "input_tokens": 42,
    "output_tokens": 118,
    "total_tokens": 160,
    "estimated_cost_usd": 0.000948
  },
  "metrics": {
    "ttft_ms": null,
    "latency_ms": 1184.2,
    "tokens_per_sec": 99.65
  }
}
```

### Switch Provider Mid-Session (e.g., to Anthropic Claude or Local Ollama)
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<SESSION_ID_FROM_PREVIOUS_TURN>",
    "provider": "anthropic",
    "message": "Now show a concise Python 3.12+ example."
  }'
```

### Streaming Chat via SSE (`POST /v1/chat/stream`)
```bash
curl -N -X POST http://localhost:8000/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Compare SQLite WAL mode and PostgreSQL for async APIs.",
    "provider": "gemini"
  }'
```

Example SSE event stream:
```text
event: meta
data: {"session_id": "3c7f8c2e-...", "provider": "gemini", "model": "gemini-4-hydrogen"}

event: delta
data: {"text": "SQLite WAL mode allows "}

event: delta
data: {"text": "concurrent readers alongside a single writer..."}

event: done
data: {"session_id": "3c7f8c2e-...", "message_id": "a92b1e04-...", "provider": "gemini", "model": "gemini-4-hydrogen", "usage": {"input_tokens": 35, "output_tokens": 96, "total_tokens": 131, "estimated_cost_usd": 0.0007725}, "metrics": {"ttft_ms": 241.5, "latency_ms": 1320.8, "tokens_per_sec": 88.95}}
```

### List, Inspect & Delete Sessions
```bash
curl "http://localhost:8000/v1/sessions?limit=20&offset=0"
curl "http://localhost:8000/v1/sessions/<SESSION_ID>"
curl -X DELETE "http://localhost:8000/v1/sessions/<SESSION_ID>"
```

### Standardized Error Envelope
All domain, validation, and upstream provider errors return a consistent JSON envelope with `X-Request-ID` correlation:
```json
{
  "error": {
    "code": "provider_rate_limit",
    "message": "Anthropic rate limit exceeded: Too many requests",
    "request_id": "8e4f9b2c-12a4-4f6a-9d10-c1324f7c9b01"
  }
}
```

---

## Project Structure

```text
llm-api-service/
├── .github/workflows/ci.yml        # Python 3.12 & 3.14 SQLite matrix + PostgreSQL 17 CI job
├── alembic/                        # Async Alembic migrations (0001_initial_schema)
├── src/llm_api_service/
│   ├── api/                        # FastAPI routes, DI helpers, global error handlers
│   ├── core/                       # Exceptions, retry/backoff, metrics, pricing, JSON logging
│   ├── db/                         # Dialect-aware async engine, ORM models, repositories
│   ├── providers/                  # Gemini, Anthropic, OpenAI-compatible adapters & registry
│   ├── schemas/                    # Pydantic v2 request/response DTOs
│   ├── services/                   # ChatService (3-tier resolution, SSE, persistence)
│   ├── config.py                   # Pydantic Settings multi-provider & dual-DB config
│   └── main.py                     # FastAPI app factory, lifespan, middleware
├── tests/
│   ├── unit/                       # Pricing, metrics, retry, and mock adapter tests
│   └── integration/                # Health, chat, SSE stream, and session endpoint tests
├── Dockerfile                      # Multi-stage slim runtime (non-root + HEALTHCHECK)
├── docker-compose.yml              # PostgreSQL 17 + Alembic + FastAPI stack
└── pyproject.toml                  # Dependencies, Ruff, and pytest-asyncio configuration
```

---

## Testing, Linting & CI Quality Gates

```bash
# Run full unit + integration test suite with coverage (>= 85% gate)
uv run pytest -v --cov=llm_api_service --cov-report=term-missing --cov-fail-under=85

# Lint & format verification
uv run ruff check .
uv run ruff format --check .

# Run integration tests against PostgreSQL
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/llm_api_service_test" \
  uv run pytest -v tests/integration
```

GitHub Actions CI (`.github/workflows/ci.yml`) runs two automated verification jobs on every push and pull request:
1. **SQLite Matrix (`Python 3.12` & `Python 3.14`)**: `uv sync --locked`, `ruff check`, `ruff format --check`, `alembic upgrade head`, and `pytest` with `--cov-fail-under=85`.
2. **PostgreSQL 17 Integration**: spins up a `postgres:17-alpine` service container, runs `alembic upgrade head`, and executes `pytest tests/integration` against live PostgreSQL.

> **Windows Smart App Control note:** If Windows blocks unsigned `.venv` `.exe` shims or compiled SQLAlchemy Cython `.pyd` extensions, set `$env:DISABLE_SQLALCHEMY_CEXT_RUNTIME="1"` and run via your signed system Python: `uv run --python-preference only-system python -m pytest` (and `python -m alembic`, `python -m uvicorn`).

---

## Roadmap

- [x] **Backend Core (Phases 0–5)**: FastAPI async REST & SSE API, 3 LLM wire protocols (Gemini, Anthropic Claude, OpenAI-compatible/Ollama), Dual-Backend SQLite + PostgreSQL 17 + Alembic migrations, TTFT/throughput/USD cost observability, exponential backoff retries, automated mock test suite, CI matrix, and Docker stack.
- [ ] **Phase 6 (Planned)**: Interactive Frontend Workbench (`React + TypeScript + Vite + Tailwind CSS`) served via Nginx reverse proxy (`proxy_buffering off` for SSE).
