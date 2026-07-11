"""
VibeScholar – Workspace / Editor Page
=======================================
Full document editor with:
  • Quill rich-text editor (via ui.add_head_html + custom JS)
  • Autosave debounce
  • Version toolbar (save, restore)
  • Right-side panel: Sentence list + Evidence panel
  • Import / Export dialogs
  • Grounding dashboard panel
  • Version history panel
  • Document selector
  • Settings button (opens settings dialog)
"""
import json
from nicegui import ui
from app.ui.components.layout import auth_guard, sidebar, page_header
from app.ui.styles import GLOBAL_CSS
from app.ui import state
from app.ui import api_client as api


# ─── Quill helpers ────────────────────────────────────────────────────────────

QUILL_CDN = """
<link href="https://cdn.quilljs.com/1.3.7/quill.snow.css" rel="stylesheet">
<script src="https://cdn.quilljs.com/1.3.7/quill.min.js"></script>
"""

QUILL_INIT_JS = """
<script>
(function initQuill() {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    setTimeout(_init, 400);
  }

  function _init() {
    var container = document.getElementById('quill-mount');
    if (!container) { setTimeout(_init, 300); return; }
    if (window.__vs_quill) return;

    window.__vs_quill = new Quill('#quill-mount', {
      theme: 'snow',
      placeholder: 'Comece a escrever seu documento científico…',
      modules: {
        toolbar: [
          [{ header: [1, 2, 3, false] }],
          ['bold', 'italic', 'underline', 'strike'],
          [{ list: 'ordered' }, { list: 'bullet' }],
          ['blockquote', 'code-block'],
          [{ align: [] }],
          ['link'],
          ['clean']
        ]
      }
    });

    // Persist initial content if available
    var initial = window.__vs_initial_content || '';
    if (initial) {
      window.__vs_quill.setText(initial);
    }

    // Autosave: debounce 2 s
    var _timer = null;
    window.__vs_quill.on('text-change', function() {
      clearTimeout(_timer);
      _timer = setTimeout(function() {
        var text = window.__vs_quill.getText();
        emitEvent('quill_autosave', { content: text });
      }, 2000);
    });
  }
})();

function setQuillContent(text) {
  if (window.__vs_quill) {
    window.__vs_quill.setText(text);
  } else {
    window.__vs_initial_content = text;
  }
}

function getQuillContent() {
  if (window.__vs_quill) {
    return window.__vs_quill.getText();
  }
  return window.__vs_initial_content || '';
}
</script>
"""


async def _read_upload_file(uploaded_file) -> tuple[str, bytes]:
    return uploaded_file.name, await uploaded_file.read()


def _toolbar_row(doc: dict, refresh_fn) -> None:
    """Top action bar above the editor."""
    async def save_version_click():
        await _save_version(doc, refresh_fn)

    with ui.row().style(
        "background:#1a1d27; border:1px solid rgba(255,255,255,.07); border-radius:12px; "
        "padding:12px 16px; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:16px;"
    ):
        ui.label(doc.get("title", "Documento")).style(
            "font-size:16px; font-weight:700; color:#f0f2ff; flex:1; min-width:0; "
            "white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"
        )

        score = doc.get("grounding_score", 0.0)
        color = "#22c55e" if score >= 0.7 else ("#f59e0b" if score >= 0.4 else "#ef4444")
        ui.element("div").style(
            f"border:2px solid {color}; border-radius:50%; width:38px; height:38px; "
            f"display:flex; align-items:center; justify-content:center; "
            f"font-size:11px; font-weight:700; color:{color};"
        ).add_slot("default", f"<span>{int(score*100)}%</span>")

        ui.button("💾 Salvar Versão", on_click=save_version_click).classes("vs-btn").style("font-size:13px; padding:6px 14px !important;")
        ui.button("📤 Exportar", on_click=lambda: _open_export_dialog(doc)).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")
        ui.button("📥 Importar", on_click=lambda: _open_import_dialog(refresh_fn)).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")
        ui.button("⚙️ Configurações", on_click=lambda: _open_settings_dialog()).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")


async def _save_version(doc: dict, refresh_fn) -> None:
    try:
        await api.api_save_version_async(state.get_cookies(), doc["id"])
        ui.notify("✅ Versão salva com sucesso!", type="positive")
        await refresh_fn()
    except Exception as e:
        ui.notify(f"Erro ao salvar versão: {str(e)[:80]}", type="negative")


def _open_export_dialog(doc: dict) -> None:
    with ui.dialog() as dlg, ui.card().style(
        "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:400px;"
    ):
        ui.label("Exportar Documento").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:4px;")
        ui.label("Escolha o formato de exportação").style("font-size:13px; color:#8b90a0; margin-bottom:20px;")

        formats = [
            ("📝 Markdown (.md)", "md"),
            ("📄 Word (.docx)", "docx"),
            ("📕 PDF (.pdf)", "pdf"),
            ("📚 BibTeX (.bib)", "bibtex"),
            ("🔤 APA (.txt)", "apa"),
            ("🔤 ABNT (.txt)", "abnt"),
        ]

        def do_export(fmt):
            url = api.api_export_document_url(doc["id"], fmt)
            ui.run_javascript(f"window.open('{url}', '_blank')")
            dlg.close()

        with ui.grid(columns=2).style("gap:8px; width:100%;"):
            for label, fmt in formats:
                ui.button(label, on_click=lambda f=fmt: do_export(f)).style(
                    "background:#212435; border:1px solid rgba(255,255,255,.08); border-radius:8px; "
                    "color:#f0f2ff; font-size:13px; padding:12px; text-align:left;"
                )

        ui.button("Fechar", on_click=dlg.close).classes("vs-btn-ghost").style("width:100%; margin-top:12px;")
    dlg.open()


def _open_import_dialog(refresh_fn) -> None:
    project = state.get_current_project()
    if not project:
        ui.notify("Selecione um projeto primeiro.", type="warning")
        return

    with ui.dialog() as dlg, ui.card().style(
        "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:420px;"
    ):
        ui.label("Importar Documento").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:4px;")
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
            uploaded_file = e.file
            filename = uploaded_file.name
            if not filename.lower().endswith((".docx", ".md", ".txt")):
                file_data["name"] = None
                file_data["content"] = None
                selected_file_label.set_text("Nenhum arquivo selecionado")
                lbl_imp_err.set_text("Arquivo inválido. Use .docx, .md ou .txt.")
                upload.reset()
                return
            try:
                filename, content = await _read_upload_file(uploaded_file)
            except Exception as exc:
                file_data["name"] = None
                file_data["content"] = None
                selected_file_label.set_text("Nenhum arquivo selecionado")
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
            title = inp_imp_title.value.strip()
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
                dlg.close()
                await refresh_fn()
                ui.notify("✅ Documento importado com sucesso!", type="positive")
            except Exception as e:
                lbl_imp_err.set_text(f"Erro: {str(e)[:100]}")

        with ui.row().style("gap:8px; margin-top:16px;"):
            ui.button("Cancelar", on_click=dlg.close).classes("vs-btn-ghost")
            ui.button("Importar", on_click=do_import).classes("vs-btn")
    dlg.open()


def _open_settings_dialog() -> None:
    project = state.get_current_project()
    if not project:
        ui.notify("Selecione um projeto primeiro.", type="warning")
        return

    settings = {}
    try:
        settings = api.api_get_project_settings(state.get_cookies(), project["id"])
    except Exception:
        pass

    with ui.dialog() as dlg, ui.card().style(
        "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:480px;"
    ):
        ui.label("Configurações do Projeto").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:20px;")

        inp_lang = ui.select(["pt", "en", "es"], label="Idioma preferido", value=settings.get("preferred_language", "pt")).style("width:100%;")
        inp_qualis = ui.select(["A1", "A2", "B1", "B2", "B3", "B4", "B5", "C"], label="Qualis mínimo", value=settings.get("minimum_qualis", "B1")).style("width:100%;")
        inp_year_min = ui.number("Ano mínimo de publicação", value=settings.get("publication_year_min"), min=1900, max=2030).style("width:100%;")
        inp_year_max = ui.number("Ano máximo de publicação", value=settings.get("publication_year_max"), min=1900, max=2030).style("width:100%;")
        inp_max_sug = ui.number("Máximo de sugestões", value=settings.get("max_suggestions", 5), min=1, max=20).style("width:100%;")
        inp_open_access = ui.checkbox("Somente acesso aberto", value=settings.get("only_open_access", False))
        inp_prefer_doi = ui.checkbox("Preferir DOI", value=settings.get("prefer_doi", False))
        lbl_s_err = ui.label("").style("color:#ef4444; font-size:13px;")

        def save_settings():
            lbl_s_err.set_text("")
            payload = {
                "preferred_language": inp_lang.value,
                "minimum_qualis": inp_qualis.value,
                "publication_year_min": int(inp_year_min.value) if inp_year_min.value else None,
                "publication_year_max": int(inp_year_max.value) if inp_year_max.value else None,
                "max_suggestions": int(inp_max_sug.value or 5),
                "only_open_access": inp_open_access.value,
                "prefer_doi": inp_prefer_doi.value,
            }
            try:
                api.api_update_project_settings(state.get_cookies(), project["id"], payload)
                ui.notify("✅ Configurações salvas!", type="positive")
                dlg.close()
            except Exception as e:
                lbl_s_err.set_text(f"Erro: {str(e)[:80]}")

        with ui.row().style("gap:8px; margin-top:20px;"):
            ui.button("Cancelar", on_click=dlg.close).classes("vs-btn-ghost")
            ui.button("Salvar Configurações", on_click=save_settings).classes("vs-btn")
    dlg.open()


async def _version_selector(doc: dict, refresh_fn) -> None:
    """Version history panel."""
    versions = []
    try:
        versions = await api.api_list_versions_async(state.get_cookies(), doc["id"])
    except Exception:
        ui.label("Não foi possível carregar o histórico.").style("font-size:13px; color:#ef4444;")

    with ui.column().style("gap:8px;"):
        ui.label("Histórico de Versões").style("font-size:15px; font-weight:700; color:#f0f2ff; margin-bottom:4px;")

        if not versions:
            ui.label("Nenhuma versão salva ainda.").style("font-size:13px; color:#8b90a0;")
            return

        for ver in versions:
            with ui.element("div").style(
                "background:#212435; border:1px solid rgba(255,255,255,.07); border-radius:8px; "
                "padding:12px 14px; display:flex; align-items:center; gap:10px;"
            ):
                ui.element("div").style(
                    "width:32px;height:32px;border-radius:8px;background:rgba(99,102,241,.15);"
                    "display:flex;align-items:center;justify-content:center;"
                    "font-size:12px;font-weight:700;color:#6366f1;flex-shrink:0;"
                ).add_slot("default", f"<span>v{ver['version_number']}</span>")
                with ui.column().style("flex:1; gap:1px; min-width:0;"):
                    ui.label(f"Versão {ver['version_number']}").style("font-size:13px; font-weight:600; color:#f0f2ff;")
                    created = ver.get("created_at", "")[:10]
                    ui.label(f"Por {ver.get('created_by','?')} · {created}").style("font-size:11px; color:#8b90a0;")

                def make_restore(v=ver):
                    async def restore():
                        try:
                            api.api_restore_version(state.get_cookies(), doc["id"], v["id"])
                            ui.notify(f"✅ Versão {v['version_number']} restaurada!", type="positive")
                            await refresh_fn()
                        except Exception as e:
                            ui.notify(f"Erro: {str(e)[:80]}", type="negative")
                    return restore

                ui.button("Restaurar", on_click=make_restore(ver)).style(
                    "background:transparent; border:1px solid rgba(99,102,241,.3); color:#6366f1; "
                    "border-radius:6px; font-size:11px; padding:4px 10px; flex-shrink:0;"
                )


async def _right_panel(doc: dict, refresh_fn) -> None:
    """Right side panel: sentence list, evidence panel, version selector, grounding dashboard."""
    tabs = ui.tabs().style("margin-bottom:0; border-bottom:1px solid rgba(255,255,255,.07);")
    with tabs:
        t_sentences = ui.tab("Sentenças", icon="list")
        t_grounding = ui.tab("Grounding", icon="verified")
        t_history = ui.tab("Histórico", icon="history")

    with ui.tab_panels(tabs, value=t_sentences).style("background:transparent; padding:16px 0;"):
        # ── Sentences panel ──────────────────────────────────────────────────
        with ui.tab_panel(t_sentences):
            sentences = []
            try:
                sentences = await api.api_list_sentences_async(state.get_cookies(), doc["id"])
            except Exception:
                ui.label("Não foi possível carregar as sentenças.").style("font-size:13px; color:#ef4444;")

            if not sentences:
                ui.label("Nenhuma sentença extraída. Salve uma versão primeiro.").style(
                    "font-size:13px; color:#8b90a0;"
                )
            else:
                for sent in sentences:
                    status = sent.get("status", "UNVERIFIED")
                    pill_cls = {"SUPPORTED": "pill-supported", "OUTDATED": "pill-outdated"}.get(status, "pill-unverified")
                    pill_label = {"SUPPORTED": "✅ Fundamentada", "OUTDATED": "⚠️ Desatualizada"}.get(status, "🔍 Não verificada")

                    with ui.element("div").style(
                        "background:#212435; border:1px solid rgba(255,255,255,.07); border-radius:8px; "
                        "padding:12px 14px; margin-bottom:8px;"
                    ):
                        with ui.row().style("justify-content:space-between; align-items:flex-start; margin-bottom:8px; gap:8px;"):
                            ui.label(sent["text"][:120] + ("…" if len(sent["text"]) > 120 else "")).style(
                                "font-size:13px; color:#f0f2ff; flex:1; line-height:1.5;"
                            )
                            ui.element("span").classes(f"pill {pill_cls}").add_slot(
                                "default", f"<span>{pill_label}</span>"
                            )

                        def make_search(s=sent):
                            def search_ev():
                                _evidence_panel(s, doc, refresh_fn)
                            return search_ev

                        ui.button("🔎 Buscar Evidências", on_click=make_search(sent)).style(
                            "background:rgba(99,102,241,.12); border:1px solid rgba(99,102,241,.25); "
                            "color:#6366f1; border-radius:6px; font-size:11px; padding:4px 12px;"
                        )

        # ── Grounding dashboard ──────────────────────────────────────────────
        with ui.tab_panel(t_grounding):
            summary = {}
            try:
                summary = await api.api_get_grounding_summary_async(state.get_cookies(), doc["id"])
            except Exception:
                summary = {}

            if not summary:
                ui.label("Nenhum relatório disponível ainda.").style("font-size:13px; color:#8b90a0;")
            else:
                score = summary.get("grounding_score", 0.0)
                color = "#22c55e" if score >= 0.7 else ("#f59e0b" if score >= 0.4 else "#ef4444")

                with ui.element("div").style("text-align:center; margin-bottom:20px;"):
                    ui.element("div").style(
                        f"width:80px;height:80px;border-radius:50%;border:3px solid {color};"
                        f"display:flex;align-items:center;justify-content:center;"
                        f"font-size:22px;font-weight:800;color:{color};margin:0 auto 8px;"
                        f"background:rgba(0,0,0,.2);"
                    ).add_slot("default", f"<span>{int(score*100)}%</span>")
                    ui.label("Score de Fundamentação").style("font-size:13px; color:#8b90a0;")

                for label, key, col in [
                    ("Fundamentadas", "supported_count", "#22c55e"),
                    ("Não verificadas", "unsupported_count", "#f59e0b"),
                    ("Desatualizadas", "outdated_count", "#ef4444"),
                ]:
                    with ui.row().style(f"justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid rgba(255,255,255,.06);"):
                        with ui.row().style("align-items:center; gap:8px;"):
                            ui.element("div").style(f"width:8px;height:8px;border-radius:50%;background:{col};")
                            ui.label(label).style("font-size:13px; color:#f0f2ff;")
                        ui.label(str(summary.get(key, 0))).style(f"font-size:16px; font-weight:700; color:{col};")

        # ── Version history ──────────────────────────────────────────────────
        with ui.tab_panel(t_history):
            await _version_selector(doc, refresh_fn)


def _evidence_panel(sentence: dict, doc: dict, refresh_fn) -> None:
    """Opens evidence suggestions dialog for a sentence."""
    suggestions = []
    try:
        suggestions = api.api_search_evidence(state.get_cookies(), sentence["id"])
    except Exception as e:
        ui.notify(f"Erro ao buscar evidências: {str(e)[:80]}", type="negative")
        return

    with ui.dialog() as dlg, ui.card().style(
        "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; "
        "padding:28px; min-width:600px; max-width:700px;"
    ):
        ui.label("Sugestões de Evidência").style("font-size:18px; font-weight:700; color:#f0f2ff;")
        ui.label(f'"{sentence["text"][:100]}…"').style(
            "font-size:13px; color:#8b90a0; margin-top:4px; margin-bottom:20px; font-style:italic;"
        )

        if not suggestions:
            ui.label("Nenhuma sugestão encontrada para esta sentença.").style("font-size:14px; color:#8b90a0;")
        else:
            ev_container = ui.column().style("gap:10px; width:100%;")
            with ev_container:
                _render_suggestions(suggestions, dlg, refresh_fn)

        ui.button("Fechar", on_click=dlg.close).classes("vs-btn-ghost").style("width:100%; margin-top:16px;")
    dlg.open()


def _render_suggestions(suggestions: list, dlg, refresh_fn) -> None:
    for sug in suggestions:
        ref = sug.get("reference", {})
        status = sug.get("status", "PENDING")
        status_colors = {"APPROVED": "#22c55e", "REJECTED": "#ef4444", "PENDING": "#f59e0b"}
        status_labels = {"APPROVED": "✅ Aprovada", "REJECTED": "❌ Rejeitada", "PENDING": "⏳ Pendente"}
        color = status_colors.get(status, "#f59e0b")

        with ui.element("div").style(
            f"background:#212435; border:1px solid rgba(255,255,255,.07); border-radius:10px; padding:16px;"
        ):
            with ui.row().style("justify-content:space-between; align-items:flex-start; gap:12px;"):
                with ui.column().style("flex:1; gap:4px; min-width:0;"):
                    ui.label(ref.get("title", "Sem título")).style("font-size:14px; font-weight:700; color:#f0f2ff;")
                    ui.label(ref.get("authors", "")).style("font-size:12px; color:#8b90a0;")
                    with ui.row().style("gap:6px; flex-wrap:wrap; margin-top:4px;"):
                        if ref.get("journal"):
                            ui.element("span").classes("vs-chip").style("font-size:11px;").add_slot(
                                "default", f"<span>{ref['journal'][:30]}</span>"
                            )
                        if ref.get("year"):
                            ui.element("span").classes("vs-chip").style("font-size:11px;").add_slot(
                                "default", f"<span>{ref['year']}</span>"
                            )
                        if ref.get("qualis_score"):
                            ui.element("span").classes("vs-chip").style(f"font-size:11px; background:rgba(34,197,94,.1); color:#22c55e;").add_slot(
                                "default", f"<span>Qualis {ref['qualis_score']}</span>"
                            )
                ui.element("span").classes("pill").style(f"color:{color}; border-color:{color}55;").add_slot(
                    "default", f"<span>{status_labels.get(status, status)}</span>"
                )

            if status == "PENDING":
                with ui.row().style("gap:8px; margin-top:12px;"):
                    def make_approve(sid=sug["id"]):
                        async def approve():
                            try:
                                api.api_update_suggestion_status(state.get_cookies(), sid, "APPROVED")
                                ui.notify("✅ Evidência aprovada!", type="positive")
                                dlg.close()
                                await refresh_fn()
                            except Exception as e:
                                ui.notify(f"Erro: {str(e)[:60]}", type="negative")
                        return approve

                    def make_reject(sid=sug["id"]):
                        async def reject():
                            try:
                                api.api_update_suggestion_status(state.get_cookies(), sid, "REJECTED")
                                ui.notify("Evidência rejeitada.", type="info")
                                dlg.close()
                                await refresh_fn()
                            except Exception as e:
                                ui.notify(f"Erro: {str(e)[:60]}", type="negative")
                        return reject

                    ui.button("✅ Aprovar", on_click=make_approve(sug["id"])).style(
                        "background:#16a34a22; border:1px solid #22c55e55; color:#22c55e; "
                        "border-radius:6px; font-size:12px; padding:6px 14px;"
                    )
                    ui.button("❌ Rejeitar", on_click=make_reject(sug["id"])).style(
                        "background:#7f1d1d22; border:1px solid #ef444455; color:#ef4444; "
                        "border-radius:6px; font-size:12px; padding:6px 14px;"
                    )


def _document_selector(refresh_fn, docs: list[dict]) -> None:
    """Document selector dropdown in the toolbar area."""
    project = state.get_current_project()
    if not project:
        return
    if not docs:
        return

    options = {str(d["id"]): d["title"] for d in docs}
    current_doc = state.get_current_document()
    current_val = str(current_doc.get("id", "")) if current_doc else ""

    def on_select(e):
        selected_id = int(e.value)
        for d in docs:
            if d["id"] == selected_id:
                state.set_current_document(d)
                ui.navigate.to("/workspace")
                break

    ui.select(
        options=options,
        label="Documento",
        value=current_val,
        on_change=on_select
    ).style("min-width:200px;")


async def workspace_page() -> None:
    if not auth_guard():
        return

    from app.ui.styles import GLOBAL_CSS
    ui.add_head_html(GLOBAL_CSS)
    ui.add_head_html(QUILL_CDN)
    ui.add_head_html(QUILL_INIT_JS)

    doc = state.get_current_document()
    project = state.get_current_project()
    project_docs = []
    if project:
        try:
            project_docs = await api.api_list_documents_async(state.get_cookies(), project["id"])
        except Exception:
            ui.notify("Não foi possível carregar documentos do projeto.", type="warning")

    async def refresh():
        # Reload current document data from API
        nonlocal doc
        if doc and doc.get("id"):
            try:
                doc = await api.api_get_document_async(state.get_cookies(), doc["id"])
                state.set_current_document(doc)
            except Exception:
                ui.notify("Não foi possível atualizar o documento.", type="negative")
        ui.navigate.to("/workspace")

    with ui.row().style("width:100%; min-height:100vh; gap:0; background:#0f1117;"):
        # Sidebar
        sidebar("/workspace")

        # Main content
        with ui.column().style("flex:1; padding:24px 28px; overflow-y:auto; min-width:0; gap:0;"):
            page_header("Editor de Documentos", project.get("name", "") if project else "")

            if not project:
                with ui.element("div").style(
                    "text-align:center; padding:60px; background:#1a1d27; border-radius:12px; border:1px dashed rgba(255,255,255,.1);"
                ):
                    ui.label("Selecione um projeto no Dashboard para começar.").style("font-size:15px; color:#8b90a0;")
                    ui.button("Ir para o Dashboard", on_click=lambda: ui.navigate.to("/dashboard")).classes("vs-btn").style("margin-top:16px;")
                return

            if not doc:
                # Show document selector
                with ui.element("div").style(
                    "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:40px; text-align:center;"
                ):
                    ui.label("Nenhum documento aberto").style("font-size:16px; font-weight:600; color:#f0f2ff; margin-bottom:8px;")
                    ui.label("Selecione ou crie um documento no Dashboard.").style("font-size:13px; color:#8b90a0; margin-bottom:20px;")
                    with ui.row().style("gap:10px; justify-content:center;"):
                        ui.button("📂 Dashboard", on_click=lambda: ui.navigate.to("/dashboard")).classes("vs-btn")
                        ui.button("📥 Importar", on_click=lambda: _open_import_dialog(refresh)).classes("vs-btn-ghost")
                return

            # ── Toolbar ────────────────────────────────────────────────────
            with ui.row().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.07); border-radius:12px; "
                "padding:10px 16px; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:16px;"
            ):
                _document_selector(refresh, project_docs)
                ui.element("div").style("flex:1;")

                score = doc.get("grounding_score", 0.0)
                color = "#22c55e" if score >= 0.7 else ("#f59e0b" if score >= 0.4 else "#ef4444")
                ui.element("div").style(
                    f"border:2px solid {color}; border-radius:50%; width:38px; height:38px; "
                    f"display:flex; align-items:center; justify-content:center; "
                    f"font-size:11px; font-weight:700; color:{color};"
                ).add_slot("default", f"<span>{int(score*100)}%</span>")

                async def save_version_click():
                    await _save_version(doc, refresh)

                ui.button("💾 Versão", on_click=save_version_click).classes("vs-btn").style("font-size:13px; padding:6px 14px !important;")
                ui.button("📤 Exportar", on_click=lambda: _open_export_dialog(doc)).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")
                ui.button("📥 Importar", on_click=lambda: _open_import_dialog(refresh)).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")
                ui.button("⚙️ Config", on_click=lambda: _open_settings_dialog()).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")

            # ── Editor + Right panel ───────────────────────────────────────
            with ui.row().style("gap:20px; align-items:flex-start; width:100%;"):

                # Quill editor
                with ui.column().style("flex:1; min-width:0;"):
                    with ui.element("div").style(
                        "background:#1a1d27; border:1px solid rgba(255,255,255,.07); border-radius:12px; overflow:hidden;"
                    ):
                        ui.element("div").props('id="quill-mount"').style("min-height:500px;")

                    # Load content into Quill
                    content = doc.get("content") or ""
                    escaped = json.dumps(content)
                    ui.add_body_html(f"<script>setTimeout(function(){{ setQuillContent({escaped}); }}, 600);</script>")

                    # Autosave handler
                    async def handle_autosave(e):
                        new_content = e.args.get("content", "") if isinstance(e.args, dict) else ""
                        if new_content and doc.get("id"):
                            try:
                                await api.api_autosave_content_async(state.get_cookies(), doc["id"], new_content)
                            except Exception:
                                ui.notify("Autosave falhou.", type="warning")

                    ui.on("quill_autosave", handle_autosave)

                # Right panel
                with ui.column().style(
                    "width:340px; flex-shrink:0; background:#1a1d27; border:1px solid rgba(255,255,255,.07); "
                    "border-radius:12px; padding:16px;"
                ):
                    await _right_panel(doc, refresh)
