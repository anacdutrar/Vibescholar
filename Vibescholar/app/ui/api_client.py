"""
VibeScholar API Client
======================
Handles HTTP calls to the FastAPI backend via httpx.
Centralises authentication cookie management and error handling.
"""
import os
import time
import httpx
from typing import Optional, Any, Dict, List
from app.core.logging import logger

PORT = os.getenv("PORT", "8080")
BASE_URL = os.getenv("API_BASE_URL") or f"http://127.0.0.1:{PORT}"
HTTP_TIMEOUT = 30


class EvidenceSearchConflictError(RuntimeError):
    """Expose a safe conflict returned by the evidence-search endpoint."""

def _client(cookies: Optional[Dict[str, str]] = None) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, cookies=cookies or {}, timeout=HTTP_TIMEOUT)

def _async_client(cookies: Optional[Dict[str, str]] = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, cookies=cookies or {}, timeout=HTTP_TIMEOUT)


def register_payload(username: str, password: str, email: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "username": username.strip(),
        "password": password,
    }
    normalized_email = (email or "").strip()
    if normalized_email:
        payload["email"] = normalized_email
    return payload


def public_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: ("<omitted>" if key == "password" else value)
        for key, value in payload.items()
    }


def validation_error_message(detail: Any) -> str:
    if not isinstance(detail, list):
        return str(detail)
    messages = []
    for item in detail:
        loc = item.get("loc", []) if isinstance(item, dict) else []
        field = str(loc[-1]) if loc else "campo"
        error_type = item.get("type", "") if isinstance(item, dict) else ""
        msg = item.get("msg", "") if isinstance(item, dict) else str(item)
        if field == "email":
            messages.append("E-mail inválido")
        elif field == "password" and ("too_short" in error_type or "too_short" in msg.lower() or "at least" in msg.lower()):
            messages.append("Senha muito curta")
        elif "missing" in error_type:
            messages.append("Campo obrigatório ausente")
        else:
            messages.append(msg)
    return "; ".join(dict.fromkeys(messages)) or "Dados inválidos"


# ─── AUTH ────────────────────────────────────────────────────────────────────

async def api_login(username: str, password: str) -> Dict[str, Any]:
    """Returns (user_data, cookies_dict) or raises."""
    async with _async_client() as c:
        r = await c.post("/api/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        return r.json(), dict(r.cookies)


async def api_register(username: str, password: str, email: Optional[str] = None) -> Dict[str, Any]:
    payload = register_payload(username, password, email)
    logger.info("api_register payload=%s url=%s", public_payload(payload), f"{BASE_URL}/api/auth/register")
    async with _async_client() as c:
        r = await c.post("/api/auth/register", json=payload)
        if r.status_code >= 400:
            logger.warning("api_register status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()


def api_logout(cookies: Dict[str, str]) -> None:
    with _client(cookies) as c:
        c.post("/api/auth/logout")


async def api_logout_async(cookies: Dict[str, str]) -> None:
    async with _async_client(cookies) as c:
        r = await c.post("/api/auth/logout")
        if r.status_code >= 400:
            logger.warning("api_logout status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()


# ─── PROJECTS ────────────────────────────────────────────────────────────────

def api_list_projects(cookies: Dict[str, str]) -> List[Dict]:
    with _client(cookies) as c:
        r = c.get("/api/projects")
        r.raise_for_status()
        return r.json()


async def api_list_projects_async(cookies: Dict[str, str]) -> List[Dict]:
    logger.info("dashboard.projects.load start url=%s", f"{BASE_URL}/api/projects")
    async with _async_client(cookies) as c:
        r = await c.get("/api/projects")
        if r.status_code >= 400:
            logger.warning("dashboard.projects.load error status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()
        projects = r.json()
        logger.info("dashboard.projects.load returned count=%s", len(projects))
        return projects


def api_create_project(cookies: Dict[str, str], name: str, description: str = "") -> Dict:
    with _client(cookies) as c:
        r = c.post("/api/projects", json={"name": name, "description": description})
        r.raise_for_status()
        return r.json()


async def api_create_project_async(cookies: Dict[str, str], name: str, description: str = "") -> Dict:
    start = time.perf_counter()
    url = f"{BASE_URL}/api/projects"
    payload = {"name": name.strip(), "description": description}
    logger.info(
        "project.create api start elapsed=%.4f url=%s timeout=%s payload=%s",
        time.perf_counter() - start,
        url,
        HTTP_TIMEOUT,
        payload,
    )
    async with _async_client(cookies) as c:
        logger.info("project.create before AsyncClient.post elapsed=%.4f url=%s", time.perf_counter() - start, url)
        r = await c.post("/api/projects", json=payload)
        logger.info(
            "project.create response received elapsed=%.4f status=%s",
            time.perf_counter() - start,
            r.status_code,
        )
        if r.status_code >= 400:
            logger.warning("project.create error response status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()


def api_delete_project(cookies: Dict[str, str], project_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.delete(f"/api/projects/{project_id}")
        r.raise_for_status()
        return r.json()


async def api_delete_project_async(cookies: Dict[str, str], project_id: int) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.delete(f"/api/projects/{project_id}")
        r.raise_for_status()
        return r.json()


def api_get_project_settings(cookies: Dict[str, str], project_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.get(f"/api/projects/{project_id}/settings")
        r.raise_for_status()
        return r.json()


async def api_get_project_settings_async(cookies: Dict[str, str], project_id: int) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.get(f"/api/projects/{project_id}/settings")
        r.raise_for_status()
        return r.json()


def api_update_project_settings(cookies: Dict[str, str], project_id: int, settings: Dict) -> Dict:
    with _client(cookies) as c:
        r = c.put(f"/api/projects/{project_id}/settings", json=settings)
        r.raise_for_status()
        return r.json()


async def api_update_project_settings_async(cookies: Dict[str, str], project_id: int, settings: Dict) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.put(f"/api/projects/{project_id}/settings", json=settings)
        r.raise_for_status()
        return r.json()


# ─── DOCUMENTS ───────────────────────────────────────────────────────────────

def api_list_documents(cookies: Dict[str, str], project_id: int) -> List[Dict]:
    with _client(cookies) as c:
        r = c.get(f"/api/projects/{project_id}/documents")
        r.raise_for_status()
        return r.json()


async def api_list_documents_async(cookies: Dict[str, str], project_id: int) -> List[Dict]:
    start = time.perf_counter()
    url = f"{BASE_URL}/api/projects/{project_id}/documents"
    logger.info("dashboard.documents.load start url=%s project_id=%s", url, project_id)
    async with _async_client(cookies) as c:
        r = await c.get(f"/api/projects/{project_id}/documents")
        logger.info(
            "dashboard.documents.load response status=%s elapsed=%.4f",
            r.status_code,
            time.perf_counter() - start,
        )
        if r.status_code >= 400:
            logger.warning("dashboard.documents.load error status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()
        documents = r.json()
        logger.info(
            "dashboard.documents.load done count=%s elapsed=%.4f",
            len(documents),
            time.perf_counter() - start,
        )
        return documents


def api_create_document(cookies: Dict[str, str], project_id: int, title: str,
                        description: str = "", content: str = "") -> Dict:
    with _client(cookies) as c:
        r = c.post(f"/api/projects/{project_id}/documents",
                   json={"title": title, "description": description, "content": content})
        r.raise_for_status()
        return r.json()


async def api_create_document_async(cookies: Dict[str, str], project_id: int, title: str,
                                    description: str = "", content: str = "") -> Dict:
    async with _async_client(cookies) as c:
        r = await c.post(
            f"/api/projects/{project_id}/documents",
            json={"title": title, "description": description, "content": content}
        )
        r.raise_for_status()
        return r.json()


def api_get_document(cookies: Dict[str, str], document_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.get(f"/api/documents/{document_id}")
        r.raise_for_status()
        return r.json()


async def api_get_document_async(cookies: Dict[str, str], document_id: int) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.get(f"/api/documents/{document_id}")
        r.raise_for_status()
        return r.json()


def api_autosave_content(cookies: Dict[str, str], document_id: int, content: str) -> Dict:
    with _client(cookies) as c:
        r = c.put(f"/api/documents/{document_id}/content", json={"content": content})
        r.raise_for_status()
        return r.json()


async def api_autosave_content_async(cookies: Dict[str, str], document_id: int, content: str) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.put(f"/api/documents/{document_id}/content", json={"content": content})
        r.raise_for_status()
        return r.json()


def api_save_version(cookies: Dict[str, str], document_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.post(f"/api/documents/{document_id}/version")
        r.raise_for_status()
        return r.json()


async def api_save_version_async(cookies: Dict[str, str], document_id: int) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.post(f"/api/documents/{document_id}/version")
        r.raise_for_status()
        return r.json()


def api_list_versions(cookies: Dict[str, str], document_id: int) -> List[Dict]:
    with _client(cookies) as c:
        r = c.get(f"/api/documents/{document_id}/versions")
        r.raise_for_status()
        return r.json()


async def api_list_versions_async(cookies: Dict[str, str], document_id: int) -> List[Dict]:
    async with _async_client(cookies) as c:
        r = await c.get(f"/api/documents/{document_id}/versions")
        r.raise_for_status()
        return r.json()


def api_restore_version(cookies: Dict[str, str], document_id: int, version_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.post(f"/api/documents/{document_id}/restore/{version_id}")
        r.raise_for_status()
        return r.json()


async def api_restore_version_async(cookies: Dict[str, str], document_id: int, version_id: int) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.post(f"/api/documents/{document_id}/restore/{version_id}")
        r.raise_for_status()
        return r.json()


def api_delete_document(cookies: Dict[str, str], document_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.delete(f"/api/documents/{document_id}")
        r.raise_for_status()
        return r.json()


async def api_delete_document_async(cookies: Dict[str, str], document_id: int) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.delete(f"/api/documents/{document_id}")
        r.raise_for_status()
        return r.json()


def api_import_document(cookies: Dict[str, str], project_id: int, title: str,
                        filename: str, file_bytes: bytes) -> Dict:
    with _client(cookies) as c:
        r = c.post(
            "/api/documents/import",
            data={"project_id": project_id, "title": title},
            files={"file": (filename, file_bytes, "application/octet-stream")}
        )
        r.raise_for_status()
        return r.json()


async def api_import_document_async(cookies: Dict[str, str], project_id: int, title: str,
                                    filename: str, file_bytes: bytes) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.post(
            "/api/documents/import",
            data={"project_id": project_id, "title": title},
            files={"file": (filename, file_bytes, "application/octet-stream")}
        )
        r.raise_for_status()
        return r.json()


def api_export_document_url(document_id: int, export_format: str) -> str:
    return f"{BASE_URL}/api/documents/{document_id}/export/{export_format}"


async def api_export_document_async(cookies: Dict[str, str], document_id: int, export_format: str) -> Dict[str, Any]:
    async with _async_client(cookies) as c:
        r = await c.get(f"/api/documents/{document_id}/export/{export_format}")
        if r.status_code >= 400:
            logger.warning("document.export failed status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()
        disposition = r.headers.get("content-disposition", "")
        filename = f"export_{document_id}.{export_format}"
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip().strip('"')
        return {
            "content": r.content,
            "content_type": r.headers.get("content-type", "application/octet-stream").split(";")[0],
            "filename": filename,
        }


# ─── GROUNDING ───────────────────────────────────────────────────────────────

def api_list_sentences(cookies: Dict[str, str], document_id: int) -> List[Dict]:
    with _client(cookies) as c:
        r = c.get(f"/api/documents/{document_id}/sentences")
        r.raise_for_status()
        return r.json()


async def api_list_sentences_async(cookies: Dict[str, str], document_id: int) -> List[Dict]:
    async with _async_client(cookies) as c:
        r = await c.get(f"/api/documents/{document_id}/sentences")
        r.raise_for_status()
        return r.json()


def api_search_evidence(cookies: Dict[str, str], sentence_id: int) -> List[Dict]:
    with _client(cookies) as c:
        r = c.post("/api/sentences/search/evidence", json={"sentence_id": sentence_id})
        r.raise_for_status()
        return r.json()


async def api_search_evidence_async(cookies: Dict[str, str], sentence_id: int) -> List[Dict]:
    async with _async_client(cookies) as c:
        # This request owns the complete bounded AI workflow. The generic UI
        # timeout must not turn an operation still running into an empty result.
        r = await c.post(
            "/api/sentences/search/evidence",
            json={"sentence_id": sentence_id},
            timeout=None,
        )
        if r.status_code == 409:
            try:
                detail = r.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            raise EvidenceSearchConflictError(
                detail
                or "Já existe uma busca de evidências em andamento para esta sentença."
            )
        r.raise_for_status()
        return r.json()


def api_update_suggestion_status(cookies: Dict[str, str], suggestion_id: int, status: str) -> Dict:
    with _client(cookies) as c:
        r = c.put(f"/api/evidence-suggestions/{suggestion_id}", json={"status": status})
        r.raise_for_status()
        return r.json()


async def api_update_suggestion_status_async(cookies: Dict[str, str], suggestion_id: int, status: str) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.put(f"/api/evidence-suggestions/{suggestion_id}", json={"status": status})
        r.raise_for_status()
        return r.json()


def api_get_grounding_summary(cookies: Dict[str, str], document_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.get(f"/api/documents/{document_id}/grounding")
        r.raise_for_status()
        return r.json()


async def api_get_grounding_summary_async(cookies: Dict[str, str], document_id: int) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.get(f"/api/documents/{document_id}/grounding")
        r.raise_for_status()
        return r.json()


# ─── REFERENCES ──────────────────────────────────────────────────────────────

def api_list_references(cookies: Dict[str, str], project_id: Optional[int] = None) -> List[Dict]:
    with _client(cookies) as c:
        params = {}
        if project_id is not None:
            params["project_id"] = project_id
        r = c.get("/api/references", params=params)
        r.raise_for_status()
        return r.json()


async def api_list_references_async(cookies: Dict[str, str], project_id: Optional[int] = None) -> List[Dict]:
    async with _async_client(cookies) as c:
        params = {}
        if project_id is not None:
            params["project_id"] = project_id
        r = await c.get("/api/references", params=params)
        r.raise_for_status()
        return r.json()


def api_create_reference(cookies: Dict[str, str], project_id: int, ref: Dict) -> Dict:
    with _client(cookies) as c:
        r = c.post(f"/api/projects/{project_id}/references", json=ref)
        r.raise_for_status()
        return r.json()


async def api_create_reference_async(cookies: Dict[str, str], project_id: int, ref: Dict) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.post(f"/api/projects/{project_id}/references", json=ref)
        r.raise_for_status()
        return r.json()


def api_update_reference(cookies: Dict[str, str], reference_id: int, ref: Dict) -> Dict:
    with _client(cookies) as c:
        r = c.put(f"/api/references/{reference_id}", json=ref)
        r.raise_for_status()
        return r.json()


async def api_update_reference_async(cookies: Dict[str, str], reference_id: int, ref: Dict) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.put(f"/api/references/{reference_id}", json=ref)
        r.raise_for_status()
        return r.json()


def api_delete_reference(cookies: Dict[str, str], reference_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.delete(f"/api/references/{reference_id}")
        r.raise_for_status()
        return r.json()


async def api_delete_reference_async(cookies: Dict[str, str], reference_id: int) -> Dict:
    async with _async_client(cookies) as c:
        r = await c.delete(f"/api/references/{reference_id}")
        r.raise_for_status()
        return r.json()


def api_import_references(cookies: Dict[str, str], project_id: int,
                           filename: str, file_bytes: bytes) -> List[Dict]:
    with _client(cookies) as c:
        r = c.post(
            f"/api/projects/{project_id}/references/import",
            files={"file": (filename, file_bytes, "application/octet-stream")}
        )
        r.raise_for_status()
        return r.json()


async def api_import_references_async(cookies: Dict[str, str], project_id: int,
                                      filename: str, file_bytes: bytes) -> List[Dict]:
    async with _async_client(cookies) as c:
        r = await c.post(
            f"/api/projects/{project_id}/references/import",
            files={"file": (filename, file_bytes, "application/octet-stream")}
        )
        r.raise_for_status()
        return r.json()
