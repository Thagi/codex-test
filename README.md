# Graph Memory Chatbot

An AI chatbot that grows smarter through conversations by persisting memories in Neo4j. The system pairs a Streamlit front-end with a FastAPI backend, leverages an Ollama-served `gpt-oss-20b` model for responses, and exposes the experience through an Nginx reverse proxy.

## Features
- **Adaptive memory**: Short-term conversation nodes consolidate into long-term knowledge with operator control.
- **Graph inspection**: Visualize the knowledge graph from the Streamlit UI.
- **Modular services**: Streamlit, FastAPI, Neo4j, and Nginx orchestrated via Podman Compose (Docker Compose compatible). Ollama runs on the host and is consumed via HTTP.

## Architecture
```
[Streamlit] --HTTP--> [Nginx] --> /api --> [FastAPI]
                                      \-> [Neo4j]
                                      \-> [Ollama]
                    \--> /streamlit --> [Streamlit]
```

Short-term memory stores individual exchanges linked as a path; a manual consolidation step triggers the LLM to summarize the dialogue and create long-term knowledge nodes.

## Getting Started

### Prerequisites
- Podman & podman-compose
- (Optional) Python 3.11 for local development without containers

### Configuration
Copy `.env.example` to `.env` and adjust values as needed:
```bash
cp .env.example .env
```

The sample configuration defaults `NEO4J_URI` to `bolt://neo4j:7687` so the
backend connects directly to the single Neo4j instance without attempting
routing-table discovery (which can trigger `Unable to retrieve routing
information` errors). If you already have a `.env` with `neo4j://...`, the
backend now normalizes it to the bolt equivalent automatically.

> **Password reminder:** Neo4j 5+ rejects the default password `neo4j`.
> The sample `.env` ships with `NEO4J_PASSWORD=neo4j_dev_password`; pick your
> own secret but avoid `neo4j`, and keep the `NEO4J_AUTH` entry in
> `docker-compose.yml` (or your deployment manifests) in sync.

### Ollama setup
Run Ollama separately on the host machine and make sure the `gpt-oss-20b` model is available:
```bash
ollama pull gpt-oss-20b
ollama serve
```

With Podman the containers can reach the host via `http://host.containers.internal`. The default `.env` points `OLLAMA_BASE_URL` to `http://host.containers.internal:11434` so no additional networking tweaks are required.

> **Using Docker instead of Podman?** Update `OLLAMA_BASE_URL` to `http://host.docker.internal:11434` in your `.env` file so the backend can reach the host Ollama instance.

### Run with Podman Compose
```bash
make compose-up
```
Visit `http://localhost:8080/streamlit/` for the UI and `http://localhost:8080/api/docs` for backend API docs.

Stop the stack with:
```bash
make compose-down
```

> **Tip:** Set `COMPOSE_CMD=docker-compose` when running `make compose-up` or `make compose-down` if you prefer Docker Compose.

### Local Development
Install backend dependencies:
```bash
make install-backend
```
Run the backend:
```bash
BACKEND_PORT=8000 make dev-backend
```

Install frontend dependencies:
```bash
make install-frontend
```
Run the frontend:
```bash
FRONTEND_PORT=8501 make dev-frontend
```

Set environment variables (`NEO4J_URI`, `OLLAMA_BASE_URL`, etc.) when running services locally.

## Testing
(Add tests under `backend/tests/` and invoke them via `pytest` once implemented.)

## Memory Model Overview
- **Short-term** (`ShortTermMessage` nodes): capture sequential chat messages with TTL.
- **Long-term** (`Knowledge` nodes): created via consolidation, linked back to contributing short-term messages.
- **Relationships**:
  - `(:ChatSession)-[:HAS_MESSAGE]->(:ShortTermMessage)`
  - `(:ShortTermMessage)-[:NEXT]->(:ShortTermMessage)` for chronology
  - `(:ShortTermMessage)-[:CONTRIBUTED_TO]->(:Knowledge)` to trace learning provenance
  - `(:ChatSession)-[:YIELDED]->(:Knowledge)` summarizing session learnings

## Graph Visualization
The Streamlit app fetches `/api/graph` and renders nodes/edges via PyVis. Use the "Refresh Graph View" button to pull the latest structure.

## Folder Structure
```
backend/   # FastAPI service
frontend/  # Streamlit app
nginx/     # Reverse proxy configuration
```

## Next Steps
- Add automated tests for Neo4j interactions using test containers or mocks.
- Implement background cleanup of expired short-term nodes.
- Extend long-term consolidation with richer LLM prompts and embeddings.
