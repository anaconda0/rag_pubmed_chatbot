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
:root {
    --page-bg: #f6f7f9;
    --panel-bg: #ffffff;
    --panel-border: #d8dee6;
    --text-main: #1f2937;
    --text-muted: #64748b;
    --accent: #0f766e;
    --accent-dark: #115e59;
    --accent-soft: #e6f4f1;
    --source-soft: #fff7ed;
    --source-border: #fed7aa;
}

body,
.gradio-container {
    background: var(--page-bg) !important;
    color: var(--text-main) !important;
}

.gradio-container label,
.gradio-container span,
.gradio-container p,
.gradio-container li,
.gradio-container h1,
.gradio-container h2,
.gradio-container h3,
.gradio-container h4,
.gradio-container textarea,
.gradio-container input {
    color: var(--text-main) !important;
}

.gradio-container textarea,
.gradio-container input {
    background: #ffffff !important;
    caret-color: var(--text-main) !important;
}

.app-shell {
    max-width: 1480px;
    margin: 0 auto;
    padding: 18px 20px 22px;
}

.app-header {
    border: 1px solid var(--panel-border);
    border-left: 5px solid var(--accent);
    background: var(--panel-bg);
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 14px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

.app-header h1 {
    margin: 0 0 4px;
    font-size: 28px;
    line-height: 1.2;
    letter-spacing: 0;
    color: var(--text-main);
}

.app-header p {
    margin: 0;
    color: var(--text-muted);
    font-size: 14px;
}

.main-column,
.side-column {
    gap: 12px;
}

#chatbot {
    border: 1px solid #334155;
    border-radius: 8px;
    background: #0f172a !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

#chatbot *,
#chatbot p,
#chatbot li,
#chatbot span,
#chatbot .prose,
#chatbot .message,
#chatbot .message-content {
    color: #f8fafc !important;
}

#chatbot button,
#chatbot button * {
    color: #f8fafc !important;
}

#chatbot [class*="message"],
#chatbot [class*="bubble"],
#chatbot [data-testid*="message"] {
    border-color: #334155 !important;
}

#chatbot [class*="user"],
#chatbot [data-testid*="user"] {
    background: #334155 !important;
    color: #f8fafc !important;
}

#chatbot [class*="bot"],
#chatbot [class*="assistant"],
#chatbot [data-testid*="bot"],
#chatbot [data-testid*="assistant"] {
    background: #111827 !important;
    color: #f8fafc !important;
}

#question_box textarea {
    border: 1px solid var(--panel-border) !important;
    border-radius: 8px !important;
    background: #ffffff !important;
}

#question_box textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.12) !important;
}

#send_button,
#clear_button,
#new_session_button {
    border-radius: 8px !important;
    min-height: 42px;
    font-weight: 600;
}

#send_button {
    background: var(--accent) !important;
    border-color: var(--accent) !important;
    color: #ffffff !important;
}

#send_button * {
    color: #ffffff !important;
}

#send_button:hover {
    background: var(--accent-dark) !important;
    border-color: var(--accent-dark) !important;
}

#clear_button,
#new_session_button {
    background: #ffffff !important;
    border: 1px solid var(--panel-border) !important;
    color: var(--text-main) !important;
}

#clear_button:hover,
#new_session_button:hover {
    background: var(--accent-soft) !important;
    border-color: #99d4cb !important;
}

#session_box textarea {
    background: var(--accent-soft) !important;
    border: 1px solid #b7e3dc !important;
    color: var(--accent-dark) !important;
    font-family: Consolas, Menlo, monospace;
    font-size: 13px;
}

#sources_panel,
#prompt_history_panel {
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    background: var(--panel-bg);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

#sources_panel {
    max-height: 390px;
    overflow-y: auto;
    color: var(--text-main) !important;
}

#sources_panel * {
    color: var(--text-main) !important;
}

#sources_panel h3 {
    color: var(--accent-dark);
    margin-top: 0;
}

#sources_panel code {
    background: var(--source-soft);
    border: 1px solid var(--source-border);
    border-radius: 6px;
    padding: 1px 5px;
    color: #7c2d12 !important;
}

#prompt_history_panel textarea {
    background: #fbfcfd !important;
    border: 1px solid var(--panel-border) !important;
    color: #111827 !important;
    min-height: 420px !important;
}

.compact-panel textarea {
    font-family: Consolas, Menlo, monospace;
    font-size: 13px;
    line-height: 1.45;
}

.tabs {
    border-radius: 8px;
}

footer {
    display: none !important;
}
"""


def build_theme() -> gr.Theme:
    """Create a simple, clean Gradio theme."""

    return gr.themes.Soft(
        primary_hue="teal",
        neutral_hue="slate",
        radius_size="sm",
        spacing_size="sm",
        text_size="md",
    )


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
            gr.Markdown(
                """
                # PubMed RAG Chatbot
                Evidence-focused medical abstract search
                """,
                elem_classes=["app-header"],
            )

            with gr.Row():
                with gr.Column(scale=3, elem_classes=["main-column"]):
                    chatbot = gr.Chatbot(
                        label="Chat",
                        height=560,
                        layout="bubble",
                        show_label=True,
                        elem_id="chatbot",
                    )

                    with gr.Row():
                        question_box = gr.Textbox(
                            label="Question",
                            placeholder="Ask about the ingested PubMed abstracts",
                            lines=2,
                            max_lines=5,
                            autofocus=True,
                            scale=8,
                            elem_id="question_box",
                        )
                        send_button = gr.Button(
                            "Send",
                            variant="primary",
                            scale=1,
                            elem_id="send_button",
                        )

                    with gr.Row():
                        clear_button = gr.Button("Clear", elem_id="clear_button")
                        new_session_button = gr.Button(
                            "New Session",
                            elem_id="new_session_button",
                        )

                with gr.Column(scale=2, elem_classes=["side-column"]):
                    session_id_box = gr.Textbox(
                        label="Session",
                        interactive=False,
                        elem_id="session_box",
                    )

                    with gr.Tabs(elem_classes=["tabs"]):
                        with gr.Tab("Sources"):
                            sources_panel = gr.Markdown(
                                value=EMPTY_SOURCES_TEXT,
                                label="Sources",
                                elem_id="sources_panel",
                            )
                        with gr.Tab("Prompt History"):
                            prompt_history_panel = gr.Textbox(
                                value=EMPTY_PROMPT_HISTORY_TEXT,
                                label="Prompt History",
                                lines=18,
                                interactive=False,
                                elem_id="prompt_history_panel",
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


def launch_app(app: gr.Blocks | None = None) -> None:
    """Launch the Gradio app with the UI theme and custom CSS."""

    demo = app or create_app()
    demo.launch(theme=build_theme(), css=APP_CSS)
