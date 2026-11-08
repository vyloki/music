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

# ZeroGPU Compatibility Handler
try:
    import spaces
    @spaces.GPU
    def _zero_gpu_worker():
        """Satisfies Hugging Face ZeroGPU runtime requirement."""
        return True
except Exception:
    def _zero_gpu_worker():
        return True

try:
    import gradio as gr

    # Minimal dashboard block satisfying Hugging Face Gradio SDK
    with gr.Blocks(title="Wave Music") as demo:
        gr.Markdown(
            "# 🎵 Wave Music Server\n\n"
            "FastAPI backend and audio streaming proxy are active.\n\n"
            "- 🌐 **Web Player**: [Open Wave App](.)\n"
            "- 💚 **System Health**: [/api/health](./api/health)\n"
            "- 📚 **API Docs**: [/docs](./docs)"
        )
        dummy_btn = gr.Button("GPU Check", visible=False)
        dummy_btn.click(fn=_zero_gpu_worker, inputs=[], outputs=[])

    # Mount Gradio at /status so root '/' serves the full Wave SPA directly
    app = gr.mount_gradio_app(app, demo, path="/status")
except ImportError:
    pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
