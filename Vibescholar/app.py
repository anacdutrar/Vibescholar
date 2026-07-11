"""
VibeScholar – Root launcher
============================
Usage: python app.py
"""
import os

import uvicorn

if __name__ == "__main__":
    # Import the FastAPI+NiceGUI application
    from app.app import fastapi_app  # noqa: F401  – triggers ui.run_with()
    uvicorn.run(
        "app.app:fastapi_app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        reload=False,
        log_level="info",
    )
