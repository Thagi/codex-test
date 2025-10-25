"""API routes for the chatbot backend."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..core.config import get_settings
from ..models.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConsolidateRequest,
    ConsolidateResponse,
    GraphSnapshot,
)
from ..services.memory import GraphMemoryService, generate_summary
from ..services.ollama import OllamaClient

router = APIRouter()


def get_memory_service() -> GraphMemoryService:
    """Dependency returning the singleton memory service."""

    settings = get_settings()
    if not hasattr(get_memory_service, "_instance"):
        get_memory_service._instance = GraphMemoryService(  # type: ignore[attr-defined]
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            short_term_ttl_minutes=settings.short_term_ttl_minutes,
        )
    return get_memory_service._instance  # type: ignore[attr-defined]


def get_ollama_client() -> OllamaClient:
    """Dependency returning the Ollama client singleton."""

    settings = get_settings()
    if not hasattr(get_ollama_client, "_instance"):
        get_ollama_client._instance = OllamaClient(  # type: ignore[attr-defined]
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )
    return get_ollama_client._instance  # type: ignore[attr-defined]


@router.get("/health", tags=["system"])
async def healthcheck() -> dict[str, str]:
    """Return basic service health information."""

    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(
    payload: ChatRequest,
    memory_service: GraphMemoryService = Depends(get_memory_service),
    ollama_client: OllamaClient = Depends(get_ollama_client),
) -> ChatResponse:
    """Process a user message and return an AI-generated response."""

    user_message = ChatMessage(role="user", content=payload.message)
    await memory_service.add_short_term_message(payload.session_id, user_message)
    history = await memory_service.get_short_term_history(payload.session_id)
    context_text = "\n".join(f"{msg.role}: {msg.content}" for msg in history)
    prompt = f"{context_text}\nassistant:" if context_text else "assistant:"
    assistant_reply = await ollama_client.generate(prompt)
    assistant_message = ChatMessage(role="assistant", content=assistant_reply)
    await memory_service.add_short_term_message(payload.session_id, assistant_message)
    updated_history = await memory_service.get_short_term_history(payload.session_id)
    return ChatResponse(session_id=payload.session_id, reply=assistant_reply, short_term_snapshot=updated_history)


@router.get("/memory/{session_id}", response_model=list[ChatMessage], tags=["memory"])
async def get_memory(
    session_id: str,
    memory_service: GraphMemoryService = Depends(get_memory_service),
) -> list[ChatMessage]:
    """Return short-term memory for a session."""

    return await memory_service.get_short_term_history(session_id)


@router.post("/memory/consolidate", response_model=ConsolidateResponse, tags=["memory"])
async def consolidate(
    payload: ConsolidateRequest,
    memory_service: GraphMemoryService = Depends(get_memory_service),
    ollama_client: OllamaClient = Depends(get_ollama_client),
) -> ConsolidateResponse:
    """Trigger long-term memory consolidation for a session."""

    history = await memory_service.get_short_term_history(payload.session_id)
    if not history:
        raise HTTPException(status_code=404, detail="No short-term history found for session")
    summary = await generate_summary(history, ollama_client)
    knowledge_id = await memory_service.consolidate_long_term(
        session_id=payload.session_id,
        summary=summary,
        notes=payload.notes,
    )
    return ConsolidateResponse(knowledge_id=knowledge_id, summary=summary)


@router.get("/graph", response_model=GraphSnapshot, tags=["graph"])
async def graph_snapshot(
    memory_service: GraphMemoryService = Depends(get_memory_service),
) -> GraphSnapshot:
    """Return the full graph snapshot for visualization."""

    nodes, edges = await memory_service.get_graph_snapshot()
    return GraphSnapshot(nodes=nodes, edges=edges)
