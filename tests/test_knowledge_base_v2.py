import json


def test_knowledge_base_load_auto_migrates_v1(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "nonexistent_legacy.json", raising=False)

    v1 = {"Elsbeth": {"keywords": [], "style": "sharp", "terms": {"Elsbeth": "艾"}}}
    kb_file.write_text(json.dumps(v1), encoding="utf-8")

    kb = kb_module.KnowledgeBase()
    kb.load()

    proj = kb.get_project("Elsbeth")
    assert proj is not None
    assert proj.show_title == "Elsbeth"
    sources = [t.source for t in proj.characters]
    assert "Elsbeth" in sources

    backup = tmp_path / "knowledge.v1.backup.json"
    assert backup.exists()


def test_knowledge_base_save_writes_v2_format(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb, TermEntry

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "nonexistent_legacy.json", raising=False)

    kb = kb_module.KnowledgeBase()
    proj = ProjectKb(show_title="Test", characters=[TermEntry(source="Hi", target="你好")])
    kb.set_project("Test", proj)
    kb.save()

    data = json.loads(kb_file.read_text())
    assert "Test" in data
    assert data["Test"]["show_title"] == "Test"
    assert data["Test"]["characters"][0]["source"] == "Hi"


def test_knowledge_base_select_by_tmdb_id(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb

    monkeypatch.setattr(kb_module, "KB_FILE", tmp_path / "k.json")
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "l.json", raising=False)
    kb = kb_module.KnowledgeBase()
    kb.set_project("elsbeth_s1", ProjectKb(show_title="Elsbeth", tmdb_id=1399))

    selected = kb.select_for_project({"tmdb_id": 1399, "name": "Random"})
    assert selected is not None
    assert selected.show_title == "Elsbeth"


def test_knowledge_base_select_ignores_boolean_tmdb_id(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb

    monkeypatch.setattr(kb_module, "KB_FILE", tmp_path / "k.json")
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "l.json", raising=False)
    kb = kb_module.KnowledgeBase()
    kb.set_project("one", ProjectKb(show_title="One", tmdb_id=1))

    selected = kb.select_for_project({"tmdb_id": True, "name": "Something unrelated"})

    assert selected is None


def test_knowledge_base_select_ignores_non_string_project_name(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb

    monkeypatch.setattr(kb_module, "KB_FILE", tmp_path / "k.json")
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "l.json", raising=False)
    kb = kb_module.KnowledgeBase()
    kb.set_project("elsbeth", ProjectKb(show_title="Elsbeth"))

    selected = kb.select_for_project({"tmdb_id": None, "name": ["Elsbeth"]})

    assert selected is None


def test_knowledge_base_select_by_show_title_fallback(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb

    monkeypatch.setattr(kb_module, "KB_FILE", tmp_path / "k.json")
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "l.json", raising=False)
    kb = kb_module.KnowledgeBase()
    kb.set_project("elsbeth", ProjectKb(show_title="Elsbeth", tmdb_id=None))

    selected = kb.select_for_project({"tmdb_id": None, "name": "Elsbeth S01E01"})
    assert selected is not None
    assert selected.show_title == "Elsbeth"


def test_knowledge_base_select_returns_none_when_no_match(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb

    monkeypatch.setattr(kb_module, "KB_FILE", tmp_path / "k.json")
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "l.json", raising=False)
    kb = kb_module.KnowledgeBase()
    kb.set_project("foo", ProjectKb(show_title="Foo"))

    selected = kb.select_for_project({"tmdb_id": 999, "name": "Something unrelated"})
    assert selected is None
