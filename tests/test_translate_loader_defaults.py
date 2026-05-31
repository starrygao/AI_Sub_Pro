import json


def test_translate_loader_applies_safe_defaults(tmp_project_dir, monkeypatch):
    """Legacy projects loaded through api/translate._load_project must get safe defaults."""
    import app.api.translate as translate_mod
    monkeypatch.setattr(translate_mod, "PROJECTS_DIR", tmp_project_dir, raising=False)

    pid = "legacy_translate"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "old",
        "video_path": "/old.mp4",
        "status": "completed",
        "progress": 100,
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = translate_mod._load_project(pid)

    # Existing preserved
    assert loaded["status"] == "completed"
    # New fields defaulted (same contract as projects.py loader)
    assert loaded["source_type"] == "upload"
    assert loaded["auto_run"] is False
    assert loaded["original_language"] is None
    assert loaded["tmdb_id"] is None
    assert loaded["pipeline_stage"] is None
    assert loaded["archived"] is False


def test_translate_loader_defaults_asr_skipped(tmp_project_dir, monkeypatch):
    """asr_skipped is written by the trailer pipeline; _apply_safe_defaults
    must declare it so reload-after-restart returns a closed schema."""
    import app.api.translate as translate_mod
    monkeypatch.setattr(translate_mod, "PROJECTS_DIR", tmp_project_dir, raising=False)

    pid = "pre_phase5_proj"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid, "name": "pre", "video_path": "/x.mp4",
        "status": "completed", "progress": 100,
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = translate_mod._load_project(pid)
    assert "asr_skipped" in loaded, "asr_skipped must be present in defaulted schema"
    assert loaded["asr_skipped"] is False
