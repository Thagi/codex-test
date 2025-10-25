"""Streamlit front-end for the adaptive chatbot."""
from __future__ import annotations

import json
import os
from typing import List

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


def _render_graph(graph_data: dict) -> None:
    network = Network(height="500px", width="100%", bgcolor="#ffffff", directed=True)
    for node in graph_data.get("nodes", []):
        network.add_node(
            node["id"],
            label=node.get("label", node["id"]),
            title=json.dumps(node.get("metadata", {}), indent=2),
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
st.title("🧠 Graph Memory Chatbot")

with st.sidebar:
    st.header("Session Controls")
    session_id = st.text_input("Session ID", value=st.session_state.get("session_id", "demo"))
    st.session_state["session_id"] = session_id
    st.markdown("Backend endpoint: `%s`" % BACKEND_URL)

def _refresh_graph() -> None:
    try:
        st.session_state.graph_data = _load_graph()
        st.session_state.graph_error = None
    except requests.RequestException as exc:
        st.session_state.graph_error = str(exc)


if "messages" not in st.session_state:
    st.session_state.messages = []
if "graph_data" not in st.session_state:
    st.session_state.graph_data = {"nodes": [], "edges": []}
if "graph_error" not in st.session_state:
    st.session_state.graph_error = None
if "graph_initialized" not in st.session_state:
    _refresh_graph()
    st.session_state.graph_initialized = True
if "consolidate_feedback" not in st.session_state:
    st.session_state.consolidate_feedback = None

main_col, side_col = st.columns((3, 2), gap="large")

with main_col:
    st.subheader("Conversation")
    if st.session_state.messages:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])
    else:
        st.info("Start the conversation using the input below.")

    st.divider()
    st.subheader("Short-term Memory Snapshot")
    try:
        short_term_history = requests.get(
            f"{BACKEND_URL}/memory/{session_id}", timeout=30
        )
        if short_term_history.ok:
            history_payload: List[dict] = short_term_history.json()
            if history_payload:
                table_rows = [
                    {
                        "Role": msg.get("role", ""),
                        "Content": msg.get("content", ""),
                        "Timestamp": msg.get("timestamp", ""),
                    }
                    for msg in history_payload
                ]
                st.dataframe(table_rows, use_container_width=True)
            else:
                st.info("No short-term memory yet for this session.")
        else:
            st.warning("Could not load short-term history from the backend.")
    except requests.RequestException as exc:
        st.warning(f"History unavailable: {exc}")

with side_col:
    st.subheader("Memory Actions")
    st.caption("Generate a long-term knowledge node from the latest chat history.")
    consolidate_notes = st.text_area(
        "Consolidation notes", height=120, key="consolidate_notes"
    )
    if st.button(
        "Trigger Long-term Update", use_container_width=True, key="consolidate_btn"
    ):
        try:
            result = _trigger_consolidation(session_id, consolidate_notes or None)
            st.session_state.consolidate_feedback = ("success", result)
            _refresh_graph()
        except requests.RequestException as exc:
            st.session_state.consolidate_feedback = ("error", str(exc))

    feedback = st.session_state.get("consolidate_feedback")
    if feedback:
        status, payload = feedback
        if status == "success":
            st.success(f"Knowledge node created: {payload['knowledge_id']}")
            st.info(payload["summary"])
        else:
            st.error(f"Failed to consolidate: {payload}")

    st.divider()
    st.subheader("Graph View")
    if st.button(
        "Refresh Graph View", use_container_width=True, key="refresh_graph_btn"
    ):
        _refresh_graph()

    if st.session_state.graph_error:
        st.warning(f"Graph unavailable: {st.session_state.graph_error}")
    elif st.session_state.graph_data.get("nodes"):
        _render_graph(st.session_state.graph_data)
    else:
        st.info("Graph will appear after interactions are stored.")

user_input = st.chat_input("Send a message", key="chat_input")

if user_input:
    try:
        response = _send_message(session_id, user_input)
        st.session_state.messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in response.get("short_term_snapshot", [])
        ]
        _refresh_graph()
        st.rerun()
    except requests.RequestException as exc:
        st.error(f"Failed to send message: {exc}")
