"""
VibeScholar – FastAPI + NiceGUI Application Entry Point
========================================================
All NiceGUI page routes are registered here.
Run via: python app.py
"""
import logging
from fastapi import FastAPI
from nicegui import app as ngapp, ui

from app.core.config import settings
from app.core.logging import logger
from app.main_db import init_db
from app.routers import auth, projects, documents, references, grounding

# ─── FastAPI setup ────────────────────────────────────────────────────────────
fastapi_app = FastAPI(
    title=settings.PROJECT_NAME,
    description="VibeScholar Scientific Writing Grounding Platform",
    version="1.0.0",
)

# Register API routers
fastapi_app.include_router(auth.router)
fastapi_app.include_router(projects.router)
fastapi_app.include_router(documents.router)
fastapi_app.include_router(references.router)
fastapi_app.include_router(grounding.router)


@fastapi_app.on_event("startup")
def on_startup():
    logger.info("Starting up VibeScholar…")
    try:
        init_db()
    except Exception as e:
        logger.error(f"DB init failed: {e}")


@fastapi_app.get("/api/health")
def health_check():
    return {"status": "healthy", "project": settings.PROJECT_NAME}


# ─── NiceGUI pages ───────────────────────────────────────────────────────────

# Import page functions (deferred to avoid circular imports at module load)

@ui.page("/")
def page_login():
    from app.ui import state
    if state.is_authenticated():
        ui.navigate.to("/dashboard")
        return
    from app.ui.pages.login import login_page
    login_page()


@ui.page("/dashboard")
async def page_dashboard():
    from app.ui.pages.dashboard import dashboard_page
    await dashboard_page()


@ui.page("/workspace")
async def page_workspace():
    from app.ui.pages.workspace import workspace_page
    await workspace_page()


@ui.page("/references")
async def page_references():
    from app.ui.pages.references import references_page
    await references_page()


# ─── NiceGUI ↔ FastAPI binding ───────────────────────────────────────────────
ui.run_with(
    fastapi_app,
    storage_secret=settings.SECRET_KEY,
    title=settings.PROJECT_NAME,
    favicon="📚",
)
