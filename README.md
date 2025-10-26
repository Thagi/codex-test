# Graph Memory Chatbot

A conversational assistant that persists memories in Neo4j and lets operators promote insights into long-term knowledge. The stack combines a Streamlit front-end, a FastAPI backend, an Ollama-served `gpt-oss-20b` model, and Nginx as the public entry point.

## System overview

```
[User] -> [Nginx]
   ├─ /streamlit/ -> [Streamlit UI]
   └─ /api/ ------> [FastAPI]
                       ├─ stores messages in [Neo4j]
                       └─ generates replies via [Ollama]
```

### Core capabilities

- **Chat orchestration** – the `/api/chat` endpoint records every exchange in short-term memory and streams replies from Ollama back to the UI.
- **Operator-driven consolidation** – a Streamlit action calls `/api/memory/consolidate` to summarize recent dialogue into a `Knowledge` node, linking contributing messages for provenance.
- **Graph insight** – `/api/graph` exposes all nodes and edges so the front-end can render the knowledge graph with PyVis.
- **Resilient storage** – when Neo4j is unreachable the memory service falls back to an in-process cache, allowing conversations to continue and graph visualisation to work with synthetic nodes until connectivity returns.
- **Agent simulations** – `/api/simulation/run` now enqueues multi-agent GPT discussions and returns a job identifier; `/api/simulation/run/{job_id}` exposes progress and results so operators can review the proposed graph before opting into `/api/simulation/commit`.

## Getting started

### 1. Prerequisites

- Podman + `podman-compose` (or Docker + `docker compose`)
- Ollama installed on the host machine with the `gpt-oss-20b` model pulled
- (Optional) Python 3.11 for local development without containers

### 2. Configure environment variables

Copy the sample file and tweak as needed:

```bash
cp .env.example .env
```

Key variables:

- `NEO4J_URI` defaults to `bolt://neo4j:7687`. The backend normalizes any `neo4j://` URI to `bolt://` to avoid routing-table errors with single-instance deployments.
- `OLLAMA_BASE_URL` should point to your host runtime. Podman users can keep `http://host.containers.internal:11434`; Docker users typically need `http://host.docker.internal:11434`.
- `NEO4J_USER` / `NEO4J_PASSWORD` must match the credentials supplied to the Neo4j container in `docker-compose.yml`.

> **Neo4j password tip:** Neo4j 5+ blocks the default password `neo4j`. The example file uses `neo4j_dev_password`; update both `.env` and the compose file together when changing it.

### 3. Prepare Ollama

Run Ollama outside the compose stack and ensure the target model is available:

```bash
ollama pull gpt-oss-20b
ollama serve
```

Containers connect to the host runtime via the `OLLAMA_BASE_URL` you configured.

### 4. Launch the stack

```bash
make compose-up
```

Visit:

- `http://localhost:8080/streamlit/` – Streamlit UI
- `http://localhost:8080/api/docs` – FastAPI interactive docs

Shut everything down with:

```bash
make compose-down
```

Set `COMPOSE_CMD=docker-compose` if you prefer Docker over Podman; the make targets respect the override.

### 5. Persisted Neo4j volumes

- Neo4j mounts host directories under `./data/neo4j/`, so compose shutdowns do **not** delete prior knowledge.
- Reset the graph using the Streamlit danger-zone control, `DELETE /api/graph`, or by removing the `data/neo4j/` directory before restarting.

## Local development

Create isolated virtual environments and run services directly:

```bash
make install-backend
BACKEND_PORT=8000 make dev-backend

make install-frontend
FRONTEND_PORT=8501 make dev-frontend
```

The backend exposes a FastAPI app at `/api` and depends on running Neo4j + Ollama instances. The Streamlit app uses `BACKEND_URL` (default `http://backend:8000/api`) to talk to the API.

## Backend details

- **Configuration** – `backend/app/core/config.py` reads environment variables via Pydantic settings and caches a singleton instance per process.
- **Service wiring** – dependency helpers in `backend/app/api/routes.py` create singletons for the `GraphMemoryService` and `OllamaClient`, ensuring connections are shared for the process lifetime.
- **Simulation tooling** – `backend/app/services/simulation.py` assembles prompts for each agent, produces a graph snapshot of the proposed dialogue, and now manages asynchronous jobs so long-running simulations surface progress and errors without tripping HTTP timeouts.
- **Fallback behaviour** – the memory service stores recent messages in Neo4j and mirrors them in a TTL-based in-memory list when the database is unreachable, enabling uninterrupted chat sessions.
- **Graph export** – `/api/graph` returns serialised nodes/edges by walking the Neo4j result or the fallback cache, preserving metadata for the front-end visualisation.

## Frontend details

- The Streamlit UI keeps session state for chat history, graph data, and live metrics. Messages are rendered via `st.chat_message`, and the chat input is kept outside tab layouts to comply with Streamlit constraints.
- Graph rendering uses PyVis, exposing node metadata tooltips and providing refresh / reset controls inside the “Knowledge graph” tab.
- Operators can add optional notes during consolidation; successful summaries are surfaced back in the UI before the graph refreshes.
- A sidebar toggle separates the live user ↔ GPT conversation workspace from the GPT ↔ GPT simulation lab, where operators configure agent personas, enqueue automated discussions, poll for their completion, inspect the temporary graph, and merge results into existing sessions on demand.

## Testing

Backend unit tests live under `backend/tests/`. Execute them with:

```bash
pytest backend/tests
```

The existing suite verifies configuration defaults; extend it as services evolve.

## Repository structure

```
backend/   # FastAPI application code, services, and tests
frontend/  # Streamlit UI
nginx/     # Reverse proxy configuration for /api and /streamlit
data/      # Persisted Neo4j volumes (created after first run)
```

## Roadmap ideas

- Add integration tests for Neo4j graph mutations and Ollama prompts using mocks or containers.
- Expose long-term knowledge retrieval in the chat prompt to ground responses.
- Enhance the graph panel with filtering (per session / node type) and live WebSocket updates.
