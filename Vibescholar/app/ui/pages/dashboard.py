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


async def _read_upload_file(uploaded_file) -> tuple[str, bytes]:
    return uploaded_file.name, await uploaded_file.read()


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


def _project_selector(
    projects: list[dict], refresh_fn, open_delete_dialog, restored_project_names: set[str]
) -> None:
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
                inp_desc = ui.textarea("Descrição (opcional)").style("width:100%;")
                lbl_err = ui.label("").style("color:#ef4444; font-size:13px;")
                create_project_running = {"value": False}

                async def create_project():
                    start = time.perf_counter()
                    refresh_started = False
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
                            lbl_err.set_text("Nome é obrigatório.")
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
                        if name in restored_project_names:
                            restored_project_names.discard(name)
                            ui.notify("Projeto restaurado com sucesso.", type="positive")
                        else:
                            ui.notify("Projeto criado com sucesso.", type="positive")
                        dlg_new_proj.close()
                        logger.info("project.create before visual refresh elapsed=%.4f", time.perf_counter() - start)
                        create_project_running["value"] = False
                        refresh_started = True
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
                            message = "Já existe um projeto com esse nome."
                            lbl_err.set_text(message)
                            ui.notify(message, type="warning")
                        else:
                            lbl_err.set_text(f"Erro: {e.response.status_code}")
                            ui.notify("Não foi possível criar o projeto.", type="negative")
                    except Exception as e:
                        logger.exception("project.create exception type=%s timeout=%s", type(e).__name__, api.HTTP_TIMEOUT)
                        lbl_err.set_text(f"Erro: {str(e)[:80]}")
                        ui.notify("Não foi possível criar o projeto.", type="negative")
                    finally:
                        if not refresh_started:
                            btn_create_project.enable()
                        create_project_running["value"] = False
                        logger.info("project.create callback end elapsed=%.4f", time.perf_counter() - start)

                with ui.row().style("gap:8px; margin-top:16px;"):
                    ui.button("Cancelar", on_click=dlg_new_proj.close).classes("vs-btn-ghost")
                    btn_create_project = ui.button("Criar Projeto", on_click=create_project).classes("vs-btn")

            ui.button("+NOVO/RESTAURAR PROJETO", on_click=dlg_new_proj.open).classes("vs-btn").style("font-size:13px; padding:6px 16px !important;")

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

                    def make_delete(p=proj):
                        def open_delete():
                            open_delete_dialog(p)
                        return open_delete

                    ui.button("Excluir projeto", on_click=make_delete(proj)).props("onclick=event.stopPropagation()").classes("vs-btn-danger").style("font-size:12px; padding:4px 10px !important;")


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
                        lbl_doc_err.set_text("Título é obrigatório.")
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
                with ui.dialog() as dlg_import_doc, ui.card().style(
                    "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:420px;"
                ):
                    ui.label("Importar documento").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:4px;")
                    ui.label("Formatos suportados: .docx · .md · .txt").style("font-size:13px; color:#8b90a0; margin-bottom:20px;")
                    inp_imp_title = ui.input("Título do documento").style("width:100%;")
                    upload = ui.upload(
                        label="Selecionar arquivo",
                        auto_upload=True,
                        multiple=False,
                        max_files=1,
                        max_file_size=20_000_000,
                        on_rejected=lambda: lbl_imp_err.set_text("Arquivo inválido. Use .docx, .md ou .txt."),
                    ).props('accept=".docx,.md,.txt"').classes("vs-upload-dark").style("width:100%; margin-top:12px;")
                    selected_file_label = ui.label("Nenhum arquivo selecionado").style("color:#8b90a0; font-size:12px;")
                    lbl_imp_err = ui.label("").style("color:#ef4444; font-size:13px;")
                    file_data = {"name": None, "content": None}

                    async def handle_upload(e):
                        filename = e.file.name
                        if not filename.lower().endswith((".docx", ".md", ".txt")):
                            file_data["name"] = None
                            file_data["content"] = None
                            selected_file_label.set_text("Nenhum arquivo selecionado")
                            lbl_imp_err.set_text("Arquivo inválido. Use .docx, .md ou .txt.")
                            upload.reset()
                            return
                        try:
                            filename, content = await _read_upload_file(e.file)
                        except Exception as exc:
                            logger.exception("dashboard.document.import upload read failed")
                            lbl_imp_err.set_text(f"Erro ao ler arquivo: {str(exc)[:80]}")
                            return
                        file_data["name"] = filename
                        file_data["content"] = content
                        selected_file_label.set_text(f"{filename} ({len(content)} bytes)")
                        lbl_imp_err.set_text("")
                        upload.reset()

                    upload.on_upload(handle_upload)

                    async def do_import():
                        lbl_imp_err.set_text("")
                        title = (inp_imp_title.value or "").strip()
                        if not title:
                            lbl_imp_err.set_text("Título é obrigatório.")
                            return
                        if not file_data["content"]:
                            lbl_imp_err.set_text("Selecione um arquivo.")
                            return
                        try:
                            doc = await api.api_import_document_async(
                                state.get_cookies(), project["id"], title,
                                file_data["name"], file_data["content"]
                            )
                            state.set_current_document(doc)
                            dlg_import_doc.close()
                            ui.notify("Documento importado com sucesso.", type="positive")
                            await refresh_fn()
                        except Exception as e:
                            logger.exception("dashboard.document.import failed")
                            lbl_imp_err.set_text(f"Erro: {str(e)[:100]}")

                    with ui.row().style("gap:8px; margin-top:16px;"):
                        ui.button("Cancelar", on_click=dlg_import_doc.close).classes("vs-btn-ghost")
                        ui.button("Importar documento", on_click=do_import).classes("vs-btn")

                ui.button("Importar documento", on_click=dlg_import_doc.open).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")
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
                f"border-radius:12px; padding:18px 20px; transition:all .2s;"
                "display:flex; align-items:center; gap:16px;"
            ):
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

                def make_delete_doc(d=doc):
                    def open_delete():
                        with ui.dialog() as dlg_del, ui.card().style(
                            "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:380px;"
                        ):
                            ui.label("Excluir documento").style("font-size:18px; font-weight:700; color:#f0f2ff;")
                            ui.label(f'Tem certeza que deseja excluir "{d["title"]}"?').style("font-size:13px; color:#8b90a0; margin:12px 0;")

                            async def confirm_delete():
                                try:
                                    await api.api_delete_document_async(state.get_cookies(), d["id"])
                                    if state.get_current_document().get("id") == d["id"]:
                                        state.set_current_document({})
                                    dlg_del.close()
                                    ui.notify("Documento excluído.", type="positive")
                                    await refresh_fn()
                                except Exception as e:
                                    logger.exception("dashboard.document.delete failed")
                                    ui.notify(f"Erro ao excluir documento: {str(e)[:80]}", type="negative")

                            with ui.row().style("gap:8px; margin-top:16px;"):
                                ui.button("Cancelar", on_click=dlg_del.close).classes("vs-btn-ghost")
                                ui.button("Excluir", on_click=confirm_delete).classes("vs-btn-danger")
                        dlg_del.open()
                    return open_delete

                def make_open(d=doc):
                    def open_doc():
                        state.set_current_document(d)
                        ui.navigate.to("/workspace")
                    return open_doc

                ui.button("Abrir no editor", on_click=make_open(doc)).classes("vs-btn").style("font-size:12px; padding:4px 10px !important;")
                ui.button("Excluir", on_click=make_delete_doc(doc)).props("onclick=event.stopPropagation()").classes("vs-btn-danger").style("font-size:12px; padding:4px 10px !important;")


async def dashboard_page() -> None:
    if not auth_guard():
        return

    container = app_layout("/dashboard", "Dashboard", "Gerencie seus projetos e documentos")

    with container:
        project_pending_delete = {"project": None, "total_open_callbacks": 0}
        restored_project_names: set[str] = set()

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
                ui.notify("Não foi possível carregar seus projetos.", type="negative")

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
                    _project_selector(
                        projects, refresh, open_project_delete_dialog, restored_project_names
                    )
                with ui.column().style("gap:0;"):
                    _document_list(refresh, docs)
            logger.info("dashboard.visual.refresh end count=%s", refresh_number)

        with ui.dialog() as project_delete_dialog, ui.card().style(
            "background:#1a1d27; border:1px solid rgba(255,255,255,.08); "
            "border-radius:16px; padding:28px; min-width:380px;"
        ):
            ui.label("Excluir projeto").style("font-size:18px; font-weight:700; color:#f0f2ff;")
            project_delete_text = ui.label("").style("font-size:13px; color:#8b90a0; margin:12px 0;")

            def cancel_project_delete() -> None:
                project = project_pending_delete["project"]
                logger.info(
                    "project.delete.cancel project_id=%s",
                    project.get("id") if project else None,
                )
                project_pending_delete["project"] = None
                project_delete_dialog.close()

            async def confirm_project_delete() -> None:
                project = project_pending_delete["project"]
                if not project:
                    return
                logger.info("project.delete.confirm project_id=%s", project.get("id"))
                try:
                    response = await api.api_delete_project_async(state.get_cookies(), project["id"])
                    logger.info(
                        "project.delete.response project_id=%s response=%s",
                        project.get("id"),
                        response,
                    )
                except Exception as exc:
                    logger.exception("dashboard.project.delete failed project_id=%s", project.get("id"))
                    ui.notify(f"Erro ao excluir projeto: {str(exc)[:80]}", type="negative")
                    return

                project_delete_dialog.close()
                project_pending_delete["project"] = None
                restored_project_names.add(project["name"].strip())
                current_before = state.get_current_project()
                context_cleared = state.clear_project_context(project["id"])
                current_after = state.get_current_project()
                logger.info(
                    "project.delete.state project_id=%s current_project_before=%s "
                    "current_project_after=%s current_document_after=%s",
                    project.get("id"),
                    current_before.get("id") if current_before else None,
                    current_after.get("id") if current_after else None,
                    state.get_current_document().get("id") if state.get_current_document() else None,
                )
                if context_cleared:
                    await ui.run_javascript(
                        "document.getElementById('current-project-chip')?.remove();"
                    )
                ui.notify("Projeto excluído.", type="positive")
                logger.info("project.delete.refresh start project_id=%s", project.get("id"))
                await dashboard_content.refresh()
                logger.info(
                    "project.delete.refresh end project_id=%s refresh_executed=true",
                    project.get("id"),
                )

            with ui.row().style("gap:8px; margin-top:16px;"):
                ui.button("Cancelar", on_click=cancel_project_delete).classes("vs-btn-ghost")
                ui.button("Excluir projeto", on_click=confirm_project_delete).classes("vs-btn-danger")

        def open_project_delete_dialog(project: dict) -> None:
            project_pending_delete["total_open_callbacks"] += 1
            logger.info(
                "project.delete.dialog_open project_id=%s callback_count=1 total_open_callbacks=%s",
                project.get("id"),
                project_pending_delete["total_open_callbacks"],
            )
            project_pending_delete["project"] = project
            project_delete_text.set_text(f'Tem certeza que deseja excluir "{project["name"]}"?')
            project_delete_dialog.open()

        await dashboard_content()
