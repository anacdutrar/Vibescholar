"""
VibeScholar – Reference Library Page
======================================

Lists, creates, updates, deletes and imports bibliography references. h
"""
from typing import Any

from nicegui import ui
from app.ui.components.layout import auth_guard, app_layout
from app.ui import state
from app.ui import api_client as api
from app.utils.validators import validate_doi


_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")


def _normalized_doi(value: Any) -> str | None:
    """Return a canonical display DOI only when the persisted value is valid."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    lowered = normalized.casefold()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    return normalized if validate_doi(normalized) else None


def _optional_text(value: Any, fallback: str = "Não informado") -> str:
    """Format optional persisted metadata without exposing Python null values."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _availability_label(value: Any) -> str:
    """Translate the persisted access marker while preserving unknown state."""
    normalized = str(value or "").strip().casefold()
    if normalized in {"aberto", "open", "open_access", "true", "sim"}:
        return "Sim"
    if normalized in {"fechado", "closed", "false", "não", "nao"}:
        return "Não"
    return "Não informado"


def _safe_academic_url(value: Any) -> str:
    """Return only an explicit HTTP(S) academic URL suitable for a link."""
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    return normalized if normalized.casefold().startswith(("https://", "http://")) else ""


def _summarize_authors(value: Any, visible_authors: int = 3) -> str:
    """Summarize semicolon-delimited authors and leave the full value untouched."""
    authors = _optional_text(value, "Autores não informados")
    if authors == "Autores não informados":
        return authors
    if ";" not in authors:
        return authors if len(authors) <= 90 else f"{authors[:87].rstrip()}…"
    names = [name.strip() for name in authors.split(";") if name.strip()]
    if len(names) <= visible_authors:
        return "; ".join(names)
    return f"{'; '.join(names[:visible_authors])} +{len(names) - visible_authors}"


def _reference_view_model(reference: dict[str, Any]) -> dict[str, Any]:
    """Build display-only metadata without mutating the API response."""
    doi = _normalized_doi(reference.get("doi"))
    abstract = _optional_text(reference.get("abstract"), "Resumo não disponível")
    return {
        "id": reference.get("id"),
        "title": _optional_text(reference.get("title"), "Sem título"),
        "authors": _optional_text(reference.get("authors"), "Autores não informados"),
        "authors_summary": _summarize_authors(reference.get("authors")),
        "year": _optional_text(reference.get("year")),
        "journal": _optional_text(reference.get("journal")),
        "doi": doi,
        "doi_display": doi or "Não disponível",
        "doi_url": f"https://doi.org/{doi}" if doi else None,
        "qualis": _optional_text(reference.get("qualis_score"), "Não classificado"),
        "open_access": _availability_label(reference.get("availability")),
        "abstract": abstract,
        "has_abstract": abstract != "Resumo não disponível",
        "issn": _optional_text(reference.get("issn")),
        "eissn": _optional_text(reference.get("eissn")),
        "language": _optional_text(reference.get("language")),
        "provider": _optional_text(reference.get("provider")),
        "source_url": _safe_academic_url(reference.get("source_url")),
    }


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
            ui.notify(f"Não foi possível carregar referências: {str(e)[:80]}", type="negative")

        async def refresh():
            ui.navigate.to("/references")

        # ── Action bar ──────────────────────────────────────────────────────
        ui.label("A biblioteca reúne as fontes do projeto e alimenta as sugestões de evidência.").style("font-size:13px; color:#8b90a0; margin-bottom:12px;")
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

        def open_details(ref_data: dict) -> None:
            view = _reference_view_model(ref_data)
            with ui.dialog() as dialog, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); "
                "border-radius:8px; padding:28px; width:min(720px, 92vw); "
                "max-height:88vh; overflow-y:auto;"
            ):
                with ui.row().style("align-items:flex-start; width:100%; gap:12px;"):
                    with ui.column().style("gap:4px; flex:1; min-width:0;"):
                        ui.label(view["title"]).style(
                            "font-size:19px; font-weight:700; color:#f0f2ff; "
                            "white-space:normal; overflow-wrap:anywhere;"
                        )
                        ui.label(view["authors"]).style(
                            "font-size:13px; color:#b2b7c8; white-space:normal; "
                            "overflow-wrap:anywhere;"
                        )
                    ui.button(icon="close", on_click=dialog.close).props(
                        'flat round dense aria-label="Fechar detalhes"'
                    ).tooltip("Fechar")

                ui.separator().style("border-color:rgba(255,255,255,.07); margin:14px 0;")
                with ui.element("div").style(
                    "display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); "
                    "gap:14px 20px; width:100%;"
                ):
                    for label, value in (
                        ("Ano", view["year"]),
                        ("Periódico / venue", view["journal"]),
                        ("Acesso aberto", view["open_access"]),
                        ("Qualis", view["qualis"]),
                        ("ISSN", view["issn"]),
                        ("eISSN", view["eissn"]),
                        ("Idioma", view["language"]),
                    ):
                        with ui.column().style("gap:2px; min-width:0;"):
                            ui.label(label).style(
                                "font-size:10px; font-weight:700; color:#73798c; "
                                "text-transform:uppercase;"
                            )
                            ui.label(value).style(
                                "font-size:13px; color:#f0f2ff; white-space:normal; "
                                "overflow-wrap:anywhere;"
                            )

                with ui.column().style("gap:5px; margin-top:18px; width:100%;"):
                    ui.label("DOI").style(
                        "font-size:10px; font-weight:700; color:#73798c; "
                        "text-transform:uppercase;"
                    )
                    if view["doi_url"]:
                        ui.link(view["doi_display"], target=view["doi_url"]).props(
                            'target="_blank" rel="noopener noreferrer"'
                        ).style("font-size:13px; color:#818cf8; overflow-wrap:anywhere;")
                    else:
                        ui.label(view["doi_display"]).style("font-size:13px; color:#f0f2ff;")

                if view["source_url"]:
                    with ui.column().style("gap:5px; margin-top:14px; width:100%;"):
                        ui.label("URL acadêmica").style(
                            "font-size:10px; font-weight:700; color:#73798c; "
                            "text-transform:uppercase;"
                        )
                        ui.link("Abrir fonte acadêmica", target=view["source_url"]).props(
                            'target="_blank" rel="noopener noreferrer"'
                        ).style("font-size:13px; color:#818cf8;")

                with ui.column().style("gap:5px; margin-top:18px; width:100%;"):
                    ui.label("Resumo").style(
                        "font-size:10px; font-weight:700; color:#73798c; "
                        "text-transform:uppercase;"
                    )
                    ui.label(view["abstract"]).style(
                        "font-size:13px; line-height:1.65; color:#b2b7c8; "
                        "white-space:pre-wrap; overflow-wrap:anywhere;"
                    )
                ui.button("Fechar", on_click=dialog.close).classes("vs-btn-ghost").style(
                    "align-self:flex-end; margin-top:18px;"
                )
            dialog.open()

        def open_edit(ref_data: dict) -> None:
            ref_id = ref_data["id"]
            with ui.dialog() as dlg_edit, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); "
                "border-radius:8px; padding:28px; width:min(560px, 92vw);"
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

        def open_delete(ref_data: dict) -> None:
            ref_id = ref_data["id"]
            title = ref_data.get("title") or "Referência"
            with ui.dialog() as dlg_del, ui.card().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.08); "
                "border-radius:8px; padding:28px; width:min(420px, 92vw);"
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

        with ui.column().style("width:100%; gap:12px;"):
            for reference in refs:
                view = _reference_view_model(reference)
                with ui.element("article").style(
                    "width:100%; background:#1a1d27; border:1px solid rgba(255,255,255,.07); "
                    "border-radius:8px; padding:18px 20px; min-width:0;"
                ):
                    with ui.row().style(
                        "width:100%; align-items:flex-start; gap:16px; flex-wrap:wrap;"
                    ):
                        with ui.column().style("gap:5px; flex:1 1 440px; min-width:0;"):
                            ui.label(view["title"]).style(
                                "font-size:15px; font-weight:700; color:#f0f2ff; "
                                "white-space:normal; overflow-wrap:anywhere;"
                            )
                            ui.label(view["authors_summary"]).style(
                                "font-size:12px; color:#9ca2b5; white-space:normal; "
                                "overflow-wrap:anywhere;"
                            )
                        with ui.row().style("gap:4px; flex-shrink:0;"):
                            ui.button(
                                icon="visibility",
                                on_click=lambda _, item=reference: open_details(item),
                            ).props('flat round dense aria-label="Ver detalhes"').tooltip(
                                "Ver detalhes"
                            )
                            ui.button(
                                icon="edit",
                                on_click=lambda _, item=reference: open_edit(item),
                            ).props(
                                'flat round dense color="primary" aria-label="Editar referência"'
                            ).tooltip("Editar")
                            ui.button(
                                icon="delete",
                                on_click=lambda _, item=reference: open_delete(item),
                            ).props(
                                'flat round dense color="negative" aria-label="Remover referência"'
                            ).tooltip("Remover")

                    with ui.element("div").style(
                        "display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); "
                        "gap:12px 18px; margin-top:14px; width:100%;"
                    ):
                        for label, value in (
                            ("Ano", view["year"]),
                            ("Periódico / venue", view["journal"]),
                            ("Acesso aberto", view["open_access"]),
                            ("Qualis", view["qualis"]),
                        ):
                            with ui.column().style("gap:2px; min-width:0;"):
                                ui.label(label).style(
                                    "font-size:10px; font-weight:700; color:#73798c; "
                                    "text-transform:uppercase;"
                                )
                                ui.label(value).style(
                                    "font-size:12px; color:#d5d8e3; white-space:normal; "
                                    "overflow-wrap:anywhere;"
                                )

                    with ui.row().style(
                        "align-items:center; gap:8px; margin-top:13px; min-width:0; "
                        "flex-wrap:wrap;"
                    ):
                        ui.label("DOI").style(
                            "font-size:10px; font-weight:700; color:#73798c; "
                            "text-transform:uppercase;"
                        )
                        if view["doi_url"]:
                            ui.link(view["doi_display"], target=view["doi_url"]).props(
                                'target="_blank" rel="noopener noreferrer"'
                            ).style("font-size:12px; color:#818cf8; overflow-wrap:anywhere;")
                        else:
                            ui.label(view["doi_display"]).style(
                                "font-size:12px; color:#9ca2b5;"
                            )
