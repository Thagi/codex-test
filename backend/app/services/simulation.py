"""Utility functions powering GPT-to-GPT simulations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Tuple
from uuid import uuid4

from ..models.chat import ChatMessage, GraphEdge, GraphNode, GraphSnapshot
from ..models.simulation import SimulationParticipant, SimulationRequest
from .memory import generate_summary
from .ollama import OllamaClient


@dataclass(slots=True)
class _PromptContext:
    """Aggregates state needed to craft role-specific prompts."""

    request: SimulationRequest
    messages: List[ChatMessage]

    def render_conversation(self) -> str:
        """Return the conversation so far as plain text."""

        history_lines: List[str] = []
        if self.request.context:
            history_lines.append(f"Scenario: {self.request.context}")
        for message in self.messages:
            history_lines.append(f"{message.role}: {message.content}")
        return "\n".join(history_lines) if history_lines else "(no previous dialogue)"


def _build_prompt(context: _PromptContext, participant: SimulationParticipant) -> str:
    """Compose a prompt instructing the participant to speak next."""

    persona_section = (
        f"\nPersona guidance: {participant.persona.strip()}"
        if participant.persona
        else ""
    )
    conversation = context.render_conversation()
    return (
        f"You are {participant.role}, participating in a round-table discussion with other expert agents."  # noqa: E501
        f"{persona_section}\n"
        "Respond with a single, well-formed message that reflects your expertise and advances the conversation.\n"  # noqa: E501
        "Do not narrate actions or mention that you are an AI model.\n"
        f"Conversation so far:\n{conversation}\n\n"
        f"{participant.role}:"
    )


def _build_simulation_graph(
    request: SimulationRequest,
    messages: Iterable[ChatMessage],
    summary: str,
) -> GraphSnapshot:
    """Create a graph snapshot describing the simulated conversation."""

    nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []
    session_node_id = f"sim-session-{uuid4()}"
    participants_meta = [participant.role for participant in request.participants]
    nodes.append(
        GraphNode(
            id=session_node_id,
            label="SimulationSession",
            type="SimulationSession",
            metadata={
                "context": request.context or "",
                "turns": request.turns,
                "participants": participants_meta,
                "generated_at": datetime.utcnow().isoformat(),
            },
        )
    )

    previous_message_id: str | None = None
    for index, message in enumerate(messages):
        message_node_id = f"sim-message-{index}"
        nodes.append(
            GraphNode(
                id=message_node_id,
                label=message.role,
                type="SimulationMessage",
                metadata={
                    "role": message.role,
                    "content": message.content,
                    "timestamp": message.timestamp.isoformat(),
                    "sequence": index,
                },
            )
        )
        edges.append(
            GraphEdge(
                source=session_node_id,
                target=message_node_id,
                relation="HAS_MESSAGE",
                metadata={"order": index},
            )
        )
        if previous_message_id is not None:
            edges.append(
                GraphEdge(
                    source=previous_message_id,
                    target=message_node_id,
                    relation="NEXT",
                    metadata={"sequence": index},
                )
            )
        previous_message_id = message_node_id

    knowledge_node_id = f"sim-knowledge-{uuid4()}"
    nodes.append(
        GraphNode(
            id=knowledge_node_id,
            label="SimulationKnowledge",
            type="SimulationKnowledge",
            metadata={
                "summary": summary,
                "context": request.context or "",
            },
        )
    )
    edges.append(
        GraphEdge(
            source=session_node_id,
            target=knowledge_node_id,
            relation="YIELDED",
            metadata={},
        )
    )
    if previous_message_id is not None:
        edges.append(
            GraphEdge(
                source=previous_message_id,
                target=knowledge_node_id,
                relation="CONTRIBUTED_TO",
                metadata={},
            )
        )

    return GraphSnapshot(nodes=nodes, edges=edges)


async def run_simulation(
    request: SimulationRequest, ollama_client: OllamaClient
) -> Tuple[List[ChatMessage], str, GraphSnapshot]:
    """Execute the GPT-to-GPT dialogue and return the transcript and graph."""

    transcript: List[ChatMessage] = []
    prompt_context = _PromptContext(request=request, messages=transcript)

    for _ in range(request.turns):
        for participant in request.participants:
            prompt = _build_prompt(prompt_context, participant)
            reply = await ollama_client.generate(prompt)
            transcript.append(ChatMessage(role=participant.role, content=reply))

    summary = await generate_summary(transcript, ollama_client)
    graph = _build_simulation_graph(request, transcript, summary)
    return transcript, summary, graph
