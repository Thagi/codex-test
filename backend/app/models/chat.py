"""Pydantic models for chat interactions."""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Represents a single chat message."""

    role: str = Field(description="Author role: user/assistant/system")
    content: str = Field(description="Message text")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Creation time")


class ChatRequest(BaseModel):
    """Request payload for submitting a user message."""

    session_id: str = Field(description="Identifier for the chat session")
    message: str = Field(description="User message text")


class ChatResponse(BaseModel):
    """Response payload containing the assistant reply."""

    session_id: str
    reply: str
    short_term_snapshot: List[ChatMessage]


class ConsolidateRequest(BaseModel):
    """Request payload for triggering long-term memory consolidation."""

    session_id: str
    notes: Optional[str] = Field(default=None, description="Optional operator notes")


class ConsolidateResponse(BaseModel):
    """Response payload returned after long-term consolidation."""

    knowledge_id: str
    summary: str


class GraphNode(BaseModel):
    """A graph node representation for visualization."""

    id: str
    label: str
    type: str
    metadata: dict[str, Any]


class GraphEdge(BaseModel):
    """A graph edge representation for visualization."""

    source: str
    target: str
    relation: str
    metadata: dict[str, Any]


class GraphSnapshot(BaseModel):
    """Full graph snapshot for UI display."""

    nodes: List[GraphNode]
    edges: List[GraphEdge]
