# Graph Memory Chatbot

An AI chatbot that grows smarter through conversations by persisting memories in Neo4j. The system pairs a Streamlit front-end with a FastAPI backend, leverages an Ollama-served `gpt-oss-20b` model for responses, and exposes the experience through an Nginx reverse proxy.

## Features
- **Adaptive memory**: Short-term conversation nodes consolidate into long-term knowledge with operator control.
- **Graph inspection**: Visualize the knowledge graph from the Streamlit UI.
- **Modular services**: Streamlit, FastAPI, Neo4j, Ollama, and Nginx orchestrated via Docker Compose.

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
- Docker & Docker Compose
- (Optional) Python 3.11 for local development without containers

### Configuration
Copy `.env.example` to `.env` and adjust values as needed:
```bash
cp .env.example .env
```

Ensure the Ollama service has the `gpt-oss-20b` model pulled:
```bash
docker exec -it <ollama_container> ollama pull gpt-oss-20b
```

### Run with Docker Compose
```bash
make compose-up
```
Visit `http://localhost:8080/streamlit/` for the UI and `http://localhost:8080/api/docs` for backend API docs.

Stop the stack with:
```bash
make compose-down
```

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
