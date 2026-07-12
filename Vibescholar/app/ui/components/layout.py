"""
VibeScholar – Shared Layout Components
=======================================
Provides: header bar, sidebar navigation, auth guard.
"""
from nicegui import ui
from app.core.logging import logger
from app.ui import state
from app.ui import api_client as api


def auth_guard() -> bool:
    """Redirect to login if not authenticated. Returns True if OK."""
    if not state.is_authenticated():
        ui.navigate.to("/")
        return False
    return True


def _nav_item(icon: str, label: str, href: str, current: str) -> None:
    is_active = current == href
    base = (
        "display:flex; align-items:center; gap:10px; padding:10px 16px; "
        "border-radius:8px; cursor:pointer; font-size:14px; font-weight:500; "
        "transition:all .2s; text-decoration:none; "
    )
    active_style = "background:rgba(99,102,241,.18); color:#6366f1;"
    idle_style = "color:#8b90a0;"
    style = base + (active_style if is_active else idle_style)

    with ui.link(target=href).style(style) as link:
        link.on("mouseover", lambda: None)  # for hover handled via CSS
        ui.icon(icon).style("font-size:18px;")
        ui.label(label)


def sidebar(current_page: str) -> None:
    """Left navigation sidebar."""
    project = state.get_current_project()
    proj_name = project.get("name", "Sem projeto") if project else "Sem projeto"

    with ui.element("aside").style(
        "width:240px; min-height:100vh; background:#161926; "
        "border-right:1px solid rgba(255,255,255,.07); "
        "display:flex; flex-direction:column; padding:20px 12px; flex-shrink:0; gap:4px;"
    ):
        # Brand
        with ui.row().style("align-items:center; gap:10px; padding:8px 8px 20px;"):
            ui.element("div").style(
                "width:34px;height:34px;border-radius:10px;"
                "background:linear-gradient(135deg,#818cf8,#6366f1);"
                "display:flex;align-items:center;justify-content:center;"
                "font-size:16px; flex-shrink:0;"
            ).add_slot("default", "<span>📚</span>")
            ui.label("VibeScholar").style(
                "font-size:16px; font-weight:800; "
                "background:linear-gradient(135deg,#818cf8,#6366f1);"
                "-webkit-background-clip:text; -webkit-text-fill-color:transparent; "
                "background-clip:text;"
            )

        # Current project chip
        if project:
            with ui.element("div").style(
                "background:rgba(99,102,241,.12); border:1px solid rgba(99,102,241,.25); "
                "border-radius:8px; padding:10px 12px; margin-bottom:8px;"
            ).props('id="current-project-chip"'):
                ui.label("PROJETO ATUAL").style("font-size:10px; font-weight:600; color:#8b90a0; letter-spacing:.5px;")
                ui.label(proj_name).style("font-size:13px; font-weight:600; color:#f0f2ff; margin-top:2px;")

        # Navigation
        ui.label("Navegação").style(
            "font-size:10px; font-weight:600; color:#8b90a0; letter-spacing:.5px; "
            "padding:0 8px; margin:8px 0 4px;"
        )
        _nav_item("dashboard", "Dashboard", "/dashboard", current_page)
        _nav_item("edit_note", "Editor", "/workspace", current_page)
        _nav_item("library_books", "Biblioteca", "/references", current_page)

        # Spacer
        ui.element("div").style("flex:1;")

        # User info + logout
        user = state.get_user()
        username = user.get("username", "Usuário") if user else "Usuário"

        ui.separator().style("border-color:rgba(255,255,255,.07); margin:8px 0;")
        with ui.row().style("align-items:center; gap:8px; padding:0 8px;"):
            ui.element("div").style(
                "width:32px;height:32px;border-radius:50%;"
                "background:linear-gradient(135deg,#818cf8,#6366f1);"
                "display:flex;align-items:center;justify-content:center;"
                "font-size:14px; font-weight:700; color:#fff; flex-shrink:0;"
            ).add_slot("default", f"<span>{username[0].upper()}</span>")
            with ui.column().style("gap:0; flex:1; min-width:0;"):
                ui.label(username).style("font-size:13px; font-weight:600; color:#f0f2ff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")
                ui.label("Online").style("font-size:11px; color:#22c55e;")

        async def do_logout():
            try:
                await api.api_logout_async(state.get_cookies())
            except Exception:
                logger.exception("Logout request failed; clearing local session anyway")
            finally:
                state.clear_session()
                ui.navigate.to("/")

        ui.button("Sair", icon="logout", on_click=do_logout).style(
            "width:100%; background:transparent; color:#8b90a0; border:1px solid rgba(255,255,255,.07); "
            "border-radius:8px; font-size:13px; margin-top:8px;"
        )


def page_header(title: str, subtitle: str = "") -> None:
    """Top content header (below nav, above content)."""
    with ui.row().style("align-items:flex-end; justify-content:space-between; margin-bottom:28px; flex-wrap:wrap; gap:12px;"):
        with ui.column().style("gap:2px;"):
            ui.label(title).style("font-size:26px; font-weight:800; color:#f0f2ff;")
            if subtitle:
                ui.label(subtitle).style("font-size:14px; color:#8b90a0;")


def app_layout(current_page: str, title: str, subtitle: str = ""):
    """
    Context-manager-like function that renders sidebar + main content wrapper.
    Usage:
        with app_layout("/dashboard", "Dashboard"):
            ...your content...
    Returns the main content container so you can use `with`.
    """
    from app.ui.styles import GLOBAL_CSS
    ui.add_head_html(GLOBAL_CSS)

    with ui.row().style("width:100%; min-height:100vh; gap:0; background:#0f1117;"):
        sidebar(current_page)
        content = ui.column().style("flex:1; padding:32px 36px; overflow-y:auto; min-width:0;")
        with content:
            page_header(title, subtitle)
        return content
