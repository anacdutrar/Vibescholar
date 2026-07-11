"""
VibeScholar – Dashboard Page
==============================
Shows: project selector/creator, document list, grounding score summary.
"""
import time
import httpx
from nicegui import ui
from app.core.logging import logger
from app.ui.components.layout import auth_guard, app_layout
from app.ui import state
from app.ui import api_client as api


def _score_color(score: float) -> str:
    if score >= 0.7:
        return "#22c55e"
    elif score >= 0.4:
        return "#f59e0b"
    return "#ef4444"


_dashboard_refresh_count = 0


def _select_valid_current_project(projects: list[dict]) -> dict:
    current = state.get_current_project()
    current_id = current.get("id") if current else None
    selected = next((project for project in projects if project["id"] == current_id), None)
    if selected:
        state.set_current_project(selected)
        logger.info("dashboard.projects.selected id=%s name=%s", selected.get("id"), selected.get("name"))
        return selected
    if current:
        logger.info("dashboard.projects.selected cleared invalid_current_id=%s", current_id)
        state.set_current_project({})
        state.set_current_document({})
    logger.info("dashboard.projects.selected none")
    return {}


def _project_selector(projects: list[dict], refresh_fn) -> None:
    current = state.get_current_project()
    current_id = current.get("id") if current else None

    with ui.column().style("gap:12px; width:100%;"):
        # Header row
        with ui.row().style("align-items:center; justify-content:space-between; width:100%;"):
            ui.label("Seus Projetos").style("font-size:18px; font-weight:700; color:#f0f2ff;")

            # New project button
            with ui.dialog() as dlg_new_proj, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:380px;"
            ):
                ui.label("Novo Projeto").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:16px;")
                inp_name = ui.input("Nome do projeto").style("width:100%;")
                inp_desc = ui.textarea("Descri??o (opcional)").style("width:100%;")
                lbl_err = ui.label("").style("color:#ef4444; font-size:13px;")
                create_project_running = {"value": False}

                async def create_project():
                    start = time.perf_counter()
                    logger.info("project.create callback start elapsed=%.4f", 0.0)
                    if create_project_running["value"]:
                        logger.warning("project.create duplicate callback ignored elapsed=%.4f", time.perf_counter() - start)
                        return
                    create_project_running["value"] = True
                    btn_create_project.disable()
                    lbl_err.set_text("")
                    try:
                        name = (inp_name.value or "").strip()
                        if not name:
                            lbl_err.set_text("Nome ? obrigat?rio.")
                            return
                        description = (inp_desc.value or "").strip()
                        logger.info(
                            "project.create before api_create_project elapsed=%.4f url=%s",
                            time.perf_counter() - start,
                            f"{api.BASE_URL}/api/projects",
                        )
                        proj = await api.api_create_project_async(state.get_cookies(), name, description)
                        logger.info("project.create before state update elapsed=%.4f", time.perf_counter() - start)
                        state.set_current_project(proj)
                        state.set_current_document({})
                        logger.info("project.create after state update elapsed=%.4f", time.perf_counter() - start)
                        dlg_new_proj.close()
                        logger.info("project.create before visual refresh elapsed=%.4f", time.perf_counter() - start)
                        await refresh_fn()
                        logger.info("project.create after visual refresh elapsed=%.4f", time.perf_counter() - start)
                    except httpx.HTTPStatusError as e:
                        logger.exception(
                            "project.create HTTPStatusError type=%s status=%s body=%s",
                            type(e).__name__,
                            e.response.status_code,
                            e.response.text,
                        )
                        if e.response.status_code == 409:
                            message = "J? existe um projeto com esse nome."
                            lbl_err.set_text(message)
                            ui.notify(message, type="warning")
                        else:
                            lbl_err.set_text(f"Erro: {e.response.status_code}")
                            ui.notify("N?o foi poss?vel criar o projeto.", type="negative")
                    except Exception as e:
                        logger.exception("project.create exception type=%s timeout=%s", type(e).__name__, api.HTTP_TIMEOUT)
                        lbl_err.set_text(f"Erro: {str(e)[:80]}")
                        ui.notify("N?o foi poss?vel criar o projeto.", type="negative")
                    finally:
                        btn_create_project.enable()
                        create_project_running["value"] = False
                        logger.info("project.create callback end elapsed=%.4f", time.perf_counter() - start)

                with ui.row().style("gap:8px; margin-top:16px;"):
                    ui.button("Cancelar", on_click=dlg_new_proj.close).classes("vs-btn-ghost")
                    btn_create_project = ui.button("Criar Projeto", on_click=create_project).classes("vs-btn")

            ui.button("+ Novo Projeto", on_click=dlg_new_proj.open).classes("vs-btn").style("font-size:13px; padding:6px 16px !important;")

        if not projects:
            with ui.element("div").style(
                "text-align:center; padding:40px; background:#1a1d27; border-radius:12px; "
                "border:1px dashed rgba(255,255,255,.1);"
            ):
                ui.label("📂").style("font-size:40px; display:block; margin-bottom:12px;")
                ui.label("Nenhum projeto ainda").style("font-size:16px; font-weight:600; color:#f0f2ff;")
                ui.label("Crie seu primeiro projeto de pesquisa").style("font-size:13px; color:#8b90a0;")
            return

        # Project cards grid
        with ui.grid(columns=3).style("gap:14px; width:100%;"):
            for proj in projects:
                is_active = proj["id"] == current_id
                border = "border-color:#6366f1 !important;" if is_active else ""

                with ui.element("div").style(
                    f"background:#1a1d27; border:1px solid rgba(255,255,255,.08); "
                    f"border-radius:12px; padding:20px; cursor:pointer; transition:all .2s; {border}"
                ) as card:
                    with ui.row().style("justify-content:space-between; align-items:flex-start; margin-bottom:12px;"):
                        with ui.column().style("gap:2px; flex:1; min-width:0;"):
                            ui.label(proj["name"]).style(
                                "font-size:15px; font-weight:700; color:#f0f2ff; "
                                "white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"
                            )
                            ui.label(proj.get("description") or "Sem descrição").style(
                                "font-size:12px; color:#8b90a0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"
                            )
                        if is_active:
                            ui.element("div").style(
                                "width:8px;height:8px;border-radius:50%;background:#22c55e;"
                                "flex-shrink:0; margin-top:4px;"
                            )

                    with ui.row().style("gap:8px; flex-wrap:wrap;"):
                        ui.element("span").classes("vs-chip").add_slot("default", f"<span>🗂️ Ativo</span>")

                    def make_select(p=proj):
                        async def select():
                            state.set_current_project(p)
                            state.set_current_document({})
                            await refresh_fn()
                        return select

                    card.on("click", make_select(proj))


def _document_list(refresh_fn, docs: list[dict] | None = None) -> None:
    project = state.get_current_project()
    if not project:
        with ui.element("div").style(
            "text-align:center; padding:40px; background:#1a1d27; border-radius:12px; border:1px dashed rgba(255,255,255,.1);"
        ):
            ui.label("Selecione um projeto para ver os documentos").style("font-size:14px; color:#8b90a0;")
        return

    docs = docs or []

    with ui.column().style("gap:12px; width:100%;"):
        with ui.row().style("align-items:center; justify-content:space-between; width:100%;"):
            ui.label("Documentos").style("font-size:18px; font-weight:700; color:#f0f2ff;")

            # New document dialog
            with ui.dialog() as dlg_new_doc, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:400px;"
            ):
                ui.label("Novo Documento").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:16px;")
                inp_title = ui.input("Título do documento").style("width:100%;")
                inp_desc2 = ui.textarea("Descrição (opcional)").style("width:100%;")
                lbl_doc_err = ui.label("").style("color:#ef4444; font-size:13px;")

                async def create_doc():
                    lbl_doc_err.set_text("")
                    title = (inp_title.value or "").strip()
                    if not title:
                        lbl_doc_err.set_text("T?tulo ? obrigat?rio.")
                        return
                    try:
                        doc = await api.api_create_document_async(
                            state.get_cookies(), project["id"], title, (inp_desc2.value or "").strip()
                        )
                        state.set_current_document(doc)
                        dlg_new_doc.close()
                        await refresh_fn()
                        ui.navigate.to("/workspace")
                    except Exception as e:
                        logger.exception("dashboard.document.create failed")
                        lbl_doc_err.set_text(f"Erro: {str(e)[:80]}")

                with ui.row().style("gap:8px; margin-top:16px;"):
                    ui.button("Cancelar", on_click=dlg_new_doc.close).classes("vs-btn-ghost")
                    ui.button("Criar Documento", on_click=create_doc).classes("vs-btn")

            with ui.row().style("gap:8px;"):
                ui.button("+ Novo", on_click=dlg_new_doc.open).classes("vs-btn").style("font-size:13px; padding:6px 14px !important;")
                ui.button("Abrir Editor", on_click=lambda: ui.navigate.to("/workspace")).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")

        if not docs:
            with ui.element("div").style(
                "text-align:center; padding:40px; background:#1a1d27; border-radius:12px; border:1px dashed rgba(255,255,255,.1);"
            ):
                ui.label("📄").style("font-size:40px; display:block; margin-bottom:12px;")
                ui.label("Nenhum documento neste projeto").style("font-size:15px; font-weight:600; color:#f0f2ff;")
                ui.label("Crie ou importe um documento para começar").style("font-size:13px; color:#8b90a0;")
            return

        for doc in docs:
            score = doc.get("grounding_score", 0.0)
            color = _score_color(score)
            current_doc = state.get_current_document()
            is_active = current_doc and current_doc.get("id") == doc["id"]
            border = "border-color:#6366f1 !important;" if is_active else ""

            with ui.element("div").style(
                f"background:#1a1d27; border:1px solid rgba(255,255,255,.08); {border} "
                f"border-radius:12px; padding:18px 20px; cursor:pointer; transition:all .2s;"
                "display:flex; align-items:center; gap:16px;"
            ) as row_card:
                # Score ring
                ui.element("div").style(
                    f"width:52px;height:52px;border-radius:50%;display:flex;align-items:center;"
                    f"justify-content:center;font-size:15px;font-weight:700;border:2px solid {color};"
                    f"background:rgba(0,0,0,.2);color:{color};flex-shrink:0;"
                ).add_slot("default", f"<span>{int(score * 100)}%</span>")

                with ui.column().style("flex:1; gap:2px; min-width:0;"):
                    ui.label(doc["title"]).style(
                        "font-size:15px; font-weight:700; color:#f0f2ff; "
                        "white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"
                    )
                    ui.label(doc.get("description") or "Sem descrição").style(
                        "font-size:12px; color:#8b90a0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"
                    )

                ui.icon("chevron_right").style("color:#8b90a0; flex-shrink:0;")

                def make_open(d=doc):
                    def open_doc():
                        state.set_current_document(d)
                        ui.navigate.to("/workspace")
                    return open_doc

                row_card.on("click", make_open(doc))


async def dashboard_page() -> None:
    if not auth_guard():
        return

    container = app_layout("/dashboard", "Dashboard", "Gerencie seus projetos e documentos")

    with container:
        @ui.refreshable
        async def dashboard_content():
            global _dashboard_refresh_count
            _dashboard_refresh_count += 1
            refresh_number = _dashboard_refresh_count
            logger.info("dashboard.visual.refresh start count=%s", refresh_number)
            projects = []
            try:
                projects = await api.api_list_projects_async(state.get_cookies())
            except Exception:
                logger.exception("dashboard.projects.load failed")
                ui.notify("N?o foi poss?vel carregar seus projetos.", type="negative")

            project = _select_valid_current_project(projects)
            docs = []
            if project:
                try:
                    docs = await api.api_list_documents_async(state.get_cookies(), project["id"])
                except Exception:
                    logger.exception("dashboard.documents.count failed project_id=%s", project.get("id"))
                    docs = []
            docs_count = len(docs)

            logger.info(
                "dashboard.counter final projects=%s docs=%s selected_project_id=%s",
                len(projects),
                docs_count,
                project.get("id") if project else None,
            )

            with ui.grid(columns=3).style("gap:16px; width:100%; margin-bottom:28px;"):
                for icon, label, val, color in [
                    ("folder", "Projeto Ativo", project["name"] if project else "?", "#6366f1"),
                    ("description", "Projetos", str(len(projects)), "#22c55e"),
                    ("verified", "Documentos", str(docs_count), "#f59e0b"),
                ]:
                    with ui.element("div").style(
                        f"background:#1a1d27; border:1px solid rgba(255,255,255,.08); "
                        f"border-radius:12px; padding:20px; display:flex; align-items:center; gap:14px;"
                    ):
                        ui.element("div").style(
                            f"width:44px;height:44px;border-radius:10px;background:{color}22;"
                            f"display:flex;align-items:center;justify-content:center;"
                            f"color:{color};font-size:20px;flex-shrink:0;"
                        ).add_slot("default", f'<span class="material-icons">{icon}</span>')
                        with ui.column().style("gap:2px;"):
                            ui.label(label).style("font-size:11px; font-weight:600; color:#8b90a0; letter-spacing:.5px; text-transform:uppercase;")
                            ui.label(val).style("font-size:18px; font-weight:800; color:#f0f2ff;")

            async def refresh():
                logger.info("dashboard.visual.refresh requested")
                await dashboard_content.refresh()

            with ui.grid(columns=2).style("gap:20px; width:100%;"):
                with ui.column().style("gap:0;"):
                    _project_selector(projects, refresh)
                with ui.column().style("gap:0;"):
                    _document_list(refresh, docs)
            logger.info("dashboard.visual.refresh end count=%s", refresh_number)

        await dashboard_content()
