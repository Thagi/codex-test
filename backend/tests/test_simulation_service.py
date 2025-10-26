"""Tests for the GPT-to-GPT simulation helpers."""
from __future__ import annotations

import anyio
import pytest

from backend.app.models.simulation import (
    SimulationJobStatus,
    SimulationParticipant,
    SimulationRequest,
)
from backend.app.services import simulation as simulation_service


class DummyOllamaClient:
    """Minimal Ollama stub that returns deterministic messages."""

    def __init__(self) -> None:
        self._call_count = 0

    async def generate(self, prompt: str):  # pragma: no cover - interface contract
        self._call_count += 1
        return f"response-{self._call_count}"


@pytest.fixture
def anyio_backend() -> str:
    """Limit anyio-powered tests to the asyncio backend bundled with pytest."""

    return "asyncio"


@pytest.mark.anyio
async def test_run_simulation_returns_graph(monkeypatch):
    """Simulations should return a transcript, summary, and meaningful graph snapshot."""

    request = SimulationRequest(
        turns=2,
        context="Explore renewable energy storage options.",
        participants=[
            SimulationParticipant(role="Engineer", persona="Detail oriented and pragmatic."),
            SimulationParticipant(role="Strategist", persona="Focus on market positioning."),
        ],
    )

    async def fake_summary(messages, _client):  # type: ignore[no-untyped-def]
        return "Synthetic summary"

    monkeypatch.setattr(simulation_service, "generate_summary", fake_summary)

    ollama_stub = DummyOllamaClient()
    transcript, summary, graph = await simulation_service.run_simulation(
        request, ollama_stub
    )

    expected_message_count = request.turns * len(request.participants)
    assert len(transcript) == expected_message_count
    assert summary == "Synthetic summary"

    # Ensure graph contains a session node and all messages are represented
    session_nodes = [node for node in graph.nodes if node.type == "SimulationSession"]
    assert session_nodes, "Simulation graph should include a session node"
    assert session_nodes[0].metadata["context"] == request.context

    message_nodes = [node for node in graph.nodes if node.type == "SimulationMessage"]
    assert len(message_nodes) == expected_message_count

    # The Ollama stub should be invoked once per generated message
    assert ollama_stub._call_count == expected_message_count


@pytest.mark.anyio
async def test_simulation_coordinator_executes_job(monkeypatch):
    """Simulation jobs should complete asynchronously and expose their result."""

    request = SimulationRequest(
        turns=1,
        context="Discuss battery recycling best practices.",
        participants=[
            SimulationParticipant(role="Scientist", persona="Loves experiments."),
            SimulationParticipant(role="Policy Maker", persona="Focus on regulations."),
        ],
    )

    async def fake_summary(messages, _client):  # type: ignore[no-untyped-def]
        return "Synthetic summary"

    monkeypatch.setattr(simulation_service, "generate_summary", fake_summary)

    ollama_stub = DummyOllamaClient()
    coordinator = simulation_service.SimulationCoordinator()

    job = await coordinator.start_simulation(request, ollama_stub)
    assert job.status == SimulationJobStatus.PENDING

    for _ in range(100):
        job = await coordinator.get_job(job.job_id)
        if job.status is SimulationJobStatus.COMPLETED:
            break
        await anyio.sleep(0.01)
    else:  # pragma: no cover - defensive branch
        pytest.fail("Simulation job did not complete in time")

    assert job.result is not None
    assert job.result.summary == "Synthetic summary"
    assert len(job.result.messages) == request.turns * len(request.participants)


@pytest.mark.anyio
async def test_simulation_coordinator_surfaces_errors():
    """Failures during generation should propagate to the job status."""

    request = SimulationRequest(
        turns=1,
        participants=[
            SimulationParticipant(role="Engineer"),
            SimulationParticipant(role="Strategist"),
        ],
    )

    class FailingOllamaClient:
        async def generate(self, prompt: str) -> str:  # pragma: no cover - stub behaviour
            raise RuntimeError("ollama unavailable")

    coordinator = simulation_service.SimulationCoordinator()
    job = await coordinator.start_simulation(request, FailingOllamaClient())

    for _ in range(100):
        job = await coordinator.get_job(job.job_id)
        if job.status is SimulationJobStatus.FAILED:
            break
        await anyio.sleep(0.01)
    else:  # pragma: no cover - defensive branch
        pytest.fail("Simulation job did not fail in time")

    assert job.error is not None
    assert "Engineer" in job.error
