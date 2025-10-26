"""Streamlit front-end for the adaptive chatbot."""
from __future__ import annotations

import json
import os
import time
from importlib import resources
from typing import Any, Dict

import requests
import streamlit as st
from pyvis.network import Network

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000/api")


def _send_message(session_id: str, message: str) -> dict:
    response = requests.post(
        f"{BACKEND_URL}/chat",
        json={"session_id": session_id, "message": message},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _trigger_consolidation(session_id: str, notes: str | None = None) -> dict:
    response = requests.post(
        f"{BACKEND_URL}/memory/consolidate",
        json={"session_id": session_id, "notes": notes},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _load_graph() -> dict:
    response = requests.get(f"{BACKEND_URL}/graph", timeout=30)
    response.raise_for_status()
    return response.json()


def _clear_graph() -> dict:
    response = requests.delete(f"{BACKEND_URL}/graph", timeout=30)
    response.raise_for_status()
    return response.json()


def _load_short_term_history(session_id: str) -> tuple[list[dict] | None, str | None]:
    try:
        response = requests.get(f"{BACKEND_URL}/memory/{session_id}", timeout=30)
    except requests.RequestException as exc:
        return None, f"History unavailable: {exc}"
    if response.ok:
        return response.json(), None
    return None, f"Could not load short-term history (status {response.status_code})"


def _start_simulation(config: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(
        f"{BACKEND_URL}/simulation/run",
        json=config,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _poll_simulation(job_id: str) -> Dict[str, Any]:
    response = requests.get(
        f"{BACKEND_URL}/simulation/run/{job_id}",
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _await_simulation(job_id: str, *, timeout: int = 300, poll_interval: float = 2.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _poll_simulation(job_id)
        state = status.get("status")
        if state == "completed":
            return status.get("result", {})
        if state == "failed":
            message = status.get("error") or "Simulation failed"
            raise RuntimeError(message)
        time.sleep(poll_interval)
    raise TimeoutError("Simulation did not finish before the timeout elapsed")


def _commit_simulation(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(
        f"{BACKEND_URL}/simulation/commit",
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


_PYVIS_UTILS_SNIPPET: str | None = None


def _render_graph(graph_data: dict) -> None:
    network = Network(height="500px", width="100%", bgcolor="#ffffff", directed=True)
    for node in graph_data.get("nodes", []):
        network.add_node(
            node["id"],
            label=node.get("label", node["id"]),
            title=json.dumps(node.get("metadata", {}), indent=2, ensure_ascii=False),
            color="#4C78A8" if node.get("type") == "ShortTermMessage" else "#F58518",
        )
    for edge in graph_data.get("edges", []):
        network.add_edge(
            edge["source"],
            edge["target"],
            label=edge.get("relation", ""),
        )
    network.repulsion(node_distance=200, spring_length=200)
    html = network.generate_html()

    global _PYVIS_UTILS_SNIPPET
    if _PYVIS_UTILS_SNIPPET is None:
        try:
            utils_path = resources.files("pyvis").joinpath("templates/lib/bindings/utils.js")
            _PYVIS_UTILS_SNIPPET = utils_path.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError):
            _PYVIS_UTILS_SNIPPET = ""

    if _PYVIS_UTILS_SNIPPET:
        html = html.replace(
            '<script src="lib/bindings/utils.js"></script>',
            f"<script>{_PYVIS_UTILS_SNIPPET}</script>",
        )

    st.components.v1.html(html, height=520)


def render_chat_page(session_id: str) -> None:
    """Render the traditional user ↔ GPT conversation tools."""

    history_data, history_error = _load_short_term_history(session_id)

    def _refresh_graph() -> None:
        graph_data = _load_graph()
        st.session_state["graph_data"] = graph_data

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "graph_data" not in st.session_state:
        st.session_state.graph_data = {"nodes": [], "edges": []}
    if "graph_loaded" not in st.session_state:
        try:
            _refresh_graph()
        except requests.RequestException:
            st.session_state.graph_data = {"nodes": [], "edges": []}
        finally:
            st.session_state.graph_loaded = True

    if history_data and not st.session_state.messages:
        st.session_state.messages = [
            {"role": item["role"], "content": item["content"]}
            for item in history_data
        ]

    graph_data = st.session_state.get("graph_data", {"nodes": [], "edges": []})
    node_count = len(graph_data.get("nodes", []))
    edge_count = len(graph_data.get("edges", []))
    session_count = len(
        {
            node.get("metadata", {}).get("session_id")
            for node in graph_data.get("nodes", [])
            if node.get("metadata", {}).get("session_id")
        }
    )
    message_count = len(st.session_state.messages)

    stat_cols = st.columns(4)
    stat_cols[0].metric("Messages", message_count)
    stat_cols[1].metric("Sessions tracked", session_count or 0)
    stat_cols[2].metric("Graph nodes", node_count)
    stat_cols[3].metric("Graph edges", edge_count)

    tab_labels = [
        "💬 Conversation",
        "📝 Memory tools",
        "🕸️ Knowledge graph",
    ]

    conversation_tab, memory_tab, graph_tab = st.tabs(tab_labels)

    with conversation_tab:
        st.subheader("Live conversation")
        st.caption("Messages flow into short-term memory before consolidation.")
        if st.session_state.messages:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
        else:
            st.info("Start the dialogue using the input below.")

        with st.expander("Short-term memory snapshot", expanded=False):
            if history_data:
                st.json(history_data)
            elif history_error:
                st.warning(history_error)
            else:
                st.info("Start chatting to populate the short-term memory cache.")

    with memory_tab:
        st.subheader("Consolidate knowledge")
        st.caption("Summarize recent exchanges into long-term knowledge nodes.")
        consolidate_notes = st.text_area(
            "Optional consolidation notes",
            placeholder="Highlight facts worth retaining in long-term memory...",
            height=140,
            key="consolidate_notes",
        )
        trigger_consolidation = st.button(
            "Trigger update",
            use_container_width=True,
            key="trigger_consolidation_button",
        )

        if trigger_consolidation:
            with st.spinner("Consolidating conversation..."):
                try:
                    result = _trigger_consolidation(session_id, consolidate_notes or None)
                except requests.RequestException as exc:
                    st.error(f"Failed to consolidate: {exc}")
                else:
                    st.success(f"Knowledge node created: {result['knowledge_id']}")
                    st.info(result["summary"])
                    try:
                        _refresh_graph()
                    except requests.RequestException as exc:
                        st.warning(f"Could not refresh graph: {exc}")
                    else:
                        st.rerun()

    with graph_tab:
        st.subheader("Knowledge graph overview")
        st.caption("Inspect the current memory graph and manage stored knowledge.")
        refresh_graph = st.button(
            "Refresh graph",
            use_container_width=True,
            key="refresh_graph_button",
        )

        if refresh_graph:
            with st.spinner("Refreshing graph..."):
                try:
                    _refresh_graph()
                except requests.RequestException as exc:
                    st.error(f"Failed to load graph: {exc}")
                else:
                    st.rerun()

        if graph_data.get("nodes"):
            _render_graph(graph_data)
        else:
            st.info("Graph will appear after interactions are stored.")

        with st.expander("Raw graph data", expanded=False):
            st.json(graph_data)

        with st.expander("Danger zone: clear stored graph", expanded=False):
            st.warning("Removing the graph deletes all stored chat memories and knowledge nodes.")
            confirmation = st.text_input(
                "Type DELETE to confirm graph reset",
                key="clear_graph_confirmation",
            )
            clear_graph = st.button(
                "Clear graph",
                use_container_width=True,
                key="clear_graph_button",
                disabled=confirmation.strip().upper() != "DELETE",
            )
            if clear_graph:
                with st.spinner("Clearing graph..."):
                    try:
                        _clear_graph()
                    except requests.RequestException as exc:
                        st.error(f"Failed to clear graph: {exc}")
                    else:
                        st.success("Graph cleared. Existing chat sessions will start fresh.")
                        st.session_state.messages = []
                        st.session_state.graph_data = {"nodes": [], "edges": []}
                        st.rerun()

    st.markdown("---")
    st.caption(
        "Send a message to continue the conversation. This input stays available even "
        "when viewing the memory or graph tabs."
    )
    user_input = st.chat_input(
        f"Message for session '{session_id}'",
        key="chat_input",
    )

    if user_input:
        with st.spinner("Sending message..."):
            try:
                response = _send_message(session_id, user_input)
            except requests.RequestException as exc:
                st.error(f"Failed to send message: {exc}")
            else:
                st.session_state.messages = [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in response.get("short_term_snapshot", [])
                ]
                try:
                    _refresh_graph()
                except requests.RequestException as exc:
                    st.warning(f"Graph refresh failed: {exc}")
                st.rerun()


def render_simulation_page() -> None:
    """Render the GPT ↔ GPT simulation tools."""

    st.subheader("Automated agent conversation")
    st.caption(
        "Configure multiple GPT roles, run a simulated discussion, and decide whether to merge "
        "the outcome into an existing knowledge graph session."
    )

    if "simulation_result" not in st.session_state:
        st.session_state.simulation_result = None

    min_participants = 2
    max_participants = 5
    if "simulation_participants" not in st.session_state:
        st.session_state.simulation_participants = [
            {"role": "Agent 1", "persona": ""},
            {"role": "Agent 2", "persona": ""},
        ]

    context = st.text_area(
        "Scenario / topic",
        placeholder="Outline the theme, goal, or problem the agents should discuss...",
        key="simulation_context",
    )
    turns = st.slider(
        "Number of turns",
        min_value=1,
        max_value=10,
        value=st.session_state.get("simulation_turns", 3),
        key="simulation_turns",
    )

    st.markdown("### Participants")
    control_cols = st.columns(2)
    with control_cols[0]:
        add_participant = st.button(
            "Add participant",
            use_container_width=True,
            disabled=len(st.session_state.simulation_participants) >= max_participants,
            key="simulation_add_participant",
        )
    with control_cols[1]:
        remove_participant = st.button(
            "Remove last participant",
            use_container_width=True,
            disabled=len(st.session_state.simulation_participants) <= min_participants,
            key="simulation_remove_participant",
        )

    if add_participant:
        new_index = len(st.session_state.simulation_participants)
        st.session_state.simulation_participants.append(
            {"role": f"Agent {new_index + 1}", "persona": ""}
        )
        st.session_state[f"simulation_role_{new_index}"] = f"Agent {new_index + 1}"
        st.session_state[f"simulation_persona_{new_index}"] = ""
        st.rerun()

    if remove_participant:
        removed_index = len(st.session_state.simulation_participants) - 1
        st.session_state.simulation_participants.pop()
        st.session_state.pop(f"simulation_role_{removed_index}", None)
        st.session_state.pop(f"simulation_persona_{removed_index}", None)
        st.rerun()

    current_participants: list[dict[str, str]] = []
    for index, participant in enumerate(st.session_state.simulation_participants):
        role_key = f"simulation_role_{index}"
        persona_key = f"simulation_persona_{index}"

        if role_key not in st.session_state:
            st.session_state[role_key] = participant["role"]
        if persona_key not in st.session_state:
            st.session_state[persona_key] = participant["persona"]

        st.markdown(f"**Participant {index + 1}**")
        role_value = st.text_input(
            "Role / title",
            key=role_key,
            help="How the agent should be referenced during the simulation.",
        )
        persona_value = st.text_area(
            "Persona / background",
            key=persona_key,
            height=80,
            help="Optional background context, expertise, or motivations.",
        )
        current_participants.append({"role": role_value, "persona": persona_value})
        st.divider()

    st.session_state.simulation_participants = current_participants

    run_simulation = st.button("Run simulation", use_container_width=True, key="simulation_run_button")

    if run_simulation:
        participants_payload: list[dict[str, str | None]] = []
        normalized_participants: list[dict[str, str]] = []
        for index, participant in enumerate(current_participants):
            role_name = participant["role"].strip()
            persona_text = participant["persona"].strip()
            effective_role = role_name or f"Agent {index + 1}"
            normalized_participants.append({"role": effective_role, "persona": persona_text})
            if effective_role:
                participants_payload.append(
                    {
                        "role": effective_role,
                        "persona": persona_text or None,
                    }
                )

        st.session_state.simulation_participants = normalized_participants

        if len(participants_payload) < 2:
            st.error("Provide at least two participants with distinct roles before running the simulation.")
        else:
            payload = {
                "turns": int(turns),
                "context": context.strip() or None,
                "participants": participants_payload,
            }
            with st.spinner("Running multi-agent simulation..."):
                try:
                    start_response = _start_simulation(payload)
                except requests.RequestException as exc:
                    st.error(f"Simulation failed to start: {exc}")
                else:
                    job_id = start_response.get("job_id")
                    if not job_id:
                        st.error("Simulation did not return a job identifier.")
                    else:
                        try:
                            result = _await_simulation(job_id)
                        except requests.RequestException as exc:
                            st.error(f"Simulation polling failed: {exc}")
                        except TimeoutError as exc:
                            st.error(str(exc))
                        except RuntimeError as exc:
                            st.error(f"Simulation failed: {exc}")
                        else:
                            st.session_state.simulation_result = result
                            st.success(
                                "Simulation complete. Review the transcript and graph below."
                            )

    simulation_result = st.session_state.get("simulation_result")
    if simulation_result:
        st.markdown("---")
        st.subheader("Conversation transcript")
        for message in simulation_result.get("messages", []):
            with st.chat_message(message.get("role", "assistant")):
                st.markdown(message.get("content", ""))

        st.subheader("Proposed knowledge summary")
        st.info(simulation_result.get("summary", ""))

        graph_data = simulation_result.get("graph", {"nodes": [], "edges": []})
        st.subheader("Simulation graph preview")
        if graph_data.get("nodes"):
            _render_graph(graph_data)
        else:
            st.info("Graph preview will appear once the simulation generates messages.")

        with st.expander("Raw simulation data", expanded=False):
            st.json(simulation_result)

        st.markdown("---")
        st.subheader("Merge simulation into an existing session")
        st.caption(
            "Choose which session should receive the simulated messages and knowledge summary."
        )
        target_session_id = st.text_input(
            "Target session ID",
            key="simulation_target_session_id",
            help="Identifier of the existing conversation to update.",
        )
        operator_notes = st.text_area(
            "Optional operator notes",
            key="simulation_operator_notes",
            placeholder="Add context for future reviewers before storing the knowledge node...",
        )
        apply_disabled = not target_session_id.strip()
        apply = st.button(
            "Merge simulation into knowledge graph",
            use_container_width=True,
            disabled=apply_disabled,
            key="simulation_apply_button",
        )
        if apply:
            payload = {
                "target_session_id": target_session_id.strip(),
                "summary": simulation_result.get("summary"),
                "notes": operator_notes.strip() or None,
                "messages": simulation_result.get("messages", []),
            }
            with st.spinner("Persisting simulated knowledge..."):
                try:
                    response = _commit_simulation(payload)
                except requests.RequestException as exc:
                    st.error(f"Failed to merge simulation: {exc}")
                else:
                    st.success(
                        f"Simulation merged successfully. Knowledge node: {response['knowledge_id']}"
                    )
                    with st.expander("Updated short-term snapshot", expanded=False):
                        st.json(response.get("short_term_snapshot", []))


st.set_page_config(page_title="Graph Memory Chatbot", layout="wide")
st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
        }
        .main .block-container {
            padding-top: 1.5rem;
            padding-bottom: 6rem;
            max-width: 1200px;
        }
        div[data-testid="stSidebar"] {
            background-color: #f1f5f9;
        }
        div[data-testid="stSidebar"] > div:first-child {
            padding-top: 1rem;
        }
        div[data-testid="stChatMessage"] {
            background-color: #ffffff !important;
            border-radius: 16px;
            padding: 1rem;
            margin-bottom: 0.75rem;
            border: 1px solid rgba(148, 163, 184, 0.25);
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
        }
        div[data-testid="stChatMessage"] p {
            font-size: 0.95rem;
            line-height: 1.55rem;
        }
        .stTabs [role="tab"] {
            padding: 0.75rem 1.25rem;
        }
        .graph-card {
            background-color: #ffffff;
            padding: 1rem;
            border-radius: 16px;
            box-shadow: 0 16px 40px rgba(15, 23, 42, 0.12);
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧠 Graph Memory Chatbot")
st.caption(
    "Switch between live conversations with the assistant and automated GPT-to-GPT simulations "
    "that can feed the evolving knowledge graph."
)

with st.sidebar:
    st.header("Navigation")
    mode = st.radio(
        "Choose experience",
        options=["User ↔ GPT chat", "GPT ↔ GPT simulation"],
        index=0,
        key="sidebar_mode",
    )
    st.divider()
    st.markdown("**Backend endpoint**")
    st.code(BACKEND_URL, language="bash")

if mode == "User ↔ GPT chat":
    with st.sidebar:
        st.header("Session Controls")
        session_id = st.text_input(
            "Session ID",
            value=st.session_state.get("session_id", "demo"),
            key="chat_session_id",
        )
        st.session_state["session_id"] = session_id
        st.markdown(
            "Use the tools on the right to consolidate conversations into long-term memory or inspect the graph."
        )
    render_chat_page(st.session_state.get("session_id", "demo"))
else:
    with st.sidebar:
        st.header("Simulation helper")
        st.markdown(
            "Configure agent roles and turns, then review the generated graph before merging it into a session."
        )
    render_simulation_page()
