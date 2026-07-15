from app.ui import state
from app.ui.pages.dashboard import _select_valid_current_project

#g
def test_clear_project_context_clears_project_and_document(monkeypatch) -> None:
    storage = {
        "current_project": {"id": 9, "name": "Projeto excluído"},
        "current_document": {"id": 27, "project_id": 9},
    }
    monkeypatch.setattr(state, "get_current_project", lambda: storage["current_project"])
    monkeypatch.setattr(
        state, "set_current_project", lambda project: storage.__setitem__("current_project", project)
    )
    monkeypatch.setattr(
        state, "set_current_document", lambda document: storage.__setitem__("current_document", document)
    )

    assert state.clear_project_context(9) is True
    assert storage["current_project"] == {}
    assert storage["current_document"] == {}


def test_deleted_project_is_not_selected_by_dashboard(monkeypatch) -> None:
    storage = {
        "current_project": {"id": 9, "name": "Projeto excluído"},
        "current_document": {"id": 27, "project_id": 9},
    }
    monkeypatch.setattr(state, "get_current_project", lambda: storage["current_project"])
    monkeypatch.setattr(
        state, "set_current_project", lambda project: storage.__setitem__("current_project", project)
    )
    monkeypatch.setattr(
        state, "set_current_document", lambda document: storage.__setitem__("current_document", document)
    )

    selected = _select_valid_current_project([{"id": 10, "name": "Outro projeto"}])

    assert selected == {}
    assert storage["current_project"] == {}
    assert storage["current_document"] == {}
