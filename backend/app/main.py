"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import get_memory_service, get_ollama_client, router
from .core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown tasks."""

    # Create singleton instances eagerly
    get_memory_service()
    get_ollama_client()
    yield
    await get_memory_service().close()
    await get_ollama_client().close()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(router, prefix="/api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    """Return service metadata."""

    return {"service": settings.app_name}
