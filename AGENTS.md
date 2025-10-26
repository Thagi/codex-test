# Project Guidelines

The repository hosts a Streamlit + FastAPI chatbot that stores memories in Neo4j, generates replies through an Ollama-served `gpt-oss-20b` model, and is published via Nginx. Unless a nested `AGENTS.md` overrides them, the conventions in this document apply to the entire tree.

## Architecture guardrails

- Preserve the current service topology: Streamlit → FastAPI → Neo4j/Ollama behind an Nginx reverse proxy.
- Short-term chat messages must land in Neo4j with a TTL and support fallback caching when the database is unavailable.
- Long-term consolidation is an operator-triggered action that creates `Knowledge` nodes linked to contributing short-term records.
- Expose the graph structure through an API (`/api/graph`) so the Streamlit UI can render node and edge metadata.

## Coding conventions

- Provide clear module, class, and function docstrings plus type annotations for new Python code.
- Keep configuration driven by environment variables; default values belong in `.env.example`.
- Prefer dependency-injected singletons (see `backend/app/api/routes.py`) instead of scattering new global clients.
- Handle Neo4j outages using the established fallback strategy in `GraphMemoryService` rather than introducing alternative storage layers.

## Tooling & documentation

- Extend or update the root `README.md` when behaviour, setup steps, or architecture change.
- Add or update tests under `backend/tests/` and run them with `pytest backend/tests` before committing when practical.
- Use the provided `Makefile` targets (`make compose-up`, `make dev-backend`, etc.) when documenting workflows or adding automation.

## UX improvement mandate

- Treat the Streamlit simulation workspace as an evolving prototype. Future contributions should prioritise reducing vertical scrolling (e.g., grouped participant controls, columnar layouts, or accordions) without sacrificing clarity for operators configuring multiple agents.
- Consolidate configuration inputs into reusable components where practical so the simulation page can scale past five agents without duplicating layout logic in `frontend/app.py`.
- When implementing GPT-to-GPT streaming or progress indicators, prefer incremental updates surfaced through the existing polling endpoint so front-end changes remain compatible with the backend job coordinator.
- Ensure incremental updates include the emitting agent, the turn index, and any graph deltas returned by the backend so operators can understand in-progress simulations without waiting for completion.

## Commit & PR expectations

- Keep commits focused and include any required documentation updates.
- Mention meaningful changes to memory handling, API schemas, or UI behaviour in PR summaries.
- Follow any additional instructions from nested `AGENTS.md` files when editing code in their scope.
