"""
VibeScholar API Client
======================
Handles all HTTP calls to the FastAPI backend via httpx.
Centralises authentication cookie management and error handling.
"""
import httpx
from typing import Optional, Any, Dict, List

BASE_URL = "http://127.0.0.1:8080"

def _client(cookies: Optional[Dict[str, str]] = None) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, cookies=cookies or {}, timeout=30)


# ─── AUTH ────────────────────────────────────────────────────────────────────

def api_login(username: str, password: str) -> Dict[str, Any]:
    """Returns (user_data, cookies_dict) or raises."""
    with _client() as c:
        r = c.post("/api/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        return r.json(), dict(r.cookies)


def api_register(username: str, password: str, email: Optional[str] = None) -> Dict[str, Any]:
    with _client() as c:
        payload = {"username": username, "password": password}
        if email:
            payload["email"] = email
        r = c.post("/api/auth/register", json=payload)
        r.raise_for_status()
        return r.json()


def api_logout(cookies: Dict[str, str]) -> None:
    with _client(cookies) as c:
        c.post("/api/auth/logout")


# ─── PROJECTS ────────────────────────────────────────────────────────────────

def api_list_projects(cookies: Dict[str, str]) -> List[Dict]:
    with _client(cookies) as c:
        r = c.get("/api/projects")
        r.raise_for_status()
        return r.json()


def api_create_project(cookies: Dict[str, str], name: str, description: str = "") -> Dict:
    with _client(cookies) as c:
        r = c.post("/api/projects", json={"name": name, "description": description})
        r.raise_for_status()
        return r.json()


def api_delete_project(cookies: Dict[str, str], project_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.delete(f"/api/projects/{project_id}")
        r.raise_for_status()
        return r.json()


def api_get_project_settings(cookies: Dict[str, str], project_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.get(f"/api/projects/{project_id}/settings")
        r.raise_for_status()
        return r.json()


def api_update_project_settings(cookies: Dict[str, str], project_id: int, settings: Dict) -> Dict:
    with _client(cookies) as c:
        r = c.put(f"/api/projects/{project_id}/settings", json=settings)
        r.raise_for_status()
        return r.json()


# ─── DOCUMENTS ───────────────────────────────────────────────────────────────

def api_list_documents(cookies: Dict[str, str], project_id: int) -> List[Dict]:
    with _client(cookies) as c:
        r = c.get(f"/api/projects/{project_id}/documents")
        r.raise_for_status()
        return r.json()


def api_create_document(cookies: Dict[str, str], project_id: int, title: str,
                        description: str = "", content: str = "") -> Dict:
    with _client(cookies) as c:
        r = c.post(f"/api/projects/{project_id}/documents",
                   json={"title": title, "description": description, "content": content})
        r.raise_for_status()
        return r.json()


def api_get_document(cookies: Dict[str, str], document_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.get(f"/api/documents/{document_id}")
        r.raise_for_status()
        return r.json()


def api_autosave_content(cookies: Dict[str, str], document_id: int, content: str) -> Dict:
    with _client(cookies) as c:
        r = c.put(f"/api/documents/{document_id}/content", json={"content": content})
        r.raise_for_status()
        return r.json()


def api_save_version(cookies: Dict[str, str], document_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.post(f"/api/documents/{document_id}/version")
        r.raise_for_status()
        return r.json()


def api_list_versions(cookies: Dict[str, str], document_id: int) -> List[Dict]:
    with _client(cookies) as c:
        r = c.get(f"/api/documents/{document_id}/versions")
        r.raise_for_status()
        return r.json()


def api_restore_version(cookies: Dict[str, str], document_id: int, version_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.post(f"/api/documents/{document_id}/restore/{version_id}")
        r.raise_for_status()
        return r.json()


def api_delete_document(cookies: Dict[str, str], document_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.delete(f"/api/documents/{document_id}")
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


def api_export_document_url(document_id: int, export_format: str) -> str:
    return f"{BASE_URL}/api/documents/{document_id}/export/{export_format}"


# ─── GROUNDING ───────────────────────────────────────────────────────────────

def api_list_sentences(cookies: Dict[str, str], document_id: int) -> List[Dict]:
    with _client(cookies) as c:
        r = c.get(f"/api/documents/{document_id}/sentences")
        r.raise_for_status()
        return r.json()


def api_search_evidence(cookies: Dict[str, str], sentence_id: int) -> List[Dict]:
    with _client(cookies) as c:
        r = c.post("/api/sentences/search/evidence", json={"sentence_id": sentence_id})
        r.raise_for_status()
        return r.json()


def api_update_suggestion_status(cookies: Dict[str, str], suggestion_id: int, status: str) -> Dict:
    with _client(cookies) as c:
        r = c.put(f"/api/evidence-suggestions/{suggestion_id}", json={"status": status})
        r.raise_for_status()
        return r.json()


def api_get_grounding_summary(cookies: Dict[str, str], document_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.get(f"/api/documents/{document_id}/grounding")
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


def api_create_reference(cookies: Dict[str, str], project_id: int, ref: Dict) -> Dict:
    with _client(cookies) as c:
        r = c.post(f"/api/projects/{project_id}/references", json=ref)
        r.raise_for_status()
        return r.json()


def api_update_reference(cookies: Dict[str, str], reference_id: int, ref: Dict) -> Dict:
    with _client(cookies) as c:
        r = c.put(f"/api/references/{reference_id}", json=ref)
        r.raise_for_status()
        return r.json()


def api_delete_reference(cookies: Dict[str, str], reference_id: int) -> Dict:
    with _client(cookies) as c:
        r = c.delete(f"/api/references/{reference_id}")
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
