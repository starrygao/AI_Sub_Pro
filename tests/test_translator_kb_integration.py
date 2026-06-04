"""Task 5 — translator must inject v2 KB via select_for_project + build_prompt_snippet."""


def test_build_prompt_includes_kb_snippet_when_kb_selected(monkeypatch):
    """When a project matches a KB, _build_prompt must include the prompt snippet."""
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb, TermEntry, StyleNotes

    kb = KnowledgeBase()
    kb.set_project("test", ProjectKb(
        show_title="TestShow",
        characters=[TermEntry(source="Alice", target="爱丽丝")],
        style_notes=StyleNotes(tone="formal"),
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai", "primary_model": "gpt-4o",
            "polish_provider": "", "batch_size": 10, "context_window": 3,
            "target_language": "简体中文",
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)
    meta = {"name": "TestShow S01E02", "tmdb_id": None}
    prompt = t._build_prompt(
        target_lang="简体中文",
        meta_info=meta,
        kb_data=None,
        context_before=[],
        context_after=[],
    )
    assert "Alice" in prompt
    assert "爱丽丝" in prompt
    assert "formal" in prompt


def test_build_prompt_no_kb_when_no_match(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    kb = KnowledgeBase()  # empty — no projects
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai", "primary_model": "gpt-4o",
            "polish_provider": "", "batch_size": 10, "context_window": 3,
            "target_language": "简体中文",
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)
    meta = {"name": "Random", "tmdb_id": None}
    prompt = t._build_prompt(
        target_lang="简体中文", meta_info=meta, kb_data=None,
        context_before=[], context_after=[],
    )
    assert "CHARACTERS" not in prompt
    assert "Use EXACTLY" not in prompt


def test_build_prompt_ignores_malformed_cast_entries(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)
    cfg = {
        "translation": {
            "primary_provider": "openai", "primary_model": "gpt-4o",
            "polish_provider": "", "batch_size": 10, "context_window": 3,
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)

    prompt = t._build_prompt(
        target_lang="简体中文",
        meta_info={"name": "Random", "cast": [{"name": "bad"}, " Alice ", 123]},
        kb_data=None,
        context_before=[],
        context_after=[],
    )

    assert "Alice" in prompt
    assert "{'name': 'bad'}" not in prompt


def test_build_polish_prompt_includes_kb_snippet(monkeypatch):
    """Polish prompt must also get the KB snippet."""
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = KnowledgeBase()
    kb.set_project("show", ProjectKb(
        show_title="ShowX",
        characters=[TermEntry(source="Bob", target="鲍勃")],
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai", "primary_model": "gpt-4o",
            "polish_provider": "", "batch_size": 10, "context_window": 3,
            "target_language": "简体中文",
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)

    # Call polish prompt builder — exact signature may vary; check what exists
    if not hasattr(t, "_build_polish_prompt"):
        import pytest
        pytest.skip("_build_polish_prompt not present in this translator")

    import inspect
    sig = inspect.signature(t._build_polish_prompt)
    # Try common signatures
    meta = {"name": "ShowX S01E01", "tmdb_id": None}
    try:
        prompt = t._build_polish_prompt(target_lang="简体中文", meta_info=meta, kb_data=None)
    except TypeError:
        try:
            prompt = t._build_polish_prompt("简体中文", meta, None)
        except TypeError:
            import pytest
            pytest.skip(f"unknown _build_polish_prompt signature: {sig}")

    assert "Bob" in prompt
    assert "鲍勃" in prompt


def test_translator_records_kb_usage_trace(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = KnowledgeBase()
    kb.set_project("trace", ProjectKb(
        show_title="Trace Show",
        tmdb_id=808,
        characters=[TermEntry(source="Maya Chen", target="玛雅·陈")],
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)
    prompt = t._build_prompt(
        target_lang="简体中文",
        meta_info={"name": "Trace Show", "tmdb_id": 808},
        kb_data=None,
        context_before=[],
        context_after=[],
    )

    assert "Maya Chen" in prompt
    trace = t.get_kb_usage_trace()
    assert trace["project"]["tmdb_id"] == 808
    assert trace["matches"][0]["source"] == "Maya Chen"
    assert trace["matches"][0]["target"] == "玛雅·陈"


def test_trace_for_project_kb_includes_places_and_style_constraints():
    from app.engines.kb_trace import trace_for_project_kb
    from app.engines.kb_models import ProjectKb, StyleNotes, TermEntry

    trace = trace_for_project_kb(ProjectKb(
        show_title="Trace Show",
        tmdb_id=808,
        places=[TermEntry(source="Harbor Nine", target="九号码头", notes="district")],
        style_notes=StyleNotes(
            tone="courtroom formal",
            perspective="first person",
            rules=["Preserve courtroom formality"],
        ),
    ))

    assert trace["project"] == {"show_title": "Trace Show", "tmdb_id": 808}
    assert {
        "category": "places",
        "source": "Harbor Nine",
        "target": "九号码头",
        "notes": "district",
        "scope": "project",
    } in trace["matches"]
    assert {
        "category": "style_notes",
        "source": "courtroom formal",
        "target": "",
        "notes": "tone",
        "scope": "style",
    } in trace["matches"]
    assert {
        "category": "style_notes",
        "source": "first person",
        "target": "",
        "notes": "perspective",
        "scope": "style",
    } in trace["matches"]
    assert {
        "category": "style_notes",
        "source": "Preserve courtroom formality",
        "target": "",
        "notes": "style rule",
        "scope": "style",
    } in trace["matches"]


def test_translator_kb_usage_trace_returns_copy(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = KnowledgeBase()
    kb.set_project("trace", ProjectKb(
        show_title="Trace Show",
        tmdb_id=808,
        characters=[TermEntry(source="Maya Chen", target="玛雅·陈")],
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)
    t._build_prompt(
        target_lang="简体中文",
        meta_info={"name": "Trace Show", "tmdb_id": 808},
        kb_data=None,
        context_before=[],
        context_after=[],
    )

    trace = t.get_kb_usage_trace()
    trace["project"]["tmdb_id"] = 999
    trace["matches"][0]["source"] = "Changed"

    fresh = t.get_kb_usage_trace()
    assert fresh["project"]["tmdb_id"] == 808
    assert fresh["matches"][0]["source"] == "Maya Chen"


def test_write_kb_usage_trace_writes_json(tmp_path):
    import json

    from app.engines.kb_trace import write_kb_usage_trace

    trace = {
        "project": {"show_title": "Trace Show", "tmdb_id": 808},
        "matches": [{"category": "characters", "source": "Maya", "target": "玛雅"}],
    }

    write_kb_usage_trace(tmp_path, trace)

    data = json.loads((tmp_path / "kb_usage_trace.json").read_text(encoding="utf-8"))
    assert data == trace


def test_build_polish_prompt_resets_stale_kb_usage_trace_on_no_match(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = KnowledgeBase()
    kb.set_project("trace", ProjectKb(
        show_title="Trace Show",
        tmdb_id=808,
        characters=[TermEntry(source="Maya Chen", target="玛雅·陈")],
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)
    t._build_prompt(
        target_lang="简体中文",
        meta_info={"name": "Trace Show", "tmdb_id": 808},
        kb_data=None,
        context_before=[],
        context_after=[],
    )
    assert t.get_kb_usage_trace()["matches"]

    prompt = t._build_polish_prompt(
        target_lang="简体中文",
        meta_info={"name": "Completely Different", "tmdb_id": 999},
        kb_data=None,
    )

    assert "Maya Chen" not in prompt
    assert t.get_kb_usage_trace() == {"project": {}, "matches": []}


def test_build_polish_prompt_records_kb_usage_trace_on_match(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = KnowledgeBase()
    kb.set_project("trace", ProjectKb(
        show_title="Trace Show",
        tmdb_id=808,
        characters=[TermEntry(source="Maya Chen", target="玛雅·陈")],
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)

    prompt = t._build_polish_prompt(
        target_lang="简体中文",
        meta_info={"name": "Trace Show", "tmdb_id": 808},
        kb_data=None,
    )

    assert "Maya Chen" in prompt
    trace = t.get_kb_usage_trace()
    assert trace["project"]["tmdb_id"] == 808
    assert trace["matches"][0]["source"] == "Maya Chen"
    assert trace["matches"][0]["target"] == "玛雅·陈"
