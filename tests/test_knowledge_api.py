import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def patched_kb_file(tmp_path, monkeypatch):
    import app.config as cfg
    import app.engines.knowledge as kb_mod

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(cfg, "KB_FILE", kb_file, raising=False)
    monkeypatch.setattr(kb_mod, "KB_FILE", kb_file)
    monkeypatch.setattr(kb_mod, "LEGACY_KB", tmp_path / "legacy.json", raising=False)

    # Reset module-level singleton in knowledge module
    monkeypatch.setattr(kb_mod, "_singleton", None, raising=False)

    # Replace translator's shared KB with a fresh instance pointing at the patched file
    try:
        import app.engines.translator as tmod
        monkeypatch.setattr(tmod, "_shared_kb", kb_mod.KnowledgeBase(), raising=False)
    except ImportError:
        pass

    # Replace API module's local KB if it has one
    try:
        import app.api.knowledge as kbapi
        monkeypatch.setattr(kbapi, "_kb", kb_mod.KnowledgeBase(), raising=False)
    except Exception:
        pass

    return kb_file


def test_kb_list_projects_empty(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    r = client.get("/api/knowledge/projects")
    assert r.status_code == 200
    assert r.json() == {"projects": []}


def test_accepted_terms_from_chinese_named_episodes_share_the_same_show_kb(tmp_project_dir,patched_kb_file):
    from app.engines.kb_suggestions import KbSuggestion,save_suggestions
    from app.engines.knowledge import _get_singleton
    from app.main import app
    from app.utils.project_store import atomic_write_json
    client=TestClient(app)
    for pid,source,target in [('episode_one','Maya','玛雅'),('episode_two','Alex','亚历克斯')]:
        pdir=tmp_project_dir/pid
        atomic_write_json(pdir/'project.json',{'id':pid,'name':pid,'show_title':'世界在起舞','tmdb_id':312020,'tmdb_type':'tv'})
        suggestion=KbSuggestion(source=source,category='characters')
        save_suggestions(pdir/'kb_suggestions.json',[suggestion])
        response=client.post(f'/api/knowledge/projects/{pid}/suggestions/{suggestion.id}/status',json={'status':'accepted','target':target})
        assert response.status_code==200
    entries=client.get('/api/knowledge/projects').json()['projects']
    assert len(entries)==1
    kb=_get_singleton().select_for_project({'tmdb_id':312020,'tmdb_type':'tv'})
    assert {t.source for t in kb.characters}=={'Maya','Alex'}


def test_same_tmdb_number_in_movie_and_tv_does_not_share_terminology(patched_kb_file):
    from app.main import app
    from app.engines.knowledge import _get_singleton
    client=TestClient(app)
    for kind,target in [('movie','电影译名'),('tv','剧集译名')]:
        response=client.put('/api/knowledge/projects/'+kind,json={'key':kind,'show_title':kind,'tmdb_id':42,'tmdb_type':kind,'characters':[{'source':'Hero','target':target}]})
        assert response.status_code==200
    store=_get_singleton()
    assert store.select_for_project({'tmdb_id':42,'tmdb_type':'tv'}).characters[0].target=='剧集译名'


def test_previewed_unsaved_candidate_can_be_accepted(tmp_project_dir,patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json
    client=TestClient(app);pid='previewed_candidate';pdir=tmp_project_dir/pid
    atomic_write_json(pdir/'project.json',{'id':pid,'name':'Example','characters':['Maya Chen']})
    (pdir/'raw.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nMaya Chen visited New York.\n')
    suggestions=client.get(f'/api/knowledge/projects/{pid}/suggestions').json()['suggestions']
    assert suggestions
    item=suggestions[0]
    response=client.post(f'/api/knowledge/projects/{pid}/suggestions/{item["id"]}/status',json={'status':'accepted','target':'审定测试译文'})
    assert response.status_code==200


def test_kb_clean_text_rejects_non_string_values():
    from app.api.knowledge import _clean_text

    assert _clean_text(123) == ""
    assert _clean_text(None) == ""
    assert _clean_text("  ok  ") == "ok"


def test_kb_create_and_get_project(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    payload = {
        "key": "elsbeth",
        "show_title": "Elsbeth",
        "tmdb_id": 1399,
        "characters": [{"source": "Elsbeth Tascioni", "target": "艾尔斯贝丝"}],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "sharp legal humor", "perspective": "", "rules": []},
    }
    r = client.put("/api/knowledge/projects/elsbeth", json=payload)
    assert r.status_code in (200, 201)

    r = client.get("/api/knowledge/projects/elsbeth")
    assert r.status_code == 200
    data = r.json()
    assert data["show_title"] == "Elsbeth"
    assert data["characters"][0]["source"] == "Elsbeth Tascioni"


def test_kb_put_rejects_body_key_mismatch(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/path-key", json={
        "key": "body-key",
        "show_title": "Mismatch",
        "characters": [],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })

    assert r.status_code == 400
    assert "key" in r.json()["detail"]


def test_kb_put_rejects_blank_key(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/%20%20", json={
        "key": "  ",
        "show_title": "Blank",
        "characters": [],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })

    assert r.status_code == 400
    assert "key" in r.json()["detail"]


def test_kb_put_rejects_non_positive_tmdb_id(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/show", json={
        "key": "show",
        "show_title": "Show",
        "tmdb_id": 0,
        "characters": [],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })

    assert r.status_code == 400
    assert "tmdb_id" in r.json()["detail"]


def test_kb_put_rejects_boolean_tmdb_id(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/show", json={
        "key": "show",
        "show_title": "Show",
        "tmdb_id": True,
        "characters": [],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })

    assert r.status_code == 422


def test_kb_put_drops_blank_terms_and_rules(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/clean", json={
        "key": "clean",
        "show_title": " Clean Show ",
        "characters": [
            {"source": "", "target": "", "notes": ""},
            {"source": "  Name  ", "target": "  名字  ", "notes": " lead "},
            {"source": "NoTarget", "target": "", "notes": ""},
        ],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "  witty  ", "perspective": "", "rules": ["", " keep jokes "]},
    })

    assert r.status_code == 200
    data = client.get("/api/knowledge/projects/clean").json()
    assert data["show_title"] == "Clean Show"
    assert data["characters"] == [{"source": "Name", "target": "名字", "notes": "lead"}]
    assert data["style_notes"]["tone"] == "witty"
    assert data["style_notes"]["rules"] == ["keep jokes"]


def test_kb_list_projects_after_put(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    client.put("/api/knowledge/projects/x", json={
        "key": "x", "show_title": "X-Show", "tmdb_id": 42,
        "characters": [], "places": [], "brands": [], "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })
    r = client.get("/api/knowledge/projects")
    assert r.status_code == 200
    projects = r.json()["projects"]
    assert len(projects) == 1
    assert projects[0]["key"] == "x"
    assert projects[0]["show_title"] == "X-Show"
    assert projects[0]["tmdb_id"] == 42


def test_kb_delete_project(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    client.put("/api/knowledge/projects/temp", json={
        "key": "temp", "show_title": "Temp",
        "characters": [], "places": [], "brands": [], "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })
    r = client.delete("/api/knowledge/projects/temp")
    assert r.status_code == 200

    r = client.get("/api/knowledge/projects/temp")
    assert r.status_code == 404


def test_kb_get_nonexistent_returns_404(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    r = client.get("/api/knowledge/projects/nonexistent")
    assert r.status_code == 404


def test_kb_saved_upserts_preserve_existing_projects(patched_kb_file):
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb

    kb = KnowledgeBase()
    kb.load()
    kb.put_project("one", ProjectKb(show_title="One"))
    kb.put_project("two", ProjectKb(show_title="Two"))

    reloaded = KnowledgeBase()
    reloaded.load()
    assert reloaded.get_project("one").show_title == "One"
    assert reloaded.get_project("two").show_title == "Two"


def test_kb_suggestions_endpoint_returns_project_suggestions(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_suggest"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Moonlit Case",
        "tmdb_id": 101,
        "cast": ["Maya Chen"],
        "overview": "Maya Chen visits the Moonlit Club.",
    })
    (pdir / "raw.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nMaya Chen enters the Moonlit Club.\n\n",
        encoding="utf-8",
    )

    response = client.get(f"/api/knowledge/projects/{pid}/suggestions")

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == pid
    assert any(item["source"] == "Maya Chen" for item in data["suggestions"])


def test_kb_usage_trace_endpoint_returns_existing_trace(tmp_project_dir, patched_kb_file):
    import json

    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_trace"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case"})
    trace = {
        "project": {"show_title": "Moonlit Case"},
        "matches": [
            {"category": "characters", "source": "Maya Chen", "target": "玛雅·陈"},
            "bad-row",
        ],
        "extra": "kept",
    }
    (pdir / "kb_usage_trace.json").write_text(json.dumps(trace), encoding="utf-8")

    response = client.get(f"/api/knowledge/projects/{pid}/usage-trace")

    assert response.status_code == 200
    assert response.json() == {
        "project": {"show_title": "Moonlit Case"},
        "matches": [
            {"category": "characters", "source": "Maya Chen", "target": "玛雅·陈"},
        ],
        "extra": "kept",
    }


def test_kb_usage_trace_endpoint_merges_translation_quality_context(tmp_project_dir, patched_kb_file):
    import json

    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_trace_quality"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case"})
    (pdir / "kb_usage_trace.json").write_text(json.dumps({
        "project": {"show_title": "Moonlit Case"},
        "matches": [{"category": "characters", "source": "Maya Chen", "target": "玛雅·陈"}],
    }), encoding="utf-8")
    (pdir / "translation_qa_report.json").write_text(json.dumps({
        "status": "needs_review",
        "trace": {
            "phrase_hits": [{"source_text": "Shoot your shot.", "target_text": "主动出击。"}],
            "profile_hits": [{"id": "medical_drama", "label": "Medical drama"}],
            "style_hits": [{"scope": "subtitle_style", "id": "zh_cn_general"}],
            "auto_repair_rounds": [{"candidate_blocks": 5, "attempted_blocks": 2}],
        },
    }), encoding="utf-8")

    response = client.get(f"/api/knowledge/projects/{pid}/usage-trace")

    assert response.status_code == 200
    data = response.json()
    assert data["matches"] == [
        {"category": "characters", "source": "Maya Chen", "target": "玛雅·陈"},
    ]
    assert data["phrase_hits"] == [{"source_text": "Shoot your shot.", "target_text": "主动出击。"}]
    assert data["profile_hits"] == [{"id": "medical_drama", "label": "Medical drama"}]
    assert data["style_hits"] == [{"scope": "subtitle_style", "id": "zh_cn_general"}]
    assert data["auto_repair_rounds"] == [{"candidate_blocks": 5, "attempted_blocks": 2}]


def test_kb_usage_trace_ignores_quality_context_while_delivery_is_invalid(
    tmp_project_dir,
    patched_kb_file,
):
    import json

    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_trace_invalid_delivery"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case"})
    (pdir / "kb_usage_trace.json").write_text(json.dumps({
        "project": {"show_title": "Moonlit Case"},
        "matches": [{"category": "characters", "source": "Maya Chen", "target": "玛雅·陈"}],
    }), encoding="utf-8")
    (pdir / "translation_qa_report.json").write_text(json.dumps({
        "status": "ok",
        "trace": {
            "phrase_hits": [{"source_text": "Stale phrase.", "target_text": "旧短语。"}],
            "profile_hits": [{"id": "stale_profile", "label": "Stale"}],
        },
        "subtitle_id_mapping": {
            "translated_srt": [{"source_block_id": 7, "output_id": 1}],
        },
    }), encoding="utf-8")
    (pdir / ".translation_delivery_in_progress").write_text(
        '{"status":"invalid"}',
        encoding="utf-8",
    )

    response = client.get(f"/api/knowledge/projects/{pid}/usage-trace")

    assert response.status_code == 200
    assert response.json() == {
        "project": {"show_title": "Moonlit Case"},
        "matches": [
            {"category": "characters", "source": "Maya Chen", "target": "玛雅·陈"},
        ],
    }


def test_kb_usage_trace_endpoint_missing_file_returns_empty_trace(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_trace_missing"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case"})

    response = client.get(f"/api/knowledge/projects/{pid}/usage-trace")

    assert response.status_code == 200
    assert response.json() == {"project": {}, "matches": []}


def test_kb_usage_trace_endpoint_returns_404_for_missing_project(patched_kb_file):
    from app.main import app

    client = TestClient(app)

    response = client.get("/api/knowledge/projects/missing_trace_project/usage-trace")

    assert response.status_code == 404


def test_kb_usage_trace_endpoint_rejects_corrupt_json(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_trace_corrupt"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case"})
    (pdir / "kb_usage_trace.json").write_text("{not json", encoding="utf-8")

    response = client.get(f"/api/knowledge/projects/{pid}/usage-trace")

    assert response.status_code == 400
    assert response.json()["detail"] == "KB usage trace file is invalid"


def test_kb_accept_suggestions_persists_entries(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_accept"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "moonlit",
        "show_title": "Moonlit Case",
        "tmdb_id": 101,
        "entries": [
            {"source": "Maya Chen", "target": "玛雅·陈", "category": "characters", "notes": "lead"}
        ],
    })

    assert response.status_code == 200
    saved = client.get("/api/knowledge/projects/moonlit").json()
    assert saved["characters"][0]["source"] == "Maya Chen"
    assert saved["characters"][0]["target"] == "玛雅·陈"


def test_kb_reject_suggestions_persists_project_decision(tmp_project_dir, patched_kb_file):
    import json

    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_reject"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/reject", json={
        "sources": ["Noisy Phrase", "Unused Name"]
    })

    assert response.status_code == 200
    data = json.loads((pdir / "kb_suggestion_decisions.json").read_text(encoding="utf-8"))
    assert data["rejected_sources"] == ["Noisy Phrase", "Unused Name"]


def test_kb_suggestion_status_rejects_accept_without_target(tmp_project_dir, patched_kb_file):
    import json

    from app.engines.kb_suggestions import KbSuggestion, save_suggestions
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_status_blank"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case"})
    save_suggestions(pdir / "kb_suggestions.json", [
        KbSuggestion(id="character:maya-chen", source="Maya Chen", target="", category="characters")
    ])

    response = client.post(
        f"/api/knowledge/projects/{pid}/suggestions/character%3Amaya-chen/status",
        json={"status": "accepted"},
    )

    assert response.status_code == 400
    assert "译文" in response.json()["detail"]
    saved = json.loads((pdir / "kb_suggestions.json").read_text(encoding="utf-8"))
    assert saved["suggestions"][0]["status"] == "pending"


def test_kb_suggestion_status_accepts_with_inline_target(tmp_project_dir, patched_kb_file):
    import json

    from app.engines.kb_suggestions import KbSuggestion, save_suggestions
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_status_inline_target"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case"})
    save_suggestions(pdir / "kb_suggestions.json", [
        KbSuggestion(id="character:maya-chen", source="Maya Chen", target="", category="characters")
    ])

    response = client.post(
        f"/api/knowledge/projects/{pid}/suggestions/character%3Amaya-chen/status",
        json={"status": "accepted", "target": " 玛雅·陈 ", "notes": " 主角 "},
    )

    assert response.status_code == 200
    suggestion = response.json()["suggestion"]
    assert suggestion["status"] == "accepted"
    assert suggestion["target"] == "玛雅·陈"
    assert suggestion["notes"] == "主角"
    saved = json.loads((pdir / "kb_suggestions.json").read_text(encoding="utf-8"))
    assert saved["suggestions"][0]["target"] == "玛雅·陈"
    kb = client.get("/api/knowledge/projects/moonlit-case").json()
    assert kb["characters"][0]["source"] == "Maya Chen"
    assert kb["characters"][0]["target"] == "玛雅·陈"


def test_kb_accept_suggestions_skips_duplicate_blank_target_and_invalid_category(
    tmp_project_dir,
    patched_kb_file,
):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_accept_robust"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})
    client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "moonlit",
        "show_title": "Moonlit Case",
        "tmdb_id": 101,
        "entries": [
            {"source": "Maya Chen", "target": "玛雅·陈", "category": "characters", "notes": "lead"}
        ],
    })

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "moonlit",
        "show_title": "Moonlit Case",
        "tmdb_id": 101,
        "entries": [
            {"source": " maya chen ", "target": "重复", "category": "characters", "notes": ""},
            {"source": "Moonlit Club", "target": "", "category": "places", "notes": ""},
            {"source": "Ignored", "target": "忽略", "category": "unknown", "notes": ""},
            {"source": "Moonlit Club", "target": "月光俱乐部", "category": "places", "notes": ""},
        ],
    })

    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    saved = client.get("/api/knowledge/projects/moonlit").json()
    assert saved["characters"] == [{"source": "Maya Chen", "target": "玛雅·陈", "notes": "lead"}]
    assert saved["places"] == [{"source": "Moonlit Club", "target": "月光俱乐部", "notes": ""}]


def test_kb_suggestions_endpoint_returns_404_for_missing_project(patched_kb_file):
    from app.main import app

    client = TestClient(app)

    response = client.get("/api/knowledge/projects/missing_project/suggestions")

    assert response.status_code == 404


def test_kb_accept_suggestions_rejects_invalid_key_without_persisting(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_bad_key"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "bad/key",
        "show_title": "Moonlit Case",
        "entries": [
            {"source": "Maya Chen", "target": "玛雅·陈", "category": "characters", "notes": "lead"}
        ],
    })

    assert response.status_code == 400
    projects = client.get("/api/knowledge/projects").json()["projects"]
    assert all(project["key"] != "bad/key" for project in projects)


def test_kb_accept_suggestions_rejects_blank_key(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_blank_key"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "  ",
        "entries": [],
    })

    assert response.status_code == 400


def test_kb_accept_suggestions_rejects_non_positive_tmdb_id(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_bad_tmdb"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "moonlit",
        "tmdb_id": 0,
        "entries": [],
    })

    assert response.status_code == 400


def test_kb_reject_suggestions_merges_and_dedupes_project_decisions(tmp_project_dir, patched_kb_file):
    import json

    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_reject_merge"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    first = client.post(f"/api/knowledge/projects/{pid}/suggestions/reject", json={
        "sources": ["Noisy Phrase", "Unused Name"]
    })
    second = client.post(f"/api/knowledge/projects/{pid}/suggestions/reject", json={
        "sources": ["noisy phrase", "New Name", "Unused Name", "  "]
    })

    assert first.status_code == 200
    assert second.status_code == 200
    data = json.loads((pdir / "kb_suggestion_decisions.json").read_text(encoding="utf-8"))
    assert data["rejected_sources"] == ["Noisy Phrase", "Unused Name", "New Name"]


def test_kb_suggestions_endpoint_filters_rejected_sources(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_suggest_rejected"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Moonlit Case",
        "tmdb_id": 101,
        "cast": ["Maya Chen"],
        "overview": "Maya Chen visits the Moonlit Club.",
    })

    reject = client.post(f"/api/knowledge/projects/{pid}/suggestions/reject", json={
        "sources": ["maya chen"]
    })
    response = client.get(f"/api/knowledge/projects/{pid}/suggestions")

    assert reject.status_code == 200
    assert response.status_code == 200
    sources = {item["source"] for item in response.json()["suggestions"]}
    assert "Maya Chen" not in sources
