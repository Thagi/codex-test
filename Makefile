.PHONY: install-backend install-frontend dev-backend dev-frontend compose-up compose-down lint

install-backend:
python -m venv .venv-backend && . .venv-backend/bin/activate && pip install -r backend/requirements.txt

install-frontend:
python -m venv .venv-frontend && . .venv-frontend/bin/activate && pip install -r frontend/requirements.txt

dev-backend:
uvicorn backend.app.main:app --reload --port $${BACKEND_PORT:-8000}

dev-frontend:
streamlit run frontend/app.py --server.port $${FRONTEND_PORT:-8501}

compose-up:
docker-compose up --build

compose-down:
docker-compose down
