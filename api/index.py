"""
Wave Music - Vercel Serverless Function Entry Point
Exposes the FastAPI 'app' instance for Vercel's Python runtime.
"""
import sys
import os

# Add root directory to sys.path so 'app.*' imports resolve cleanly
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.main import app

