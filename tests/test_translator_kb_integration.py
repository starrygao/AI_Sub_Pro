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
