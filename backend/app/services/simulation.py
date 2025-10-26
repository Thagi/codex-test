"""Utility functions powering GPT-to-GPT simulations."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Dict, Iterable, List, Tuple, TypeVar
from uuid import uuid4

from ..models.chat import ChatMessage, GraphEdge, GraphNode, GraphSnapshot
from ..models.simulation import (
    SimulationJob,
    SimulationJobStatus,
    SimulationParticipant,
    SimulationRequest,
    SimulationResponse,
)
from .memory import generate_summary
from .ollama import OllamaClient


_T = TypeVar("_T")


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


class SimulationError(RuntimeError):
    """Raised when a simulation cannot be completed successfully."""


async def _await_with_timeout(
    awaitable: Awaitable[_T],
    timeout_seconds: float | None,
    timeout_message: str,
) -> _T:
    """Await a coroutine, raising a simulation error if it exceeds the timeout."""

    try:
        if timeout_seconds is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError as exc:
        raise SimulationError(timeout_message) from exc


async def run_simulation(
    request: SimulationRequest,
    ollama_client: OllamaClient,
    *,
    max_tokens_per_message: int | None = None,
    generation_timeout_seconds: float | None = None,
) -> Tuple[List[ChatMessage], str, GraphSnapshot]:
    """Execute the GPT-to-GPT dialogue and return the transcript and graph."""

    transcript: List[ChatMessage] = []
    prompt_context = _PromptContext(request=request, messages=transcript)

    for _ in range(request.turns):
        for participant in request.participants:
            prompt = _build_prompt(prompt_context, participant)
            options = (
                {"num_predict": max_tokens_per_message}
                if max_tokens_per_message and max_tokens_per_message > 0
                else None
            )
            generation_coro = ollama_client.generate(prompt, options=options)
            try:
                reply = await _await_with_timeout(
                    generation_coro,
                    generation_timeout_seconds,
                    (
                        "Timed out waiting for a reply from participant "
                        f"'{participant.role}'. Check the Ollama service or network connectivity."
                    ),
                )
            except asyncio.CancelledError:
                raise
            except SimulationError:
                raise
            except Exception as exc:  # pragma: no cover - surface backend failure
                raise SimulationError(
                    f"Failed to generate a reply for role '{participant.role}'."
                ) from exc
            transcript.append(ChatMessage(role=participant.role, content=reply))

    summary_coro = generate_summary(
        transcript,
        ollama_client,
        max_tokens=max_tokens_per_message,
    )
    try:
        summary = await _await_with_timeout(
            summary_coro,
            generation_timeout_seconds,
            (
                "Timed out while generating the simulation summary. "
                "Verify the Ollama service is responsive."
            ),
        )
    except asyncio.CancelledError:
        raise
    except SimulationError:
        raise
    except Exception as exc:  # pragma: no cover - surface backend failure
        raise SimulationError("Failed to summarize simulated conversation.") from exc

    graph = _build_simulation_graph(request, transcript, summary)
    return transcript, summary, graph


@dataclass(slots=True)
class _SimulationJobState:
    """Internal representation of a simulation job's state."""

    job_id: str
    request: SimulationRequest
    status: SimulationJobStatus = SimulationJobStatus.PENDING
    result: SimulationResponse | None = None
    error: str | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    started_at: float | None = None


class SimulationCoordinator:
    """Manage asynchronous execution and retrieval of simulation jobs."""

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        max_tokens_per_message: int | None = None,
        generation_timeout_seconds: float | None = None,
    ) -> None:
        """Initialize the coordinator.

        Args:
            timeout_seconds: Optional maximum duration allowed for a simulation job
                before it is cancelled and marked as failed.
            max_tokens_per_message: Optional upper bound for tokens generated by
                each participant response and the final summary.
            generation_timeout_seconds: Optional cap for individual Ollama
                requests. When provided, responses that exceed the timeout fail
                fast with a clear error rather than leaving jobs in limbo.
        """

        self._jobs: Dict[str, _SimulationJobState] = {}
        self._lock = asyncio.Lock()
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
        )
        self._max_tokens_per_message = (
            max_tokens_per_message
            if max_tokens_per_message and max_tokens_per_message > 0
            else None
        )
        self._generation_timeout_seconds = (
            generation_timeout_seconds
            if generation_timeout_seconds and generation_timeout_seconds > 0
            else None
        )

    async def start_simulation(
        self, request: SimulationRequest, ollama_client: OllamaClient
    ) -> SimulationJob:
        """Enqueue a simulation job and begin execution in the background."""

        job_id = f"sim-job-{uuid4()}"
        state = _SimulationJobState(job_id=job_id, request=request)
        async with self._lock:
            self._jobs[job_id] = state
        state.task = asyncio.create_task(self._execute_job(state, ollama_client))
        return await self.get_job(job_id)

    async def get_job(self, job_id: str) -> SimulationJob:
        """Return a snapshot of the requested job's state."""

        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            self._apply_timeout_if_needed(state)
            return self._snapshot_job(state)

    async def _execute_job(
        self, state: _SimulationJobState, ollama_client: OllamaClient
    ) -> None:
        """Run the simulation and store the results on the job state."""

        async with self._lock:
            state.status = SimulationJobStatus.RUNNING
            state.started_at = asyncio.get_running_loop().time()

        try:
            simulation_coro = run_simulation(
                state.request,
                ollama_client,
                max_tokens_per_message=self._max_tokens_per_message,
                generation_timeout_seconds=self._generation_timeout_seconds,
            )
            if self._timeout_seconds is not None:
                transcript, summary, graph = await asyncio.wait_for(
                    simulation_coro, timeout=self._timeout_seconds
                )
            else:
                transcript, summary, graph = await simulation_coro
        except asyncio.CancelledError:
            async with self._lock:
                if state.status is SimulationJobStatus.RUNNING:
                    state.status = SimulationJobStatus.FAILED
                    if state.error is None:
                        state.error = "Simulation was cancelled."
                state.task = None
                state.started_at = None
            return
        except asyncio.TimeoutError:
            async with self._lock:
                state.status = SimulationJobStatus.FAILED
                if self._timeout_seconds is not None:
                    state.error = (
                        "Simulation exceeded the maximum runtime of "
                        f"{self._timeout_seconds} seconds."
                    )
                else:  # pragma: no cover - defensive fallback
                    state.error = "Simulation exceeded the maximum runtime."
                state.task = None
                state.started_at = None
            return
        except Exception as exc:  # pragma: no cover - defensive programming
            async with self._lock:
                state.status = SimulationJobStatus.FAILED
                state.error = str(exc)
                state.task = None
                state.started_at = None
            return

        result = SimulationResponse(messages=transcript, summary=summary, graph=graph)
        async with self._lock:
            state.status = SimulationJobStatus.COMPLETED
            state.result = result
            state.task = None
            state.started_at = None

    async def shutdown(self) -> None:
        """Cancel any in-flight jobs during application shutdown."""

        async with self._lock:
            tasks = [job.task for job in self._jobs.values() if job.task is not None]
        for task in tasks:
            if task is None:
                continue
            if task.done():
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @staticmethod
    def _snapshot_job(state: _SimulationJobState) -> SimulationJob:
        """Convert an internal job state to its API representation."""

        return SimulationJob(
            job_id=state.job_id,
            status=state.status,
            result=state.result,
            error=state.error,
        )

    def _apply_timeout_if_needed(self, state: _SimulationJobState) -> None:
        """Mark running jobs as failed if they have exceeded the timeout."""

        if (
            self._timeout_seconds is None
            or state.status is not SimulationJobStatus.RUNNING
            or state.started_at is None
        ):
            return

        elapsed = asyncio.get_running_loop().time() - state.started_at
        if elapsed <= self._timeout_seconds:
            return

        state.status = SimulationJobStatus.FAILED
        state.error = (
            "Simulation exceeded the maximum runtime of "
            f"{self._timeout_seconds} seconds."
        )
        state.started_at = None
        task = state.task
        if task is not None and not task.done():
            task.cancel()
            task.add_done_callback(self._silence_task_result)
        elif task is not None and task.done():
            state.task = None

    @staticmethod
    def _silence_task_result(task: asyncio.Task[None]) -> None:
        """Swallow task cancellation exceptions to avoid noisy logs."""

        with suppress(asyncio.CancelledError, Exception):
            task.result()
