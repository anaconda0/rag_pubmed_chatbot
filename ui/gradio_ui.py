"""Gradio interface for the PubMed RAG chatbot.

The UI calls src.rag_chain.run_rag_pipeline() and does not contain retrieval,
embedding, MongoDB, or memory logic.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
import time
import uuid
from typing import Any

import gradio as gr

from src.memory_manager import ChatMemoryManager
from src.rag_chain import run_rag_pipeline


EMPTY_SOURCES_TEXT = "No sources retrieved yet."
EMPTY_PROMPT_HISTORY_TEXT = "No prompts yet."


APP_CSS = """
.app-shell {
    max-width: 1400px;
    margin: 0 auto;
}
.compact-panel textarea {
    font-family: Consolas, Menlo, monospace;
    font-size: 13px;
}
"""


def create_session_state() -> dict[str, Any]:
    """Create a new chat session.

    Each session gets its own ChatMemoryManager. Short-term memory lives inside
    that manager. Long-term memory is stored in MongoDB with the session id.
    """

    session_id = uuid.uuid4().hex[:12]
    return {
        "session_id": session_id,
        "memory_manager": ChatMemoryManager(session_id=session_id),
        "prompt_history": [],
    }


def ensure_session_state(session_state: dict[str, Any] | None) -> dict[str, Any]:
    """Return a valid session state, creating one if needed."""

    if not isinstance(session_state, dict):
        return create_session_state()

    if "session_id" not in session_state or "memory_manager" not in session_state:
        return create_session_state()

    if "prompt_history" not in session_state:
        session_state["prompt_history"] = []

    return session_state


def truncate_text(text: str, max_length: int = 900) -> str:
    """Shorten long text for the sources panel."""

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def format_sources(chunks: list[dict[str, Any]]) -> str:
    """Format retrieved chunks for display in the UI."""

    if not chunks:
        return EMPTY_SOURCES_TEXT

    sections = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.get("metadata", {})
        title = metadata.get("title") or "Unknown title"
        pmid = metadata.get("pmid") or "Unknown PMID"
        row_index = metadata.get("row_index")
        chunk_index = metadata.get("chunk_index")
        score = chunk.get("score", 0.0)
        text = truncate_text(chunk.get("text", ""))

        sections.append(
            f"### Source {index}\n"
            f"- Score: `{score:.4f}`\n"
            f"- PMID: `{pmid}`\n"
            f"- Row: `{row_index}` | Chunk: `{chunk_index}`\n"
            f"- Title: {title}\n\n"
            f"{text}"
        )

    return "\n\n---\n\n".join(sections)


def format_prompt_history(prompt_history: list[dict[str, str]]) -> str:
    """Format prompts generated during the current UI session."""

    if not prompt_history:
        return EMPTY_PROMPT_HISTORY_TEXT

    sections = []
    for index, item in enumerate(prompt_history, start=1):
        sections.append(
            f"Prompt {index}\n"
            f"Time: {item['time']}\n"
            f"Question: {item['question']}\n\n"
            f"{item['prompt']}"
        )

    return "\n\n" + ("=" * 90 + "\n\n").join(sections)


def stream_text(text: str, chunk_size: int = 12) -> Generator[str, None, None]:
    """Yield small pieces of text to create a streaming effect."""

    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]
        time.sleep(0.02)


def initialize_ui() -> tuple[
    list[dict[str, str]],
    str,
    str,
    str,
    dict[str, Any],
]:
    """Initialize a fresh UI session when the page opens."""

    session_state = create_session_state()
    return (
        [],
        EMPTY_SOURCES_TEXT,
        EMPTY_PROMPT_HISTORY_TEXT,
        session_state["session_id"],
        session_state,
    )


def submit_question(
    question: str,
    chat_history: list[dict[str, str]] | None,
    session_state: dict[str, Any] | None,
) -> Generator[
    tuple[
        list[dict[str, str]],
        str,
        str,
        str,
        str,
        dict[str, Any],
    ],
    None,
    None,
]:
    """Handle one user question and stream the assistant response."""

    session_state = ensure_session_state(session_state)
    chat_history = chat_history or []
    question = (question or "").strip()

    if not question:
        yield (
            chat_history,
            "",
            EMPTY_SOURCES_TEXT,
            format_prompt_history(session_state["prompt_history"]),
            session_state["session_id"],
            session_state,
        )
        return

    chat_history = chat_history + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": "Retrieving relevant PubMed chunks..."},
    ]

    yield (
        chat_history,
        "",
        "Retrieving sources...",
        format_prompt_history(session_state["prompt_history"]),
        session_state["session_id"],
        session_state,
    )

    try:
        result = run_rag_pipeline(
            question,
            memory_manager=session_state["memory_manager"],
            save_to_memory=True,
        )

        sources_text = format_sources(result["dataset_chunks"])
        session_state["prompt_history"].append(
            {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "question": question,
                "prompt": result["prompt"],
            }
        )
        prompt_history_text = format_prompt_history(session_state["prompt_history"])

        chat_history[-1]["content"] = ""
        for text_piece in stream_text(result["answer"]):
            chat_history[-1]["content"] += text_piece
            yield (
                chat_history,
                "",
                sources_text,
                prompt_history_text,
                session_state["session_id"],
                session_state,
            )

    except Exception as exc:
        chat_history[-1]["content"] = f"Error: {exc}"
        yield (
            chat_history,
            "",
            EMPTY_SOURCES_TEXT,
            format_prompt_history(session_state["prompt_history"]),
            session_state["session_id"],
            session_state,
        )


def clear_current_session(
    session_state: dict[str, Any] | None,
) -> tuple[
    list[dict[str, str]],
    str,
    str,
    str,
    str,
    dict[str, Any],
]:
    """Clear the visible chat and short-term memory for this session."""

    session_state = ensure_session_state(session_state)
    session_state["memory_manager"].clear_short_term_memory()
    session_state["prompt_history"] = []

    return (
        [],
        "",
        EMPTY_SOURCES_TEXT,
        EMPTY_PROMPT_HISTORY_TEXT,
        session_state["session_id"],
        session_state,
    )


def start_new_session() -> tuple[
    list[dict[str, str]],
    str,
    str,
    str,
    str,
    dict[str, Any],
]:
    """Create a completely new session id and memory manager."""

    session_state = create_session_state()
    return (
        [],
        "",
        EMPTY_SOURCES_TEXT,
        EMPTY_PROMPT_HISTORY_TEXT,
        session_state["session_id"],
        session_state,
    )


def create_app() -> gr.Blocks:
    """Build and return the Gradio application."""

    with gr.Blocks(
        title="PubMed RAG Chatbot",
        fill_height=True,
    ) as demo:
        session_state = gr.State(value=None)

        with gr.Column(elem_classes=["app-shell"]):
            gr.Markdown("# PubMed RAG Chatbot")

            with gr.Row():
                with gr.Column(scale=3):
                    chatbot = gr.Chatbot(
                        label="Chat",
                        height=560,
                        layout="bubble",
                        show_label=True,
                    )

                    with gr.Row():
                        question_box = gr.Textbox(
                            label="Question",
                            placeholder="Ask about the ingested PubMed abstracts",
                            lines=2,
                            max_lines=5,
                            autofocus=True,
                            scale=8,
                        )
                        send_button = gr.Button(
                            "Send",
                            variant="primary",
                            scale=1,
                        )

                    with gr.Row():
                        clear_button = gr.Button("Clear")
                        new_session_button = gr.Button("New Session")

                with gr.Column(scale=2):
                    session_id_box = gr.Textbox(
                        label="Session",
                        interactive=False,
                    )
                    sources_panel = gr.Markdown(
                        value=EMPTY_SOURCES_TEXT,
                        label="Sources",
                    )
                    prompt_history_panel = gr.Textbox(
                        value=EMPTY_PROMPT_HISTORY_TEXT,
                        label="Prompt History",
                        lines=18,
                        interactive=False,
                        elem_classes=["compact-panel"],
                    )

        demo.load(
            fn=initialize_ui,
            outputs=[
                chatbot,
                sources_panel,
                prompt_history_panel,
                session_id_box,
                session_state,
            ],
        )

        submit_outputs = [
            chatbot,
            question_box,
            sources_panel,
            prompt_history_panel,
            session_id_box,
            session_state,
        ]

        question_box.submit(
            fn=submit_question,
            inputs=[question_box, chatbot, session_state],
            outputs=submit_outputs,
        )
        send_button.click(
            fn=submit_question,
            inputs=[question_box, chatbot, session_state],
            outputs=submit_outputs,
        )
        clear_button.click(
            fn=clear_current_session,
            inputs=[session_state],
            outputs=submit_outputs,
        )
        new_session_button.click(
            fn=start_new_session,
            outputs=submit_outputs,
        )

    return demo.queue()
