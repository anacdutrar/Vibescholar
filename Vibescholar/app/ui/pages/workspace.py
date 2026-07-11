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
import base64
import asyncio
import hashlib
import math
import re
import time
from nicegui import ui
from app.core.logging import logger
from app.ui.components.layout import auth_guard, sidebar, page_header
from app.ui.styles import GLOBAL_CSS
from app.ui import state
from app.ui import api_client as api


SENTENCE_PAGE_SIZE = 10
PARAGRAPH_SUMMARY_PAGE_SIZE = 25


# ─── Quill helpers ────────────────────────────────────────────────────────────

QUILL_CDN = """
<link href="https://cdn.quilljs.com/1.3.7/quill.snow.css" rel="stylesheet">
<script src="https://cdn.quilljs.com/1.3.7/quill.min.js"></script>
"""

QUILL_INIT_JS = """
<script>
window.__vs_autosave_timer = window.__vs_autosave_timer || null;
window.__vs_loading_content = false;
window.__vs_autosave_revision = window.__vs_autosave_revision || 0;

function cancelQuillAutosave() {
  if (window.__vs_autosave_timer !== null) {
    clearTimeout(window.__vs_autosave_timer);
    window.__vs_autosave_timer = null;
    console.debug('quill.autosave debounce_cancelled');
  }
}

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
      window.__vs_loading_content = true;
      window.__vs_quill.setText(initial, 'silent');
      window.__vs_loading_content = false;
    }

    // Autosave: debounce 2 s
    window.__vs_quill.on('text-change', function(delta, oldDelta, source) {
      if (source !== 'user' || window.__vs_loading_content) {
        console.debug('quill.autosave change_ignored source=' + source);
        return;
      }
      cancelQuillAutosave();
      window.__vs_autosave_timer = setTimeout(function() {
        window.__vs_autosave_timer = null;
        window.__vs_autosave_revision += 1;
        var text = window.__vs_quill.getText();
        emitEvent('quill_autosave', {
          content: text,
          revision: window.__vs_autosave_revision
        });
      }, 2000);
    });
  }
})();

function setQuillContent(text) {
  cancelQuillAutosave();
  window.__vs_loading_content = true;
  if (window.__vs_quill) {
    window.__vs_quill.setText(text, 'silent');
  } else {
    window.__vs_initial_content = text;
  }
  window.__vs_loading_content = false;
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


def _detect_apparent_citation(text: str) -> dict | None:
    doi_match = re.search(r"\b10\.\d{4,9}/[^\s\]\)},;]+", text, re.IGNORECASE)
    author_year_match = re.search(
        r"\(([A-ZÀ-ÖØ-Ý][\wÀ-ÿ'’-]+)(?:\s+et\s+al\.)?,\s*((?:19|20)\d{2})\)",
        text,
        re.IGNORECASE,
    )
    numeric_match = re.search(r"\[\d+(?:-\d+)?\]", text)
    if doi_match:
        doi = doi_match.group(0).rstrip(".,;:")
        return {"raw": doi, "doi": doi, "author": None, "year": None}
    if author_year_match:
        return {
            "raw": author_year_match.group(0),
            "doi": None,
            "author": author_year_match.group(1),
            "year": int(author_year_match.group(2)),
        }
    if numeric_match:
        return {"raw": numeric_match.group(0), "doi": None, "author": None, "year": None}
    return None


def _has_apparent_citation(text: str) -> bool:
    return _detect_apparent_citation(text) is not None


def _reference_matches_citation(reference: dict, citation: dict) -> bool:
    if citation.get("doi"):
        return (reference.get("doi") or "").strip().lower() == citation["doi"].strip().lower()
    if citation.get("author") and citation.get("year") is not None:
        return (
            citation["author"].strip().lower() in (reference.get("authors") or "").lower()
            and reference.get("year") == citation["year"]
        )
    return False


def _paragraph_key(sentence: dict) -> str:
    paragraph_number = sentence.get("paragraph_number")
    return "unidentified" if paragraph_number is None else str(paragraph_number)


def _paragraph_filter_options(sentences: list[dict]) -> dict[str, str]:
    numbers = sorted({
        sentence.get("paragraph_number")
        for sentence in sentences
        if sentence.get("paragraph_number") is not None
    })
    options = {"all": "Todos os parágrafos"}
    options.update({str(number): f"Parágrafo {number}" for number in numbers})
    if any(sentence.get("paragraph_number") is None for sentence in sentences):
        options["unidentified"] = "Sem parágrafo identificado"
    return options


def _filter_sentences_by_paragraph(sentences: list[dict], selected: str) -> list[dict]:
    if selected == "all":
        return list(sentences)
    return [sentence for sentence in sentences if _paragraph_key(sentence) == selected]


def _initial_paragraph_filter(sentences: list[dict]) -> str:
    options = _paragraph_filter_options(sentences)
    return next((key for key in options if key != "all"), "all")


def _paginate(items: list, page: int, page_size: int) -> tuple[list, int, int]:
    total_pages = max(1, math.ceil(len(items) / page_size))
    current_page = min(max(page, 1), total_pages)
    start = (current_page - 1) * page_size
    return items[start:start + page_size], current_page, total_pages


def _paragraph_summaries(sentences: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for sentence in sentences:
        grouped.setdefault(_paragraph_key(sentence), []).append(sentence)

    def sort_key(item: tuple[str, list[dict]]) -> tuple[int, int]:
        key, _ = item
        return (1, 0) if key == "unidentified" else (0, int(key))

    summaries = []
    for key, group in sorted(grouped.items(), key=sort_key):
        label = "Sem parágrafo identificado" if key == "unidentified" else f"Parágrafo {key}"
        summaries.append({
            "key": key,
            "label": label,
            "sentence_count": len(group),
            "approved_evidence_count": sum(
                int(sentence.get("approved_evidence_count") or 0) for sentence in group
            ),
            "unverified_count": sum(
                1 for sentence in group if sentence.get("status", "UNVERIFIED") == "UNVERIFIED"
            ),
        })
    return summaries


def _set_sentence_view_filter(view_state: dict, selected: str) -> None:
    view_state["filter"] = selected
    view_state["sentence_page"] = 1
    view_state["summary_page"] = 1


def _sentence_panel_view(sentences: list[dict], view_state: dict) -> dict:
    selected = view_state["filter"]
    if selected == "all":
        items, page, total_pages = _paginate(
            _paragraph_summaries(sentences),
            view_state["summary_page"],
            PARAGRAPH_SUMMARY_PAGE_SIZE,
        )
        view_state["summary_page"] = page
        return {
            "mode": "summaries",
            "items": items,
            "page": page,
            "total_pages": total_pages,
            "card_count": 0,
            "summary_count": len(items),
        }

    paragraph_sentences = _filter_sentences_by_paragraph(sentences, selected)
    items, page, total_pages = _paginate(
        paragraph_sentences,
        view_state["sentence_page"],
        SENTENCE_PAGE_SIZE,
    )
    view_state["sentence_page"] = page
    return {
        "mode": "sentences",
        "items": items,
        "total_items": len(paragraph_sentences),
        "page": page,
        "total_pages": total_pages,
        "card_count": len(items),
        "summary_count": 0,
    }


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _is_current_autosave_response(autosave_state: dict, revision: int) -> bool:
    return revision == autosave_state["latest_started"]


async def _persist_content_before_version(cookies: dict, document_id: int, content: str) -> dict:
    logger.info(
        "document.version.manual put_start document_id=%s size=%s hash=%s",
        document_id,
        len(content),
        _content_digest(content),
    )
    await api.api_autosave_content_async(cookies, document_id, content)
    logger.info("document.version.manual put_complete_before_post document_id=%s", document_id)
    result = await api.api_save_version_async(cookies, document_id)
    logger.info(
        "document.version.manual post_complete document_id=%s version_id=%s created=%s",
        document_id,
        result.get("id"),
        result.get("created", True),
    )
    return result


async def _persist_content_before_version_locked(
    persistence_lock: asyncio.Lock,
    cookies: dict,
    document_id: int,
    content: str,
) -> dict:
    async with persistence_lock:
        return await _persist_content_before_version(cookies, document_id, content)


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
        ui.button("⚙️ Configurações", on_click=_open_settings_dialog).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")


async def _save_version(
    doc: dict,
    refresh_fn,
    save_button=None,
    save_status=None,
    operation_state: dict | None = None,
    persistence_lock: asyncio.Lock | None = None,
    autosave_state: dict | None = None,
) -> None:
    operation_state = operation_state or {"running": False}
    persistence_lock = persistence_lock or asyncio.Lock()
    autosave_state = autosave_state or {"latest_started": 0}
    if operation_state["running"]:
        return
    if autosave_state.get("loading_draft"):
        ui.notify("Aguarde o carregamento do rascunho.", type="warning")
        return
    operation_state["running"] = True
    if save_button is not None:
        save_button.disable()
    try:
        content = await ui.run_javascript("getQuillContent()")
        await ui.run_javascript("cancelQuillAutosave()")
        logger.info("quill.autosave debounce_cancelled reason=manual_version document_id=%s", doc["id"])
        autosave_state["next_revision"] = autosave_state.get("next_revision", 0) + 1
        autosave_state["latest_started"] = autosave_state["next_revision"]
        if save_status is not None:
            save_status.set_text("Salvando…")
        result = await _persist_content_before_version_locked(
            persistence_lock,
            state.get_cookies(),
            doc["id"],
            content or "",
        )
        doc["content"] = content or ""
        state.set_current_document(doc)
        if result.get("created") is False:
            message = result.get("message", "Nenhuma alteração desde a última versão.")
            ui.notify(message, type="info")
        else:
            ui.notify("Versão salva com sucesso!", type="positive")
        if save_status is not None:
            save_status.set_text("Rascunho salvo")
        await refresh_fn()
    except Exception as e:
        logger.exception("document.version.manual failed document_id=%s", doc.get("id"))
        if save_status is not None:
            save_status.set_text("Erro ao salvar rascunho")
        ui.notify(f"Erro ao salvar versão: {str(e)[:80]}", type="negative")
    finally:
        operation_state["running"] = False
        if save_button is not None:
            save_button.enable()


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

        async def do_export(fmt):
            try:
                exported = await api.api_export_document_async(state.get_cookies(), doc["id"], fmt)
                encoded = base64.b64encode(exported["content"]).decode("ascii")
                filename = json.dumps(exported["filename"])
                content_type = json.dumps(exported["content_type"])
                ui.run_javascript(f"""
                    const link = document.createElement('a');
                    link.href = 'data:' + {content_type} + ';base64,{encoded}';
                    link.download = {filename};
                    document.body.appendChild(link);
                    link.click();
                    link.remove();
                """)
                ui.notify("Exporta??o iniciada.", type="positive")
                dlg.close()
            except Exception as e:
                ui.notify(f"Erro ao exportar: {str(e)[:80]}", type="negative")

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


async def _open_settings_dialog() -> None:
    project = state.get_current_project()
    if not project:
        ui.notify("Selecione um projeto primeiro.", type="warning")
        return

    settings = {}
    try:
        settings = await api.api_get_project_settings_async(state.get_cookies(), project["id"])
    except Exception as e:
        ui.notify(f"N?o foi poss?vel carregar configura??es: {str(e)[:80]}", type="negative")

    with ui.dialog() as dlg, ui.card().style(
        "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; min-width:480px;"
    ):
        ui.label("Configurações do Projeto").style("font-size:18px; font-weight:700; color:#f0f2ff; margin-bottom:20px;")

        inp_lang = ui.select(["pt", "en", "es"], label="Idioma principal das refer?ncias", value=settings.get("preferred_language", "pt")).style("width:100%;")
        inp_qualis = ui.select(["A1", "A2", "B1", "B2", "B3", "B4", "B5", "C"], label="Qualis mínimo", value=settings.get("minimum_qualis", "B1")).style("width:100%;")
        inp_year_min = ui.number("Ano mínimo de publicação", value=settings.get("publication_year_min"), min=1900, max=2030).style("width:100%;")
        inp_year_max = ui.number("Ano máximo de publicação", value=settings.get("publication_year_max"), min=1900, max=2030).style("width:100%;")
        inp_max_sug = ui.number("Máximo de sugestões", value=settings.get("max_suggestions", 5), min=1, max=20).style("width:100%;")
        inp_open_access = ui.checkbox("Somente acesso aberto", value=settings.get("only_open_access", False))
        ui.label("Filtra artigos dispon?veis gratuitamente.").style("font-size:12px; color:#8b90a0; margin-top:-8px;")
        inp_prefer_doi = ui.checkbox("Preferir DOI", value=settings.get("prefer_doi", False))
        ui.label("Prioriza refer?ncias que possuam identificador DOI.").style("font-size:12px; color:#8b90a0; margin-top:-8px;")
        lbl_s_err = ui.label("").style("color:#ef4444; font-size:13px;")

        async def save_settings():
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
                await api.api_update_project_settings_async(state.get_cookies(), project["id"], payload)
                ui.notify("✅ Configurações salvas!", type="positive")
                dlg.close()
            except Exception as e:
                lbl_s_err.set_text(f"Erro: {str(e)[:80]}")

        with ui.row().style("gap:8px; margin-top:20px;"):
            ui.button("Cancelar", on_click=dlg.close).classes("vs-btn-ghost")
            ui.button("Salvar Configurações", on_click=save_settings).classes("vs-btn")
    dlg.open()


async def _version_selector(
    doc: dict,
    refresh_fn,
    persistence_lock: asyncio.Lock,
    autosave_state: dict,
) -> None:
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
                    def open_confirmation():
                        with ui.dialog() as dialog, ui.card().style(
                            "background:#1a1d27; border:1px solid rgba(255,255,255,.08); "
                            "border-radius:16px; padding:24px; min-width:420px;"
                        ):
                            ui.label("Carregar versão como rascunho").style(
                                "font-size:17px; font-weight:700; color:#f0f2ff;"
                            )
                            ui.label(
                                f"O conteúdo atual do rascunho será substituído pela versão {v['version_number']}."
                            ).style("font-size:13px; color:#b8bdcc; margin:10px 0;")

                            async def confirm_restore() -> None:
                                autosave_state["loading_draft"] = True
                                try:
                                    await ui.run_javascript("cancelQuillAutosave()")
                                    logger.info(
                                        "quill.autosave debounce_cancelled reason=load_draft document_id=%s",
                                        doc["id"],
                                    )
                                    autosave_state["next_revision"] = autosave_state.get("next_revision", 0) + 1
                                    autosave_state["latest_started"] = autosave_state["next_revision"]
                                    async with persistence_lock:
                                        restored = await api.api_restore_version_async(
                                            state.get_cookies(), doc["id"], v["id"]
                                        )
                                        restored_content = restored.get("content") or ""
                                        await ui.run_javascript(
                                            f"setQuillContent({json.dumps(restored_content)})"
                                        )
                                        doc["content"] = restored_content
                                        state.set_current_document(doc)
                                    dialog.close()
                                    ui.notify(
                                        f"Versão {v['version_number']} carregada como rascunho. "
                                        "Salve uma nova versão quando desejar.",
                                        type="positive",
                                    )
                                    await refresh_fn()
                                except Exception as exc:
                                    logger.exception(
                                        "document.version.load_draft failed document_id=%s version_id=%s",
                                        doc.get("id"),
                                        v.get("id"),
                                    )
                                    ui.notify(f"Erro: {str(exc)[:80]}", type="negative")
                                finally:
                                    autosave_state["loading_draft"] = False

                            with ui.row().style("gap:8px; margin-top:14px;"):
                                ui.button("Cancelar", on_click=dialog.close).classes("vs-btn-ghost")
                                ui.button(
                                    "Carregar como rascunho", on_click=confirm_restore
                                ).classes("vs-btn")
                        dialog.open()
                    return open_confirmation

                ui.button("Carregar como rascunho", on_click=make_restore(ver)).style(
                    "background:transparent; border:1px solid rgba(99,102,241,.3); color:#6366f1; "
                    "border-radius:6px; font-size:11px; padding:4px 10px; flex-shrink:0;"
                )


async def _right_panel(
    doc: dict,
    refresh_fn,
    persistence_lock: asyncio.Lock,
    autosave_state: dict,
) -> None:
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
                ignored_citations: set[int] = set()
                options = _paragraph_filter_options(sentences)
                view_state = {
                    "filter": _initial_paragraph_filter(sentences),
                    "sentence_page": 1,
                    "summary_page": 1,
                }
                render_sequence = {"value": 0}
                paragraph_count = len(options) - 1
                logger.info(
                    "workspace.sentences.loaded total=%s paragraphs=%s initial_paragraph=%s",
                    len(sentences),
                    paragraph_count,
                    view_state["filter"],
                )

                async def refresh_sentence_panel() -> None:
                    sentence_cards.refresh()

                @ui.refreshable
                def sentence_cards() -> None:
                    started_at = time.perf_counter()
                    render_sequence["value"] += 1
                    view = _sentence_panel_view(sentences, view_state)

                    if view["mode"] == "summaries":
                        ui.label(f"{len(options) - 1} parágrafos no documento").style(
                            "font-size:12px; color:#8b90a0; margin-bottom:10px;"
                        )
                        for summary in view["items"]:
                            sentence_label = "sentença" if summary["sentence_count"] == 1 else "sentenças"
                            with ui.row().style(
                                "background:#212435; border:1px solid rgba(255,255,255,.07); "
                                "border-radius:8px; padding:10px 12px; margin-bottom:6px; "
                                "align-items:center; justify-content:space-between; width:100%; gap:10px;"
                            ):
                                with ui.column().style("gap:2px; min-width:0; flex:1;"):
                                    ui.label(
                                        f"{summary['label']} — {summary['sentence_count']} {sentence_label}"
                                    ).style("font-size:13px; font-weight:600; color:#f0f2ff;")
                                    ui.label(
                                        f"{summary['approved_evidence_count']} evidência(s) aprovada(s) · "
                                        f"{summary['unverified_count']} não verificada(s)"
                                    ).style("font-size:11px; color:#8b90a0;")

                                def make_open_paragraph(paragraph_key=summary["key"]):
                                    def open_paragraph() -> None:
                                        _set_sentence_view_filter(view_state, paragraph_key)
                                        paragraph_select.value = paragraph_key
                                        sentence_cards.refresh()
                                    return open_paragraph

                                ui.button(
                                    "Ver sentenças", on_click=make_open_paragraph()
                                ).classes("vs-btn-ghost").style("font-size:11px;")

                        with ui.row().style(
                            "align-items:center; justify-content:center; gap:10px; margin-top:10px; width:100%;"
                        ):
                            def previous_summary_page() -> None:
                                view_state["summary_page"] = max(1, view["page"] - 1)
                                sentence_cards.refresh()

                            def next_summary_page() -> None:
                                view_state["summary_page"] = min(view["total_pages"], view["page"] + 1)
                                sentence_cards.refresh()

                            previous_button = ui.button("Anterior", on_click=previous_summary_page).classes("vs-btn-ghost")
                            if view["page"] == 1:
                                previous_button.disable()
                            ui.label(f"Página {view['page']} de {view['total_pages']}").style(
                                "font-size:12px; color:#b8bdcc;"
                            )
                            next_button = ui.button("Próximo", on_click=next_summary_page).classes("vs-btn-ghost")
                            if view["page"] == view["total_pages"]:
                                next_button.disable()
                    else:
                        count = view["total_items"]
                        count_label = "sentença" if count == 1 else "sentenças"
                        ui.label(f"{count} {count_label} neste parágrafo").style(
                            "font-size:12px; color:#8b90a0; margin-bottom:10px;"
                        )

                    for sent in view["items"] if view["mode"] == "sentences" else []:
                        status = sent.get("status", "UNVERIFIED")
                        pill_cls = {
                            "SUPPORTED": "pill-supported",
                            "OUTDATED": "pill-outdated",
                        }.get(status, "pill-unverified")
                        pill_label = {
                            "SUPPORTED": "Fundamentada",
                            "OUTDATED": "Desatualizada",
                        }.get(status, "Não verificada")
                        approved_count = int(sent.get("approved_evidence_count") or 0)
                        approved_titles = sent.get("approved_reference_titles") or []
                        citation = _detect_apparent_citation(sent["text"])
                        citation_needs_review = (
                            citation is not None
                            and approved_count == 0
                            and sent["id"] not in ignored_citations
                        )

                        with ui.element("div").style(
                            "background:#212435; border:1px solid rgba(255,255,255,.07); border-radius:8px; "
                            "padding:12px 14px; margin-bottom:8px;"
                        ):
                            with ui.row().style(
                                "justify-content:space-between; align-items:flex-start; margin-bottom:8px; gap:8px;"
                            ):
                                ui.label(sent["text"][:120] + ("…" if len(sent["text"]) > 120 else "")).style(
                                    "font-size:13px; color:#f0f2ff; flex:1; line-height:1.5;"
                                )
                                ui.element("span").classes(f"pill {pill_cls}").add_slot(
                                    "default", f"<span>{pill_label}</span>"
                                )

                            if citation_needs_review:
                                ui.label("Citação detectada — verificação necessária").style(
                                    "font-size:11px; color:#f59e0b; margin-bottom:6px;"
                                )
                                ui.label(f"Padrão detectado: {citation['raw']}").style(
                                    "font-size:11px; color:#d5d8e2; margin-bottom:6px;"
                                )
                            ui.label(f"{approved_count} evidência(s) aprovada(s)").style(
                                "font-size:11px; color:#8b90a0;"
                            )
                            for title in approved_titles[:3]:
                                ui.label(f"• {title[:80]}").style(
                                    "font-size:11px; color:#b8bdcc; white-space:nowrap; "
                                    "overflow:hidden; text-overflow:ellipsis; max-width:100%;"
                                )

                            def make_search(s=sent):
                                async def search_ev():
                                    await _evidence_panel(s, doc, refresh_sentence_panel)
                                return search_ev

                            def make_review(s=sent, detected=citation):
                                async def review_citation():
                                    await _citation_review_dialog(
                                        s,
                                        doc,
                                        detected,
                                        ignored_citations,
                                        refresh_sentence_panel,
                                    )
                                return review_citation

                            action_label = (
                                "Ver / adicionar evidências"
                                if approved_count > 0
                                else (
                                    "Revisar citação detectada"
                                    if citation_needs_review
                                    else "Buscar evidências"
                                )
                            )
                            action_callback = (
                                make_review(sent, citation)
                                if citation_needs_review
                                else make_search(sent)
                            )
                            ui.button(action_label, on_click=action_callback).style(
                                "background:rgba(99,102,241,.12); border:1px solid rgba(99,102,241,.25); "
                                "color:#818cf8; border-radius:6px; font-size:11px; padding:4px 12px; margin-top:8px;"
                            )

                    if view["mode"] == "sentences" and view["total_pages"] > 1:
                        with ui.row().style(
                            "align-items:center; justify-content:center; gap:10px; margin-top:10px; width:100%;"
                        ):
                            def previous_sentence_page() -> None:
                                view_state["sentence_page"] = max(1, view["page"] - 1)
                                sentence_cards.refresh()

                            def next_sentence_page() -> None:
                                view_state["sentence_page"] = min(view["total_pages"], view["page"] + 1)
                                sentence_cards.refresh()

                            previous_button = ui.button("Anterior", on_click=previous_sentence_page).classes("vs-btn-ghost")
                            if view["page"] == 1:
                                previous_button.disable()
                            ui.label(f"Página {view['page']} de {view['total_pages']}").style(
                                "font-size:12px; color:#b8bdcc;"
                            )
                            next_button = ui.button("Próximo", on_click=next_sentence_page).classes("vs-btn-ghost")
                            if view["page"] == view["total_pages"]:
                                next_button.disable()

                    elapsed = time.perf_counter() - started_at
                    logger.info(
                        "workspace.sentences.render sequence=%s filter=%s cards=%s summaries=%s elapsed=%.4f",
                        render_sequence["value"],
                        view_state["filter"],
                        view["card_count"],
                        view["summary_count"],
                        elapsed,
                    )
                    if render_sequence["value"] == 1:
                        logger.info(
                            "workspace.sentences.initial cards=%s paragraph=%s elapsed=%.4f",
                            view["card_count"],
                            view_state["filter"],
                            elapsed,
                        )

                def change_paragraph(event) -> None:
                    _set_sentence_view_filter(view_state, event.value)
                    sentence_cards.refresh()

                paragraph_select = ui.select(
                    options=options,
                    value=view_state["filter"],
                    label="Parágrafo",
                    on_change=change_paragraph,
                ).style("width:100%; margin-bottom:10px;")
                sentence_cards()

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
            await _version_selector(doc, refresh_fn, persistence_lock, autosave_state)


async def _citation_review_dialog(
    sentence: dict,
    doc: dict,
    citation: dict,
    ignored_citations: set[int],
    refresh_sentence_panel,
) -> None:
    with ui.dialog() as dialog, ui.card().style(
        "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; "
        "padding:28px; min-width:600px; max-width:700px;"
    ):
        ui.label("Revisar citação detectada").style(
            "font-size:18px; font-weight:700; color:#f0f2ff;"
        )
        ui.label(f"Padrão detectado: {citation['raw']}").style(
            "font-size:13px; color:#f59e0b; margin:6px 0 16px;"
        )

        try:
            suggestions = await api.api_search_evidence_async(
                state.get_cookies(), sentence["id"]
            )
        except Exception as exc:
            ui.label(f"Erro ao localizar referências: {str(exc)[:80]}").style(
                "font-size:13px; color:#ef4444;"
            )
            suggestions = []

        matches = [
            suggestion
            for suggestion in suggestions
            if _reference_matches_citation(suggestion.get("reference") or {}, citation)
        ]

        if matches:
            for suggestion in matches:
                reference = suggestion.get("reference") or {}
                with ui.element("div").style(
                    "background:#212435; border:1px solid rgba(255,255,255,.07); "
                    "border-radius:8px; padding:14px; margin-bottom:10px;"
                ):
                    ui.label(reference.get("title") or "Sem título").style(
                        "font-size:14px; font-weight:700; color:#f0f2ff;"
                    )
                    ui.label(reference.get("authors") or "Autores não informados").style(
                        "font-size:12px; color:#b8bdcc;"
                    )
                    ui.label(
                        f"Ano: {reference.get('year') or 'não informado'} · "
                        f"DOI: {reference.get('doi') or 'não informado'}"
                    ).style("font-size:11px; color:#8b90a0; margin:4px 0 10px;")

                    async def confirm_match(
                        suggestion_id=suggestion["id"], matched_reference=reference
                    ) -> None:
                        try:
                            await api.api_update_suggestion_status_async(
                                state.get_cookies(), suggestion_id, "APPROVED"
                            )
                        except Exception as exc:
                            ui.notify(
                                f"Erro ao confirmar evidência: {str(exc)[:80]}",
                                type="negative",
                            )
                            return

                        titles = sentence.setdefault("approved_reference_titles", [])
                        title = matched_reference.get("title")
                        if title and title not in titles:
                            titles.append(title)
                        sentence["approved_evidence_count"] = len(titles) or 1
                        sentence["status"] = "SUPPORTED"
                        ui.notify("Citação confirmada como evidência.", type="positive")
                        dialog.close()
                        await refresh_sentence_panel()

                    ui.button(
                        "Confirmar como evidência", on_click=confirm_match
                    ).classes("vs-btn").style("font-size:12px;")
        else:
            ui.label("Nenhuma referência correspondente encontrada na biblioteca").style(
                "font-size:13px; color:#b8bdcc; margin-bottom:10px;"
            )

            async def search_suggestions() -> None:
                dialog.close()
                await _evidence_panel(sentence, doc, refresh_sentence_panel)

            ui.button("Buscar sugestões", on_click=search_suggestions).classes("vs-btn")

        async def ignore_citation() -> None:
            ignored_citations.add(sentence["id"])
            dialog.close()
            await refresh_sentence_panel()

        with ui.row().style("gap:8px; margin-top:16px; width:100%;"):
            ui.button("Ignorar citação detectada", on_click=ignore_citation).classes("vs-btn-ghost")
            ui.button("Fechar", on_click=dialog.close).classes("vs-btn-ghost")
    dialog.open()


async def _evidence_panel(sentence: dict, doc: dict, refresh_fn) -> None:
    """Opens evidence suggestions dialog for a sentence."""
    with ui.dialog() as dlg, ui.card().style(
        "background:#1a1d27; border:1px solid rgba(255,255,255,.08); border-radius:16px; "
        "padding:28px; min-width:600px; max-width:700px;"
    ):
        ui.label("Sugest?es de Evid?ncia").style("font-size:18px; font-weight:700; color:#f0f2ff;")
        ui.label(f'"{sentence["text"][:100]}?"').style(
            "font-size:13px; color:#8b90a0; margin-top:4px; margin-bottom:20px; font-style:italic;"
        )

        @ui.refreshable
        async def evidence_content():
            try:
                suggestions = await api.api_search_evidence_async(state.get_cookies(), sentence["id"])
            except Exception as e:
                ui.label(f"Erro ao buscar evid?ncias: {str(e)[:80]}").style("font-size:13px; color:#ef4444;")
                return

            approved = [s for s in suggestions if s.get("status") == "APPROVED"]
            pending = [s for s in suggestions if s.get("status", "PENDING") == "PENDING"]
            rejected = [s for s in suggestions if s.get("status") == "REJECTED"]

            if approved:
                ui.label("Refer?ncias aprovadas").style("font-size:13px; font-weight:700; color:#22c55e;")
                _render_suggestions(approved, refresh_fn, evidence_content.refresh)
            if pending:
                ui.label("Sugest?es pendentes").style("font-size:13px; font-weight:700; color:#f0f2ff; margin-top:10px;")
                _render_suggestions(pending, refresh_fn, evidence_content.refresh)
            if not pending:
                ui.button("Buscar mais sugest?es", on_click=evidence_content.refresh).classes("vs-btn-ghost").style("margin-top:8px;")
            if not suggestions:
                ui.label("Nenhuma sugest?o encontrada para esta senten?a.").style("font-size:14px; color:#8b90a0;")
            if rejected:
                ui.label(f"{len(rejected)} sugest?o(?es) rejeitada(s).").style("font-size:12px; color:#8b90a0; margin-top:8px;")

        await evidence_content()
        ui.button("Fechar", on_click=dlg.close).classes("vs-btn-ghost").style("width:100%; margin-top:16px;")
    dlg.open()


def _render_suggestions(suggestions: list, refresh_fn, evidence_refresh_fn) -> None:
    for sug in suggestions:
        ref = sug.get("reference", {})
        status = sug.get("status", "PENDING")
        status_colors = {"APPROVED": "#22c55e", "REJECTED": "#ef4444", "PENDING": "#f59e0b"}
        status_labels = {"APPROVED": "Aprovada", "REJECTED": "Rejeitada", "PENDING": "Pendente"}
        color = status_colors.get(status, "#f59e0b")

        with ui.element("div").style(
            "background:#212435; border:1px solid rgba(255,255,255,.07); border-radius:10px; padding:16px;"
        ):
            with ui.row().style("justify-content:space-between; align-items:flex-start; gap:12px;"):
                with ui.column().style("flex:1; gap:4px; min-width:0;"):
                    ui.label(ref.get("title", "Sem t?tulo")).style("font-size:14px; font-weight:700; color:#f0f2ff;")
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
                            ui.element("span").classes("vs-chip").style("font-size:11px; background:rgba(34,197,94,.1); color:#22c55e;").add_slot(
                                "default", f"<span>Qualis {ref['qualis_score']}</span>"
                            )
                ui.element("span").classes("pill").style(f"color:{color}; border-color:{color}55;").add_slot(
                    "default", f"<span>{status_labels.get(status, status)}</span>"
                )

            if status == "PENDING":
                with ui.row().style("gap:8px; margin-top:12px;"):
                    async def approve(sid=sug["id"]):
                        try:
                            await api.api_update_suggestion_status_async(state.get_cookies(), sid, "APPROVED")
                            ui.notify("Evid?ncia aprovada!", type="positive")
                            await evidence_refresh_fn()
                            await refresh_fn()
                        except Exception as e:
                            ui.notify(f"Erro: {str(e)[:60]}", type="negative")

                    async def reject(sid=sug["id"]):
                        try:
                            await api.api_update_suggestion_status_async(state.get_cookies(), sid, "REJECTED")
                            ui.notify("Evid?ncia rejeitada.", type="info")
                            await evidence_refresh_fn()
                        except Exception as e:
                            ui.notify(f"Erro: {str(e)[:60]}", type="negative")

                    ui.button("Aprovar", on_click=approve).style(
                        "background:#16a34a22; border:1px solid #22c55e55; color:#22c55e; "
                        "border-radius:6px; font-size:12px; padding:6px 14px;"
                    )
                    ui.button("Rejeitar", on_click=reject).style(
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

    persistence_lock = asyncio.Lock()
    autosave_state = {
        "next_revision": 0,
        "latest_started": 0,
        "latest_completed": 0,
        "loading_draft": False,
    }
    save_operation = {"running": False}

    async def refresh_analysis_panel() -> None:
        nonlocal doc
        if doc and doc.get("id"):
            try:
                doc = await api.api_get_document_async(state.get_cookies(), doc["id"])
                state.set_current_document(doc)
            except Exception:
                ui.notify("Não foi possível atualizar o documento.", type="negative")
        await right_panel_content.refresh()

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
                return

            # ── Toolbar ────────────────────────────────────────────────────
            with ui.row().style(
                "background:#1a1d27; border:1px solid rgba(255,255,255,.07); border-radius:12px; "
                "padding:10px 16px; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:16px;"
            ):
                _document_selector(refresh_analysis_panel, project_docs)
                ui.element("div").style("flex:1;")

                score = doc.get("grounding_score", 0.0)
                color = "#22c55e" if score >= 0.7 else ("#f59e0b" if score >= 0.4 else "#ef4444")
                ui.element("div").style(
                    f"border:2px solid {color}; border-radius:50%; width:38px; height:38px; "
                    f"display:flex; align-items:center; justify-content:center; "
                    f"font-size:11px; font-weight:700; color:{color};"
                ).add_slot("default", f"<span>{int(score*100)}%</span>")

                async def save_version_click():
                    await _save_version(
                        doc,
                        refresh_analysis_panel,
                        save_button,
                        save_status,
                        save_operation,
                        persistence_lock,
                        autosave_state,
                    )

                save_button = ui.button("💾 Versão", on_click=save_version_click).classes("vs-btn").style("font-size:13px; padding:6px 14px !important;")
                save_status = ui.label("Rascunho salvo").style("font-size:11px; color:#8b90a0;")
                ui.button("📤 Exportar", on_click=lambda: _open_export_dialog(doc)).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")
                ui.button("⚙️ Config", on_click=_open_settings_dialog).classes("vs-btn-ghost").style("font-size:13px; padding:6px 14px !important;")

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
                            if autosave_state["loading_draft"]:
                                logger.info(
                                    "quill.autosave ignored_during_draft_load document_id=%s",
                                    doc["id"],
                                )
                                return
                            autosave_state["next_revision"] += 1
                            revision = autosave_state["next_revision"]
                            autosave_state["latest_started"] = revision
                            browser_revision = e.args.get("revision") if isinstance(e.args, dict) else None
                            save_status.set_text("Salvando…")
                            logger.info(
                                "quill.autosave start document_id=%s revision=%s browser_revision=%s "
                                "size=%s hash=%s",
                                doc["id"],
                                revision,
                                browser_revision,
                                len(new_content),
                                _content_digest(new_content),
                            )
                            try:
                                async with persistence_lock:
                                    await api.api_autosave_content_async(
                                        state.get_cookies(), doc["id"], new_content
                                    )
                                if not _is_current_autosave_response(autosave_state, revision):
                                    logger.info(
                                        "quill.autosave stale_response_ignored document_id=%s revision=%s latest=%s",
                                        doc["id"],
                                        revision,
                                        autosave_state["latest_started"],
                                    )
                                    return
                                autosave_state["latest_completed"] = revision
                                doc["content"] = new_content
                                save_status.set_text("Rascunho salvo")
                                logger.info(
                                    "quill.autosave end document_id=%s revision=%s status=success",
                                    doc["id"],
                                    revision,
                                )
                            except Exception:
                                logger.exception(
                                    "quill.autosave end document_id=%s revision=%s status=error",
                                    doc.get("id"),
                                    revision,
                                )
                                if _is_current_autosave_response(autosave_state, revision):
                                    save_status.set_text("Erro ao salvar rascunho")

                    ui.on("quill_autosave", handle_autosave)

                # Right panel
                with ui.column().style(
                    "width:340px; flex-shrink:0; background:#1a1d27; border:1px solid rgba(255,255,255,.07); "
                    "border-radius:12px; padding:16px;"
                ):
                    @ui.refreshable
                    async def right_panel_content() -> None:
                        await _right_panel(
                            doc,
                            refresh_analysis_panel,
                            persistence_lock,
                            autosave_state,
                        )

                    await right_panel_content()
