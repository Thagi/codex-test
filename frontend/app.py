"""Streamlit front-end for the adaptive chatbot."""
from __future__ import annotations

import json
import os

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
    st.components.v1.html(html, height=520)


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
st.caption("Interact with the assistant while tracking how memory evolves over time.")

with st.sidebar:
    st.header("Session Controls")
    session_id = st.text_input("Session ID", value=st.session_state.get("session_id", "demo"))
    st.session_state["session_id"] = session_id
    st.divider()
    st.markdown("**Backend endpoint**")
    st.code(BACKEND_URL, language="bash")
    st.markdown(
        "Use the tools on the right to consolidate conversations into long-term memory or inspect the graph."
    )

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

user_input = st.chat_input(f"Message for session '{session_id}'", key="chat_input")

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
                    st.session_state.graph_data = {"nodes": [], "edges": []}
                    st.rerun()
