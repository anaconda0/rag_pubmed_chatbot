"""Application entry point.

This file only launches the Gradio app. The UI is defined in ui/gradio_ui.py,
and the RAG logic stays inside src/.
"""

from ui.gradio_ui import create_app


app = create_app()


if __name__ == "__main__":
    app.launch()
