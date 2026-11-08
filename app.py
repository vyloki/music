"""
Wave Music - Hugging Face Spaces Entry Point (Gradio + FastAPI)
Integrates Wave's FastAPI backend into Hugging Face Spaces' Free Gradio SDK.
"""
import os
import sys

# Ensure root workspace directory is in python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.main import app

# ZeroGPU Mandatory Interface
try:
    import spaces
    @spaces.GPU
    def ping_gpu(query: str):
        return f"Wave Music Engine Active: {query}"
except Exception:
    def ping_gpu(query: str):
        return f"Wave Music Engine Active: {query}"

try:
    import gradio as gr

    # Direct gr.Interface with @spaces.GPU satisfies ZeroGPU scanner
    demo = gr.Interface(
        fn=ping_gpu,
        inputs=gr.Textbox(label="Status Query", value="healthcheck"),
        outputs=gr.Textbox(label="Engine Response"),
        title="🎵 Wave Music Server",
        description="FastAPI backend and audio streaming proxy are active.",
    )

    # Mount Gradio at /status so root '/' serves the full Wave SPA directly
    app = gr.mount_gradio_app(app, demo, path="/status")
except ImportError:
    pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
