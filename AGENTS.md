# Project Guidelines

This repository contains a Streamlit + FastAPI chatbot application backed by an Ollama-served `gpt-oss-20b` model, Neo4j for memory persistence, and Nginx as the public-facing web server.

## Scope
These guidelines apply to the entire repository unless superseded by more specific nested instructions.

## Architectural requirements
- Provide a Streamlit front-end that communicates with a FastAPI backend for chat interactions.
- Integrate with Ollama's `gpt-oss-20b` model endpoint for generating responses.
- Persist conversation state in a Neo4j graph database with distinct regions for short-term and long-term memory.
- Long-term memory should update when triggered via a UI button.
- Include a UI panel that visualizes or otherwise exposes the current graph structure.
- Use Nginx as a reverse proxy / web server in front of FastAPI and Streamlit services.

## Coding & documentation conventions
- Use descriptive module, class, and function docstrings.
- Prefer typing annotations for Python code.
- Provide configuration via environment variables wherever secrets / endpoints are required; default values belong in `.env.example`.
- Include setup instructions and run commands in the repository `README.md`.
- Tests or scripts must be runnable via `make` targets where appropriate.

## Commit & PR process
- Ensure changes include necessary documentation updates.
- Run available tests before committing when practical.
- Follow instructions in this file when preparing future changes.
