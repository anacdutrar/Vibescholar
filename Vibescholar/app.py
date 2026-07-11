"""
VibeScholar – Root launcher
============================
Usage: python app.py
"""
import uvicorn

if __name__ == "__main__":
    # Import the FastAPI+NiceGUI application
    from app.app import fastapi_app  # noqa: F401  – triggers ui.run_with()
    uvicorn.run(
        "app.app:fastapi_app",
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_level="info",
    )
