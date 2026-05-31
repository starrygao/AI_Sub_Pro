import json


def test_startup_restores_progress_from_disk(tmp_project_dir):
    pdir = tmp_project_dir / "restored"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 55, "stage": "translate", "message": "pre-crash",
        "updated_at": "2026-04-19T00:00:00",
    }))

    from fastapi.testclient import TestClient
    from app.main import app
    from app.engines.scheduler import progress_store

    progress_store.clear()

    with TestClient(app):  # triggers startup event
        pass

    assert "restored" in progress_store
    assert progress_store["restored"]["progress"] == 55
    assert progress_store["restored"]["stage"] == "translate"
