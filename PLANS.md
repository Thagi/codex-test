# Implementation Plan

## Current state snapshot

- **Backend** – FastAPI app under `backend/app` exposes chat, memory, and graph endpoints, persisting data in Neo4j with an in-process fallback cache for outages.
- **Frontend** – Streamlit UI in `frontend/app.py` provides chat, consolidation controls, and PyVis graph visualisation.
- **Infrastructure** – `docker-compose.yml` orchestrates backend, frontend, Neo4j, and Nginx; the Makefile wraps local dev and compose workflows.
- **Testing** – Minimal pytest coverage exists for configuration defaults.

## Near-term enhancements

1. **Broaden automated tests**
   - Add unit tests for `GraphMemoryService` covering short-term inserts, consolidation Cypher, fallback pruning, and graph export helpers.
   - Mock the Ollama client to test `generate_summary` prompt construction without hitting the external service.

2. **Improve retrieval quality**
   - Feed long-term knowledge back into the chat prompt (e.g., retrieve recent `Knowledge` nodes per session before generating a reply).
   - Surface consolidated knowledge in the Streamlit conversation view so operators can see what the model already knows.

3. **Observability & resilience**
   - Emit structured logging around Neo4j failures and fallback usage to aid debugging.
   - Add health endpoints or status cards indicating Neo4j / Ollama connectivity in the Streamlit sidebar.

4. **Graph UX refinements**
   - Provide filters (by session, node type) in the graph tab.
   - Highlight edges contributing to a selected knowledge node and show summaries inline.

5. **Deployment polish**
   - Supply production-ready configuration samples (TLS termination for Nginx, resource limits).
   - Document how to scale the backend horizontally while reusing the Neo4j instance.

## Stretch goals

- Introduce background workers to consolidate short-term memory automatically based on heuristics.
- Explore embedding-based recall (e.g., integrate a vector store) to supplement graph traversal for retrieval.
- Add end-to-end tests that exercise the Streamlit front-end against a seeded backend using Playwright.
