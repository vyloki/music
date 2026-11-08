#!/usr/bin/env python3
"""
Wave — Quick Start Script
Run this to start the Wave music app server.

Usage:
    python run.py
"""

import os
import sys
import uvicorn
from app.config import settings


def main():
    """Start the Wave server."""
    default_port = "7860" if "SPACE_ID" in os.environ else str(settings.port)
    port = int(os.environ.get("PORT", default_port))
    host = os.environ.get("HOST", settings.host)
    debug = settings.debug if "DEBUG" not in os.environ else os.environ.get("DEBUG", "false").lower() in ("1", "true", "yes")

    print()
    print("  🎵  W A V E  ")
    print("  ─────────────────────────")
    print("  Your Personal Music App")
    print(f"  Version {settings.app_version}")
    print()
    print(f"  🌐  http://{host}:{port}")
    print(f"  📚  http://{host}:{port}/docs")
    print()

    try:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=debug,
            log_level="debug" if debug else "info",
        )
    except KeyboardInterrupt:
        print("\n👋 Wave server stopped by user (Ctrl+C).")
        try:
            sys.exit(0)
        except SystemExit:
            pass


if __name__ == "__main__":
    main()
