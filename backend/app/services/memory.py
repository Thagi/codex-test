"""Graph memory service backed by Neo4j."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncIterator, List, Optional
from uuid import uuid4

from neo4j import AsyncGraphDatabase
from neo4j.async_ import AsyncSession
from neo4j.exceptions import Neo4jError

from ..models.chat import ChatMessage, GraphEdge, GraphNode


@dataclass(slots=True)
class MemoryRecord:
    """Fallback in-memory record when Neo4j is unavailable."""

    session_id: str
    role: str
    content: str
    timestamp: datetime


class GraphMemoryService:
    """Service orchestrating short-term and long-term memory graph operations."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        short_term_ttl_minutes: int,
    ) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._ttl = timedelta(minutes=short_term_ttl_minutes)
        self._ttl_minutes = short_term_ttl_minutes
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self._fallback_records: list[MemoryRecord] = []

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Context manager returning an async Neo4j session."""

        async with self._driver.session() as session:
            yield session

    async def add_short_term_message(self, session_id: str, message: ChatMessage) -> None:
        """Persist a chat message in the short-term region."""

        query = """
        MERGE (s:ChatSession {session_id: $session_id})
        ON CREATE SET s.created_at = datetime()
        WITH s
        CREATE (m:ShortTermMessage {
            id: $message_id,
            role: $role,
            content: $content,
            timestamp: datetime($timestamp),
            expires_at: datetime($timestamp) + duration({minutes: $ttl_minutes})
        })
        MERGE (s)-[:HAS_MESSAGE]->(m)
        WITH s, m
        OPTIONAL MATCH (s)-[:HAS_MESSAGE]->(prev)
        WHERE prev.timestamp < m.timestamp
        WITH s, m, prev
        ORDER BY prev.timestamp DESC
        LIMIT 1
        WITH m, prev
        WHERE prev IS NOT NULL
        MERGE (prev)-[:NEXT]->(m)
        """
        parameters = {
            "session_id": session_id,
            "message_id": str(uuid4()),
            "role": message.role,
            "content": message.content,
            "timestamp": message.timestamp.isoformat(),
            "ttl_minutes": self._ttl_minutes,
        }
        try:
            async with self.session() as neo_session:
                await neo_session.run(query, parameters)
        except Neo4jError:
            self._fallback_records.append(
                MemoryRecord(
                    session_id=session_id,
                    role=message.role,
                    content=message.content,
                    timestamp=message.timestamp,
                )
            )

    async def get_short_term_history(self, session_id: str) -> List[ChatMessage]:
        """Fetch ordered short-term messages for a session."""

        query = """
        MATCH (s:ChatSession {session_id: $session_id})-[:HAS_MESSAGE]->(m:ShortTermMessage)
        WHERE m.expires_at >= datetime()
        RETURN m.role AS role, m.content AS content, m.timestamp AS timestamp
        ORDER BY timestamp ASC
        """
        try:
            async with self.session() as neo_session:
                result = await neo_session.run(query, session_id=session_id)
                neo4j_records = await result.to_list()
                records = []
                for record in neo4j_records:
                    timestamp = record["timestamp"]
                    if hasattr(timestamp, "to_native"):
                        timestamp = timestamp.to_native()
                    records.append(
                        ChatMessage(
                            role=record["role"],
                            content=record["content"],
                            timestamp=timestamp,
                        )
                    )
                return records
        except Neo4jError:
            return [
                ChatMessage(role=rec.role, content=rec.content, timestamp=rec.timestamp)
                for rec in self._fallback_records
                if rec.session_id == session_id
            ]

    async def consolidate_long_term(self, session_id: str, summary: str, notes: Optional[str] = None) -> str:
        """Persist a long-term knowledge node derived from the session."""

        knowledge_id = str(uuid4())
        query = """
        MATCH (s:ChatSession {session_id: $session_id})-[:HAS_MESSAGE]->(m:ShortTermMessage)
        WITH collect(m) AS messages, s
        CREATE (k:Knowledge {
            id: $knowledge_id,
            session_id: $session_id,
            summary: $summary,
            notes: $notes,
            created_at: datetime()
        })
        MERGE (s)-[:YIELDED]->(k)
        WITH k, messages
        UNWIND messages AS msg
        MERGE (msg)-[:CONTRIBUTED_TO]->(k)
        RETURN k.id AS id
        """
        try:
            async with self.session() as neo_session:
                await neo_session.run(
                    query,
                    session_id=session_id,
                    knowledge_id=knowledge_id,
                    summary=summary,
                    notes=notes,
                )
        except Neo4jError:
            # fallback: just keep a memory record for display
            self._fallback_records.append(
                MemoryRecord(
                    session_id=session_id,
                    role="knowledge",
                    content=summary,
                    timestamp=datetime.utcnow(),
                )
            )
        return knowledge_id

    async def get_graph_snapshot(self) -> tuple[List[GraphNode], List[GraphEdge]]:
        """Retrieve graph nodes and edges for visualization."""

        query = """
        MATCH (n)
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
        """
        try:
            async with self.session() as neo_session:
                result = await neo_session.run(query)
                record = await result.single()
        except Neo4jError:
            nodes = [
                GraphNode(
                    id=str(index),
                    label=rec.role,
                    type="Fallback",
                    metadata={"content": rec.content, "timestamp": rec.timestamp.isoformat()},
                )
                for index, rec in enumerate(self._fallback_records)
            ]
            return nodes, []

        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []
        if record:
            for node in record["nodes"]:
                nodes.append(
                    GraphNode(
                        id=str(node.id),
                        label=next(iter(node.labels), "Node"),
                        type=next(iter(node.labels), "Node"),
                        metadata={k: v for k, v in node.items()},
                    )
                )
            for rel in record["rels"]:
                if rel is None:
                    continue
                edges.append(
                    GraphEdge(
                        source=str(rel.start_node.id),
                        target=str(rel.end_node.id),
                        relation=rel.type,
                        metadata={k: v for k, v in rel.items()},
                    )
                )
        return nodes, edges

    async def close(self) -> None:
        """Close driver connections and cleanup."""

        await self._driver.close()


async def generate_summary(messages: List[ChatMessage], ollama_client) -> str:
    """Create a summary of chat messages using the Ollama client."""

    prompt_lines = ["Summarize the following conversation focusing on stable knowledge."]
    for msg in messages:
        prompt_lines.append(f"{msg.role}: {msg.content}")
    prompt = "\n".join(prompt_lines)
    return await ollama_client.generate(prompt)
