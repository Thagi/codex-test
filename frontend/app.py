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

chat_container = st.container()
input_col, action_col = st.columns([3, 1])

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

with chat_container:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

with input_col:
    user_input = st.chat_input("Send a message", key="chat_input")

with action_col:
    st.markdown("### Actions")
    consolidate_notes = st.text_area("Consolidation notes", height=120)
    if st.button("Trigger Long-term Update", use_container_width=True):
        try:
            result = _trigger_consolidation(session_id, consolidate_notes or None)
            st.success(f"Knowledge node created: {result['knowledge_id']}")
            st.info(result["summary"])
            _refresh_graph()
        except requests.RequestException as exc:
            st.error(f"Failed to consolidate: {exc}")

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

st.subheader("Conversation State")
try:
    short_term_history = requests.get(f"{BACKEND_URL}/memory/{session_id}", timeout=30)
    if short_term_history.ok:
        messages: List[dict] = short_term_history.json()
        st.json(messages)
    else:
        st.warning("Could not load short-term history")
except requests.RequestException as exc:
    st.warning(f"History unavailable: {exc}")

st.subheader("Graph View")
_refresh = st.button("Refresh Graph View")
if _refresh or "graph_data" not in st.session_state:
    try:
        _refresh_graph()
    except requests.RequestException as exc:
        st.error(f"Failed to load graph: {exc}")

if st.session_state.get("graph_data"):
    _render_graph(st.session_state["graph_data"])
else:
    st.info("Graph will appear after interactions are stored.")
