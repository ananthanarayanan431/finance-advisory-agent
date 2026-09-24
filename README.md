# Market Research Agent

**AI-powered market and financial research, from objective to report.**

Ask a business question in plain English, such as *"How is the EV charging market in India shaping up, and who are the key players?"* or *"Compare NVIDIA's and AMD's last four quarters of data-center revenue."* A team of AI research agents then:

1. makes sure it understands the question, and asks you a follow-up if it doesn't,
2. turns the question into a structured research plan,
3. splits the plan into sub-topics and researches them **in parallel** across the web and SEC filings (and your own documents, if you add them),
4. writes a single, cited research report that you can read in the app or download as a PDF.

You can watch the progress live while the agents work: which topics are being researched and which sources were found.

---

## Table of contents

- [How it works](#how-it-works)
- [Features](#features)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [API overview](#api-overview)
- [Observability](#observability)
- [Development](#development)
- [Further reading](#further-reading)

---

## How it works

The agent is a single [LangGraph](https://github.com/langchain-ai/langgraph) graph that contains three nested levels of agents:

```
                 ┌──────────────┐
  Your question ─▶   Clarify     │── unclear? ──▶ asks you a follow-up question
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │Research brief│   turns the question into a structured plan
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │  Supervisor  │   lead researcher: splits the plan into topics
                 └──┬────┬────┬─┘
          ┌─────────┘    │    └─────────┐      (runs in parallel, capped by config)
          ▼              ▼              ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐
   │ Researcher │ │ Researcher │ │ Researcher │   each one loops: think → search → read
   │  (topic 1) │ │  (topic 2) │ │  (topic 3) │   then compresses what it found
   └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
         └──────────────┼──────────────┘
                        ▼
                 ┌──────────────┐
                 │ Final report │   writer merges all findings into a cited report
                 └──────────────┘
```

| Stage | What it does |
| --- | --- |
| **Clarify** | Checks whether the request is specific enough. If it isn't, the run stops and returns a clarifying question. |
| **Research brief** | Rewrites the conversation into a precise research brief. |
| **Supervisor** | Plans the research, delegates topics to researcher sub-agents (`ConductResearch`), reviews what comes back, and decides when there is enough (`ResearchComplete`). |
| **Researchers** | One ReAct loop per topic. Each researcher calls search tools, reflects with a `think_tool`, and finally compresses its findings into notes with sources. |
| **Final report** | A writer combines every researcher's notes into one structured, cited Markdown report. |

### Research sources

| Source | Used for |
| --- | --- |
| **Tavily** and **Exa** | General web search and content extraction |
| **SEC EDGAR** | 10-K / 10-Q / 8-K filings, financial statements, Form 4 insider trades, 13F institutional holdings |
| **Context Hub** | Files and URLs you upload yourself, searched through embeddings. A turn opts in per request. |
| NewsAPI, Reddit | Clients are implemented (`webtools/`) but not yet wired into the agent |

### What happens when you send a message

```
Browser ──POST /v1/chat/stream──▶ FastAPI ──enqueue──▶ Celery worker ──runs──▶ LangGraph agent
   ▲                                 │                      │
   └──────── Server-Sent Events ◀────┴──── Redis pub/sub ◀──┘  (progress, sources, report)
```

The API never runs research itself. It queues the turn and relays events. A **Celery worker** executes the graph and publishes every progress event to Redis, and the API streams those events to the browser over SSE. Conversation state is checkpointed in **Postgres**, so sessions survive restarts and you can reopen a running session and pick up its live status.

---

## Features

- **Deep, multi-agent research.** A supervisor fans work out to parallel researcher sub-agents.
- **Clarifying questions.** The agent asks before researching a vague request instead of guessing.
- **Live progress streaming.** Topics, sources and status appear in real time over SSE.
- **Cited reports.** Every report is written from the sources the researchers found, and can be exported as a PDF.
- **Financial data built in.** SEC EDGAR filings, financial statements, insider trades and institutional holdings.
- **Context Hub.** Upload your own files or URLs and let the agent research over them.
- **Session history.** A sidebar lists past sessions, which you can rename, pin, delete or reopen.
- **Any LLM provider.** OpenAI-compatible gateways (OpenRouter, Together, Groq, vLLM), native Anthropic, or native Google Gemini. Switching is a `.env` change, not a code change.
- **Bounded cost.** Three independent caps limit supervisor turns, parallel researchers, and tool calls per researcher.
- **Resilient.** HTTP and LLM retries, and a circuit breaker for each search provider.
- **Observable.** OpenTelemetry traces and metrics from the backend and the browser, with SigNoz dashboards and alerts committed to the repo.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| **Agent** | LangGraph, LangChain (`init_chat_model`), Python 3.12 |
| **API** | FastAPI, Server-Sent Events |
| **Background jobs** | Celery, with Redis as broker and event pub/sub |
| **Storage** | Postgres (LangGraph checkpointer, sessions, audit; Alembic migrations), MinIO (Context Hub files) |
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui |
| **Observability** | OpenTelemetry, SigNoz (deployed with `foundryctl` from `casting.yaml`) |
| **Quality** | pytest, ruff, mypy (strict), ESLint, GitHub Actions CI, Dependabot |

---

## Repository layout

```
.
├── backend/        Python package `agentdrops`: FastAPI API, LangGraph agent, Celery worker
│   └── src/agentdrops/
│       ├── main.py          app lifespan, CORS, error handlers, /health
│       ├── api/v1/          thin HTTP routers (chat, sessions, research, contexthub, suggestions)
│       ├── service/         business logic, one class per route group
│       ├── agents/          the LangGraph graph: scope/, supervisor/, research/, writer/,
│       │                    prompts/, edgar/, contexthub/, llm.py, state.py
│       ├── webtools/        Tavily / Exa / NewsAPI / Reddit clients
│       ├── worker/          Celery app and tasks that run research turns
│       ├── jobs/            Redis pub/sub event relay (worker → API)
│       ├── repository/      Postgres-backed stores
│       ├── db/              SQLAlchemy models and Alembic migrations
│       ├── resilience/      retry policies and circuit breakers
│       └── observability/   tracing, metrics, logging
├── frontend/       Next.js chat UI: sidebar, chat panel, research drawer, Context Hub panel
├── signoz/         SigNoz dashboards, alerts and a committed docker-compose snapshot
├── docs/           design spec and per-feature implementation plans
├── casting.yaml    Foundry definition of the SigNoz observability stack
└── .github/        CI workflows (backend, frontend) and Dependabot config
```

---

## Getting started

### Prerequisites

- Python **3.12+**
- Node.js **22+** and npm (the version CI uses)
- Docker (for Postgres, Redis and MinIO)
- An LLM API key (for example OpenRouter, Anthropic or Google) and a Tavily and/or Exa key

### 1. Backend

```bash
cd backend
make install        # create .venv and install the package with dev extras
make env            # copy .env.example → .env, then fill in your keys (see Configuration)
make infra-up       # start postgres :5432, redis :6379, minio :9000 (console :9001)
make run            # apply DB migrations, then start the API on http://localhost:8001
```

In a **second terminal**, start the worker:

```bash
cd backend
make worker         # Celery worker that actually runs the research
```

> **The worker must be running.** The API only queues research turns, and nothing completes without a worker.

API docs are at <http://localhost:8001/docs>. Run `make doctor` to check your local setup.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev         # http://localhost:3000
```

Open <http://localhost:3000> and ask a question.

The frontend expects the backend on `http://localhost:8001`. Set `NEXT_PUBLIC_API_BASE_URL` to point it somewhere else. Backend CORS allows `http://localhost:3000` only.

### 3. Observability (optional)

```bash
cd backend
make signoz-up      # start SigNoz (UI :8080, OTLP :4317/:4318, MCP :8000)
make signoz-open
```

If you don't run SigNoz, set `OTEL_ENABLED=false` in `backend/.env`.

### Ports at a glance

| Service | Port |
| --- | --- |
| Frontend | 3000 |
| Backend API | 8001 (8000 is taken by SigNoz's MCP server) |
| Postgres | 5432 |
| Redis | 6379 |
| MinIO / console | 9000 / 9001 |
| SigNoz UI | 8080 |
| OTLP gRPC / HTTP | 4317 / 4318 |

---

## Configuration

All backend settings live in `backend/.env`. See [`backend/.env.example`](backend/.env.example) for the annotated list. The backend **fails fast on startup** if a required key is missing.

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER` | `openai` (any OpenAI-compatible gateway, the default), `anthropic` or `google_genai` |
| `LLM_API_KEY` | Key for that provider or gateway |
| `LLM_BASE_URL` | Gateway URL, used only with `openai` (default: OpenRouter) |
| `RESEARCH_MODEL` | Model id, for example `anthropic/claude-sonnet-5` on OpenRouter or `claude-sonnet-5` on native Anthropic |
| `TAVILY_API_KEY`, `EXA_API_KEY` | Web search |
| `EDGAR_IDENTITY` | `"Your Name you@example.com"`. SEC EDGAR is free, but requires requesters to identify themselves. |
| `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL` | Embeddings for Context Hub (any OpenAI-compatible `/embeddings` endpoint) |
| `DATABASE_URL`, `REDIS_URL`, `MINIO_*` | Infra. The defaults match `docker-compose.yml`. |
| `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT` | Tracing export to SigNoz |

**Cost caps** (in `Settings`):

| Setting | Default | Limits |
| --- | --- | --- |
| `max_researcher_iterations` | 6 | Supervisor planning turns |
| `max_concurrent_researchers` | 3 | Researchers running in parallel |
| `max_tool_call_iterations` | 5 | Tool-call rounds per researcher |

---

## API overview

All routes are versioned under `/v1`. Full interactive docs are at `/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe |
| `POST` | `/v1/chat` | Queue a research turn |
| `POST` | `/v1/chat/stream` | Queue a turn and stream its progress, sources and report (SSE) |
| `GET` | `/v1/research/sessions` | List sessions |
| `PATCH` / `DELETE` | `/v1/research/sessions/{thread_id}` | Rename / pin, or delete a session |
| `GET` | `/v1/research/{thread_id}` | Status: `queued`, `clarifying`, `running`, `done` or `failed` |
| `GET` | `/v1/research/{thread_id}/report` | The final report |
| `POST` | `/v1/contexthub/documents` / `/v1/contexthub/urls` | Add a file or URL to Context Hub |
| `GET` / `DELETE` | `/v1/contexthub/documents[/{id}]` | List or delete Context Hub documents |
| `GET` | `/v1/suggestions/starter` | Example prompts for the empty chat screen |

Example request:

```bash
curl -N -X POST http://localhost:8001/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Competitive landscape of the US plant-based meat market", "use_context_hub": false}'
```

Pass the returned `thread_id` back in `thread_id` to continue the same conversation, for example to answer a clarifying question.

---

## Observability

The backend and the browser both emit OpenTelemetry traces. The committed SigNoz assets in [`signoz/`](signoz/README.md) include:

- **A dashboard** showing tool-call throughput, latency and failures per tool, research-turn P95 duration, turns by outcome, and average tokens per turn.
- **Alerts** for a high tool-call failure rate and slow research turns.

---

## Development

```bash
# backend/
make check          # ruff + mypy --strict + pytest (what CI runs)
make test           # tests only; no network access, LLMs and HTTP are faked
make test-file FILE=tests/unit/agents/supervisor/test_graph.py
make db-revision MSG="add foo"   # new Alembic migration

# frontend/
make check          # eslint + tsc + next build (what CI runs)
```

GitHub Actions runs the backend and frontend pipelines on every PR to `main`. Each pipeline runs only when its own directory changes.

---

## Further reading

- [`backend/README.md`](backend/README.md): backend setup, configuration and API in depth
- [`signoz/README.md`](signoz/README.md): observability stack, dashboards and alerts
- [`docs/superpowers/specs/2026-07-12-deepresearch-market-agent-design.md`](docs/superpowers/specs/2026-07-12-deepresearch-market-agent-design.md): the authoritative design document
- [`CLAUDE.md`](CLAUDE.md): architecture notes and invariants for contributors
