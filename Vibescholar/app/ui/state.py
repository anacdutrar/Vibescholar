"""
VibeScholar – Shared UI State & Session Store
=============================================
Provides a centralised, per-user app.storage.user namespace wrapper
so all NiceGUI pages can read/write session data safely. h
"""
from nicegui import app as ngapp


# ── helpers ──────────────────────────────────────────────────────────────────

def get_cookies() -> dict:
    return ngapp.storage.user.get("cookies", {})

def set_cookies(cookies: dict) -> None:
    ngapp.storage.user["cookies"] = cookies

def get_user() -> dict:
    return ngapp.storage.user.get("user", {})

def set_user(user: dict) -> None:
    ngapp.storage.user["user"] = user

def is_authenticated() -> bool:
    return bool(ngapp.storage.user.get("cookies"))

def get_current_project() -> dict:
    return ngapp.storage.user.get("current_project", {})

def set_current_project(project: dict) -> None:
    ngapp.storage.user["current_project"] = project

def get_current_document() -> dict:
    return ngapp.storage.user.get("current_document", {})

def set_current_document(doc: dict) -> None:
    ngapp.storage.user["current_document"] = doc

def clear_project_context(project_id: int | None = None) -> bool:
    current = get_current_project()
    if project_id is not None and current.get("id") != project_id:
        return False
    set_current_project({})
    set_current_document({})
    return True

def clear_session() -> None:
    ngapp.storage.user.clear()
