# Agentdrops — Market Research Agent Backend

A LangGraph deep-research agent (clarify → brief → supervisor → parallel researchers → writer)
served by FastAPI. Chat turns run in a Celery worker, and their progress streams back to the
client over SSE through Redis pub/sub.

```
AgentState:      clarify_with_user → write_research_brief → supervisor → final_report_generation
SupervisorState:   supervisor ⇄ supervisor_tools        (fans research topics out concurrently)
ResearcherState:     llm_call ⇄ tool_node → compress_research   (one ReAct loop per topic)
```

Researcher tools: Tavily and Exa web search, SEC EDGAR filings, `think_tool`, and Context Hub
retrieval when a turn opts in.

## Quick start

Requires Python ≥ 3.12 and Docker. Every step has a `make` target (`make help` lists them all):

```bash
cd backend
make install        # creates .venv, pip install -e ".[dev]" (includes anthropic/google_genai SDKs)
make env            # copies .env.example → .env; then fill in the keys below
make infra-up       # postgres 5432, redis 6379, minio 9000 (console 9001)
make run            # applies migrations, then uvicorn --reload on :8001
make worker         # in a second terminal: Celery worker that executes chat turns
```

**Keep `make worker` running.** The API only enqueues turns, and no turn completes without a worker.
The port is 8001, not 8000, because SigNoz's MCP server uses 8000. The frontend's CORS is
pinned to `http://localhost:3000`.

`make doctor` sanity-checks the local environment.

## Configuration (`.env`)

`Settings` (`src/agentdrops/config/settings.py`) fails fast if a required key is missing. See
`.env.example` for the full annotated list.

### LLM

The chat model is provider-agnostic. Every node builds it through `agents/llm.py::build_llm`,
so switching providers only means editing `.env`, never the code.

- `LLM_PROVIDER` — `openai` (default; any OpenAI-wire gateway such as OpenRouter, Together, Groq
  or vLLM), `anthropic` (native), or `google_genai` (native).
- `LLM_API_KEY` — key for the chosen provider or gateway.
- `LLM_BASE_URL` — gateway URL. Used only when `LLM_PROVIDER=openai` (default: OpenRouter).
- `RESEARCH_MODEL` — model id. Its format depends on the provider, for example
  `anthropic/claude-sonnet-5` on OpenRouter or `claude-sonnet-5` on native Anthropic.

### Data sources

- `TAVILY_API_KEY`, `EXA_API_KEY` — web search used by the researchers.
- `NEWSAPI_KEY`, `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — NewsAPI and Reddit tools, built
  in `webtools/registry.py` but not yet wired into the graph.
- `EDGAR_IDENTITY` — `"Name email@domain"`. SEC EDGAR is free and unauthenticated, but its
  fair-access policy requires every request to identify the requester. The EDGAR tool covers
  10-K/10-Q/8-K filings, financial statements, Form 4 insider trades and 13F holdings.

### Context Hub

Context Hub is an optional knowledge base of uploaded files and URLs. A turn opts in with
`use_context_hub: true`. Uploaded files are stored in MinIO (`MINIO_CONTEXTHUB_BUCKET`) and
embedded through an OpenAI-wire `/embeddings` endpoint that is configured separately from the
chat LLM: `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`.

### Cost caps

Three independent limits bound a run:

- `max_researcher_iterations` (default 6) — supervisor turns.
- `max_concurrent_researchers` (default 3) — how many researchers run in parallel.
- `max_tool_call_iterations` (default 5) — ReAct rounds per researcher.

### Infra and observability

`DATABASE_URL`, `REDIS_URL` and `MINIO_*` default to the values in `docker-compose.yml`.
Traces are exported to SigNoz over OTLP (`OTEL_EXPORTER_OTLP_ENDPOINT`, default `:4317`). Set
`OTEL_ENABLED=false` to run without a collector.

## Database migrations

Postgres holds the LangGraph checkpointer and the session and audit tables, so threads survive
restarts and the API and worker share them. `make run` and `make worker` run `make db-upgrade`
(`alembic upgrade head`) automatically.

```bash
make db-revision MSG="add foo"   # autogenerate from db/models
make db-check                    # fail if models and applied schema drift
make db-downgrade REV=-1
```

## Observability (SigNoz)

```bash
make signoz-up      # deploys the stack from ../casting.yaml
make signoz-open    # UI at http://localhost:8080
```

## API

All routes are under `/v1`. Interactive docs are at `http://localhost:8001/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe (unversioned) |
| `POST` | `/v1/chat` | Enqueue a turn; returns `{thread_id, status: "queued"}` |
| `POST` | `/v1/chat/stream` | Enqueue a turn and stream its progress, sources and result via SSE |
| `GET` | `/v1/research/sessions` | List recent sessions (sidebar) |
| `PATCH` | `/v1/research/sessions/{thread_id}` | Rename and/or pin a session |
| `DELETE` | `/v1/research/sessions/{thread_id}` | Delete a session |
| `GET` | `/v1/research/{thread_id}` | Thread status: `queued` / `clarifying` / `running` / `done` / `failed` |
| `GET` | `/v1/research/{thread_id}/report` | Final report for a completed thread |
| `POST` | `/v1/contexthub/documents` | Upload a file to Context Hub |
| `POST` | `/v1/contexthub/urls` | Add a URL to Context Hub |
| `GET` | `/v1/contexthub/documents` | List Context Hub documents |
| `DELETE` | `/v1/contexthub/documents/{document_id}` | Delete a Context Hub document |
| `GET` | `/v1/suggestions/starter` | Example prompts for the empty chat state |

Chat request body:

```json
{ "message": "...", "thread_id": "<optional, resumes a thread>", "use_context_hub": false }
```

SSE event shapes are documented on `chat_stream` in `api/v1/chat.py` and mirrored in
`frontend/src/lib/types.ts`. Change both together.

## Development

```bash
make test                                              # pytest (asyncio_mode=auto, no network)
make test-file FILE=tests/unit/agents/test_graph.py    # one file; add -k name to filter
make lint           # ruff check      (make lint-fix / make format)
make typecheck      # mypy --strict
make check          # lint + typecheck + test, which is what CI runs
```

Tests mirror `src/` under `tests/unit/`. `tests/unit/agents/conftest.py` provides
`make_settings(**overrides)` and a scripted `FakeChatModel`. Webtool tests use `respx`.

## Layout

```
src/agentdrops/
  main.py        app lifespan, CORS, exception handlers, /health; mounts api/v1
  api/v1/        thin routers, one per route group, plus schema.py
  service/       business logic, one class per route group
  agents/        LangGraph graph, nodes, prompts, tools, edgar/, contexthub/
  webtools/      Tavily / Exa / NewsAPI / Reddit clients (retry + circuit breaker)
  worker/        Celery app and tasks that run chat turns
  jobs/          Redis pub/sub event relay between worker and API
  repository/    Postgres-backed session, audit and Context Hub stores
  db/            SQLAlchemy engine, models, Alembic migrations
  resilience/    HTTP/LLM retry policies, circuit breakers
  observability/ OpenTelemetry tracing, metrics, logging
```

The design spec is in `../docs/superpowers/specs/2026-07-12-deepresearch-market-agent-design.md`.
