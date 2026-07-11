"""
VibeScholar – Reference Library Page
======================================
Lists, creates, updates, deletes and imports bibliography references.
"""
from nicegui import ui
from app.ui.components.layout import auth_guard, app_layout
from app.ui import state
from app.ui import api_client as api


def _ref_form_fields():
    """Returns a dict of input widgets for reference form."""
    inp_title   = ui.input("Título *").style("width:100%;")
    inp_authors = ui.input("Autores *").style("width:100%;")
    inp_journal = ui.input("Periódico / Conferência").style("width:100%;")
    with ui.row().style("gap:12px; width:100%;"):
        inp_year    = ui.number("Ano", min=1800, max=2030).style("flex:1;")
        inp_qualis  = ui.select(["A1","A2","B1","B2","B3","B4","B5","C"], label="Qualis", value="B1").style("flex:1;")
    inp_doi     = ui.input("DOI").style("width:100%;")
    inp_abstract= ui.textarea("Resumo").style("width:100%;")
    inp_avail   = ui.select(["ABERTO","FECHADO"], label="Disponibilidade", value="FECHADO").style("width:100%;")
    return {
        "title": inp_title,
        "authors": inp_authors,
        "journal": inp_journal,
        "year": inp_year,
        "qualis_score": inp_qualis,
        "doi": inp_doi,
        "abstract": inp_abstract,
        "availability": inp_avail,
    }


def _build_payload(fields: dict) -> dict:
    return {
        "title": fields["title"].value.strip(),
        "authors": fields["authors"].value.strip(),
        "journal": fields["journal"].value.strip() or None,
        "year": int(fields["year"].value) if fields["year"].value else None,
        "qualis_score": fields["qualis_score"].value,
        "doi": fields["doi"].value.strip() or None,
        "abstract": fields["abstract"].value.strip() or None,
        "availability": fields["availability"].value,
    }


async def references_page() -> None:
    if not auth_guard():
        return

    project = state.get_current_project()
    container = app_layout(
        "/references",
        "Biblioteca de Referências",
        project["name"] if project else "Nenhum projeto selecionado"
    )

    with container:
        if not project:
            with ui.element("div").style(
                "text-align:center; padding:60px; background:#1a1d27; border-radius:12px; border:1px dashed rgba(255,255,255,.1);"
            ):
                ui.label("Selecione um projeto no Dashboard primeiro.").style("font-size:15px; color:#8b90a0;")
                ui.button("Dashboard", on_click=lambda: ui.navigate.to("/dashboard")).classes("vs-btn").style("margin-top:16px;")
            return

        refs = []
        try:
            refs = await api.api_list_references_async(state.get_cookies(), project["id"])
        except Exception as e:
            ui.notify(f"N?o foi poss?vel carregar refer?ncias: {str(e)[:80]}", type="negative")

        async def refresh():
            ui.navigate.to("/references")

        # ── Action bar ──────────────────────────────────────────────────────
        ui.label("A biblioteca re?ne as fontes do projeto e alimenta as sugest?es de evid?ncia.").style("font-size:13px; color:#8b90a0; margin-bottom:12px;")
        with ui.row().style("align-items:center; gap:10px; margin-bottom:20px; flex-wrap:wrap;"):
            ui.label(f"{len(refs)} referências").style("font-size:14px; color:#8b90a0; flex:1;")

            # Import dialog
            with ui.dialog() as dlg_import, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:420px;"
            ):
                ui.label("Importar Referências").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:4px;")
                ui.label("Formatos: .bib · .csv · .json").style("font-size:13px; color:#8b90a0; margin-bottom:16px;")
                upload = ui.upload(label="Selecionar arquivo", auto_upload=True, multiple=False, max_files=1).style("width:100%;")
                lbl_imp_err = ui.label("").style("color:#ef4444; font-size:13px;")
                file_data = {"name": None, "content": None}

                async def handle_upload(e):
                    file_data["name"] = e.file.name
                    file_data["content"] = await e.file.read()

                upload.on_upload(handle_upload)

                async def do_import():
                    lbl_imp_err.set_text("")
                    if not file_data["content"]:
                        lbl_imp_err.set_text("Selecione um arquivo.")
                        return
                    try:
                        imported = await api.api_import_references_async(
                            state.get_cookies(), project["id"],
                            file_data["name"], file_data["content"]
                        )
                        dlg_import.close()
                        ui.notify(f"✅ {len(imported)} referências importadas!", type="positive")
                        await refresh()
                    except Exception as e:
                        lbl_imp_err.set_text(f"Erro: {str(e)[:100]}")

                with ui.row().style("gap:8px; margin-top:14px;"):
                    ui.button("Cancelar", on_click=dlg_import.close).classes("vs-btn-ghost")
                    ui.button("Importar", on_click=do_import).classes("vs-btn")

            ui.button("📥 Importar", on_click=dlg_import.open).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")

            # New reference dialog
            with ui.dialog() as dlg_new, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:500px;"
            ):
                ui.label("Nova Referência").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:16px;")
                fields = _ref_form_fields()
                lbl_new_err = ui.label("").style("color:#ef4444; font-size:13px;")

                async def create_ref():
                    lbl_new_err.set_text("")
                    payload = _build_payload(fields)
                    if not payload["title"] or not payload["authors"]:
                        lbl_new_err.set_text("Título e autores são obrigatórios.")
                        return
                    try:
                        await api.api_create_reference_async(state.get_cookies(), project["id"], payload)
                        dlg_new.close()
                        ui.notify("✅ Referência criada!", type="positive")
                        await refresh()
                    except Exception as e:
                        lbl_new_err.set_text(f"Erro: {str(e)[:80]}")

                with ui.row().style("gap:8px; margin-top:16px;"):
                    ui.button("Cancelar", on_click=dlg_new.close).classes("vs-btn-ghost")
                    ui.button("Criar Referência", on_click=create_ref).classes("vs-btn")

            ui.button("+ Nova Referência", on_click=dlg_new.open).classes("vs-btn").style("font-size:13px; padding:6px 14px !important;")

        # ── References table ────────────────────────────────────────────────
        if not refs:
            with ui.element("div").style(
                "text-align:center; padding:60px; background:#1a1d27; border-radius:12px; border:1px dashed rgba(255,255,255,.1);"
            ):
                ui.label("📚").style("font-size:48px; display:block; margin-bottom:12px;")
                ui.label("Nenhuma referência ainda").style("font-size:16px; font-weight:600; color:#f0f2ff;")
                ui.label("Adicione ou importe referências bibliográficas").style("font-size:13px; color:#8b90a0;")
            return

        columns = [
            {"name": "title", "label": "Título", "field": "title", "align": "left"},
            {"name": "authors", "label": "Autores", "field": "authors", "align": "left"},
            {"name": "year", "label": "Ano", "field": "year", "align": "center"},
            {"name": "qualis", "label": "Qualis", "field": "qualis_score", "align": "center"},
            {"name": "avail", "label": "Acesso", "field": "availability", "align": "center"},
            {"name": "actions", "label": "Ações", "field": "id", "align": "center"},
        ]
        rows = [
            {
                "id": r["id"],
                "title": r["title"][:60] + ("…" if len(r.get("title","")) > 60 else ""),
                "authors": r.get("authors","")[:40] + ("…" if len(r.get("authors","")) > 40 else ""),
                "year": r.get("year") or "—",
                "qualis_score": r.get("qualis_score") or "—",
                "availability": r.get("availability","FECHADO"),
            }
            for r in refs
        ]

        table = ui.table(columns=columns, rows=rows, row_key="id").style(
            "width:100%; background:#1a1d27; border:1px solid rgba(255,255,255,.07); border-radius:12px;"
        )

        table.add_slot("body-cell-actions", """
            <q-td :props="props">
              <q-btn flat dense icon="edit" size="sm" color="primary"
                     @click="$parent.$emit('edit', props.row)" />
              <q-btn flat dense icon="delete" size="sm" color="negative"
                     @click="$parent.$emit('delete', props.row)" class="q-ml-xs"/>
            </q-td>
        """)

        def handle_edit(e):
            ref_id = e.args["id"]
            ref_data = next((r for r in refs if r["id"] == ref_id), None)
            if not ref_data:
                return

            with ui.dialog() as dlg_edit, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:500px;"
            ):
                ui.label("Editar Referência").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:16px;")
                ef = _ref_form_fields()
                ef["title"].value = ref_data.get("title","")
                ef["authors"].value = ref_data.get("authors","")
                ef["journal"].value = ref_data.get("journal","") or ""
                ef["year"].value = ref_data.get("year")
                ef["qualis_score"].value = ref_data.get("qualis_score","B1") or "B1"
                ef["doi"].value = ref_data.get("doi","") or ""
                ef["abstract"].value = ref_data.get("abstract","") or ""
                ef["availability"].value = ref_data.get("availability","FECHADO")
                lbl_edit_err = ui.label("").style("color:#ef4444; font-size:13px;")

                async def save_edit():
                    lbl_edit_err.set_text("")
                    payload = _build_payload(ef)
                    if not payload["title"] or not payload["authors"]:
                        lbl_edit_err.set_text("Título e autores são obrigatórios.")
                        return
                    try:
                        await api.api_update_reference_async(state.get_cookies(), ref_id, payload)
                        dlg_edit.close()
                        ui.notify("✅ Referência atualizada!", type="positive")
                        await refresh()
                    except Exception as e:
                        lbl_edit_err.set_text(f"Erro: {str(e)[:80]}")

                with ui.row().style("gap:8px; margin-top:16px;"):
                    ui.button("Cancelar", on_click=dlg_edit.close).classes("vs-btn-ghost")
                    ui.button("Salvar", on_click=save_edit).classes("vs-btn")
            dlg_edit.open()

        def handle_delete(e):
            ref_id = e.args["id"]
            ref_data = next((r for r in refs if r["id"] == ref_id), None)
            title = ref_data.get("title","Referência") if ref_data else "Referência"

            with ui.dialog() as dlg_del, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:380px;"
            ):
                ui.label("Remover Referência").style("font-size:18px; font-weight:700; color:#f0f2ff;")
                ui.label(f'Tem certeza que deseja remover "{title[:60]}"?').style("font-size:13px; color:#8b90a0; margin:12px 0;")
                with ui.row().style("gap:8px;"):
                    ui.button("Cancelar", on_click=dlg_del.close).classes("vs-btn-ghost")
                    async def confirm_del():
                        try:
                            await api.api_delete_reference_async(state.get_cookies(), ref_id)
                            dlg_del.close()
                            ui.notify("Referência removida.", type="info")
                            await refresh()
                        except Exception as ex:
                            ui.notify(f"Erro: {str(ex)[:60]}", type="negative")
                    ui.button("Remover", on_click=confirm_del).classes("vs-btn-danger")
            dlg_del.open()

        table.on("edit", handle_edit)
        table.on("delete", handle_delete)
