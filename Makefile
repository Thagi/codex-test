.PHONY: install-backend install-frontend dev-backend dev-frontend compose-up compose-down lint

COMPOSE_CMD ?= podman-compose
COMPOSE_FILE ?= docker-compose.yml

install-backend:
python -m venv .venv-backend && . .venv-backend/bin/activate && pip install -r backend/requirements.txt

install-frontend:
python -m venv .venv-frontend && . .venv-frontend/bin/activate && pip install -r frontend/requirements.txt

dev-backend:
uvicorn backend.app.main:app --reload --port $${BACKEND_PORT:-8000}

dev-frontend:
streamlit run frontend/app.py --server.port $${FRONTEND_PORT:-8501}

compose-up:
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) up --build

compose-down:
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) down
