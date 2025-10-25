"""Graph memory service backed by Neo4j."""
from __future__ import annotations

from contextlib import asynccontextmanager
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncIterator, Dict, List, Optional, Tuple
from uuid import uuid4

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from ..models.chat import ChatMessage, GraphEdge, GraphNode


# Neo4j connectivity can fail with a variety of exception types depending on the
# networking layer (e.g. DNS resolution raising ``ValueError`` or lower level
# ``OSError`` variants). When those occur we fall back to the in-memory cache in
# the same way we do for driver-provided ``Neo4jError`` subclasses.
FALLBACK_EXCEPTIONS: Tuple[type[BaseException], ...] = (
    Neo4jError,
    ServiceUnavailable,
    OSError,
    ValueError,
)


@dataclass(slots=True)
class MemoryRecord:
    """Fallback in-memory record when Neo4j is unavailable."""

    session_id: str
    role: str
    content: str
    timestamp: datetime
    expires_at: Optional[datetime] = None


class GraphMemoryService:
    """Service orchestrating short-term and long-term memory graph operations."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        short_term_ttl_minutes: int,
    ) -> None:
        normalized_uri = self._normalize_uri(uri)
        self._uri = normalized_uri
        self._user = user
        self._password = password
        self._ttl = timedelta(minutes=short_term_ttl_minutes)
        self._ttl_minutes = short_term_ttl_minutes
        driver_kwargs: dict[str, object] = {"auth": (user, password)}
        self._driver = AsyncGraphDatabase.driver(normalized_uri, **driver_kwargs)
        self._fallback_records: list[MemoryRecord] = []

    @staticmethod
    def _normalize_uri(uri: str) -> str:
        """Return a Neo4j bolt URI suitable for direct connections."""

        if uri.startswith("neo4j+ssc://"):
            return "bolt+ssc://" + uri[len("neo4j+ssc://") :]
        if uri.startswith("neo4j+s://"):
            return "bolt+s://" + uri[len("neo4j+s://") :]
        if uri.startswith("neo4j://"):
            return "bolt://" + uri[len("neo4j://") :]
        return uri

    def _prune_fallback_records(self) -> None:
        """Drop expired fallback short-term records to keep memory bounded."""

        now = datetime.utcnow()
        self._fallback_records = [
            record
            for record in self._fallback_records
            if record.expires_at is None or record.expires_at >= now
        ]

    def _record_fallback(self, record: MemoryRecord) -> None:
        """Store a fallback record after pruning expired entries."""

        self._prune_fallback_records()
        self._fallback_records.append(record)

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
                result = await neo_session.run(query, parameters)
                await result.consume()
        except FALLBACK_EXCEPTIONS:
            self._record_fallback(
                MemoryRecord(
                    session_id=session_id,
                    role=message.role,
                    content=message.content,
                    timestamp=message.timestamp,
                    expires_at=message.timestamp + self._ttl,
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
        self._prune_fallback_records()
        try:
            async with self.session() as neo_session:
                result = await neo_session.run(query, session_id=session_id)
                neo4j_records = [record async for record in result]
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
        except FALLBACK_EXCEPTIONS:
            fallback_messages = [
                ChatMessage(role=rec.role, content=rec.content, timestamp=rec.timestamp)
                for rec in sorted(self._fallback_records, key=lambda r: r.timestamp)
                if rec.session_id == session_id
                and rec.role != "knowledge"
                and (rec.expires_at is None or rec.expires_at >= datetime.utcnow())
            ]
            return fallback_messages

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
                result = await neo_session.run(
                    query,
                    session_id=session_id,
                    knowledge_id=knowledge_id,
                    summary=summary,
                    notes=notes,
                )
                await result.consume()
        except FALLBACK_EXCEPTIONS:
            # fallback: just keep a memory record for display
            self._record_fallback(
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
        except FALLBACK_EXCEPTIONS:
            self._prune_fallback_records()
            nodes: List[GraphNode] = []
            edges: List[GraphEdge] = []
            node_ids: Dict[int, str] = {}
            sorted_records: List[Tuple[int, MemoryRecord]] = sorted(
                enumerate(self._fallback_records), key=lambda item: item[1].timestamp
            )
            for index, record in sorted_records:
                node_id = f"fallback-{index}"
                node_ids[index] = node_id
                node_type = "Knowledge" if record.role == "knowledge" else record.role
                metadata = {
                    "session_id": record.session_id,
                    "timestamp": record.timestamp.isoformat(),
                    "content": record.content,
                }
                if record.expires_at is not None:
                    metadata["expires_at"] = record.expires_at.isoformat()
                nodes.append(
                    GraphNode(
                        id=node_id,
                        label=node_type,
                        type=node_type,
                        metadata=metadata,
                    )
                )

            sessions: Dict[str, List[Tuple[int, MemoryRecord]]] = defaultdict(list)
            for index, record in sorted_records:
                sessions[record.session_id].append((index, record))

            for session_id, records in sessions.items():
                chronological = sorted(records, key=lambda item: item[1].timestamp)
                previous_message_index: Optional[int] = None
                knowledge_indices: List[int] = []
                for index, record in chronological:
                    if record.role == "knowledge":
                        knowledge_indices.append(index)
                        continue
                    if previous_message_index is not None:
                        edges.append(
                            GraphEdge(
                                source=node_ids[previous_message_index],
                                target=node_ids[index],
                                relation="FALLBACK_NEXT",
                                metadata={"session_id": session_id},
                            )
                        )
                    previous_message_index = index

                if previous_message_index is None:
                    continue
                for knowledge_index in knowledge_indices:
                    edges.append(
                        GraphEdge(
                            source=node_ids[previous_message_index],
                            target=node_ids[knowledge_index],
                            relation="FALLBACK_CONTRIBUTED",
                            metadata={"session_id": session_id},
                        )
                    )

            return nodes, edges

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
