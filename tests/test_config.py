import json
import importlib

from app.config import DEFAULT_CONFIG


def test_default_config_has_tmdb_section():
    assert "tmdb" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["tmdb"] == {"api_key": "", "language": "zh-CN"}


def test_default_config_has_providers_claude_cli():
    assert "providers" in DEFAULT_CONFIG
    cc = DEFAULT_CONFIG["providers"]["claude_cli"]
    assert cc["enabled"] is True
    assert cc["model"] == "claude-opus-4-7"
    assert cc["timeout_sec"] == 180

    codex = DEFAULT_CONFIG["providers"]["codex_cli"]
    assert codex["enabled"] is True
    assert codex["model"] == "gpt-5.5"
    assert codex["timeout_sec"] == 180


def test_default_config_has_concurrency_section():
    c = DEFAULT_CONFIG["concurrency"]
    assert c["asr"] == 2
    assert c["translate"] == 4
    assert c["download"] == 3
    assert c["burn"] == 1


def test_default_config_translation_has_full_doc_mode():
    assert DEFAULT_CONFIG["translation"]["full_doc_mode"] is False


def test_default_config_follows_system_display_language():
    assert DEFAULT_CONFIG["general"]["display_language"] == "auto"


def test_default_config_uses_packaging_friendly_asr_model():
    assert DEFAULT_CONFIG["asr"]["model_size"] == "large-v3-turbo"


def test_config_loads_and_merges_partial_saved_config(tmp_path, monkeypatch):
    """Old config.json without new sections still loads; new keys populate from DEFAULT_CONFIG."""
    import app.config as cfg
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", cfg_file)

    old = {
        "api_keys": {"openai": "sk-legacy"},
        "translation": {"primary_provider": "openai", "primary_model": "gpt-4o"},
    }
    cfg_file.write_text(json.dumps(old))

    cfg.Config._data = {}  # reset class-level state
    cfg.Config.load()
    loaded = cfg.Config.to_dict()

    # Existing values preserved
    assert loaded["api_keys"]["openai"] == "sk-legacy"
    assert loaded["translation"]["primary_provider"] == "openai"
    # New sections auto-populated from DEFAULT_CONFIG
    assert loaded["tmdb"]["language"] == "zh-CN"
    assert loaded["concurrency"]["asr"] == 2
    assert loaded["providers"]["claude_cli"]["enabled"] is True
    assert loaded["providers"]["codex_cli"]["enabled"] is True
    assert loaded["translation"]["full_doc_mode"] is False
    assert loaded["general"]["display_language"] == "auto"


def test_config_load_ignores_non_object_saved_sections(tmp_path, monkeypatch):
    """Legacy or hand-edited config must not replace object sections with bad types."""
    import app.config as cfg
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", cfg_file)

    cfg_file.write_text(json.dumps({
        "concurrency": ["bad"],
        "translation": None,
        "providers": {"claude_cli": "bad"},
    }))

    cfg.Config._data = {}
    cfg.Config.load()
    loaded = cfg.Config.to_dict()

    assert loaded["concurrency"] == cfg.DEFAULT_CONFIG["concurrency"]
    assert loaded["translation"] == cfg.DEFAULT_CONFIG["translation"]
    assert loaded["providers"]["claude_cli"] == cfg.DEFAULT_CONFIG["providers"]["claude_cli"]
    assert loaded["providers"]["codex_cli"] == cfg.DEFAULT_CONFIG["providers"]["codex_cli"]


def test_config_load_normalizes_invalid_display_language(tmp_path, monkeypatch):
    import app.config as cfg
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", cfg_file)

    cfg_file.write_text(json.dumps({
        "general": {
            "display_language": "fr-FR",
        },
    }))

    cfg.Config._data = {}
    cfg.Config.load()

    assert cfg.Config.to_dict()["general"]["display_language"] == "auto"
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["general"]["display_language"] == "auto"


def test_config_load_rejects_nonstandard_json_constants(tmp_path, monkeypatch):
    import app.config as cfg

    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", cfg_file)
    cfg_file.write_text('{"concurrency": {"asr": NaN}}', encoding="utf-8")

    cfg.Config._data = {}
    cfg.Config.load()

    assert cfg.Config.to_dict()["concurrency"] == cfg.DEFAULT_CONFIG["concurrency"]
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["concurrency"] == cfg.DEFAULT_CONFIG["concurrency"]


def test_config_load_backs_up_invalid_config_before_writing_defaults(tmp_path, monkeypatch):
    import app.config as cfg

    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", cfg_file)
    cfg_file.write_text('{"api_keys": {"openai": "sk-user"', encoding="utf-8")

    cfg.Config._data = {}
    cfg.Config.load()

    backups = sorted(tmp_path.glob("config.invalid-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"api_keys": {"openai": "sk-user"'
    assert json.loads(cfg_file.read_text(encoding="utf-8")) == cfg.DEFAULT_CONFIG


def test_config_load_does_not_share_nested_defaults(tmp_path, monkeypatch):
    from app import config as cfg

    target = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", target)
    cfg.Config._data = {}
    cfg.Config.load()

    cfg.Config.set_val("api_keys", "openai", "sk-runtime")

    assert cfg.DEFAULT_CONFIG["api_keys"]["openai"] == ""


def test_config_to_dict_returns_deep_copy():
    from app import config as cfg

    cfg.Config._data = {"api_keys": {"openai": "sk-original"}}
    exported = cfg.Config.to_dict()
    exported["api_keys"]["openai"] = "sk-mutated"

    assert cfg.Config._data["api_keys"]["openai"] == "sk-original"


def test_config_save_is_atomic(tmp_path, monkeypatch):
    import json as _json
    from app import config as cfg

    target = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", target)
    cfg.Config._data = {"k": "v"}

    real_dump = _json.dump

    def boom(*a, **k):
        raise RuntimeError("disk full")

    target.write_text('{"existing": 1}', encoding="utf-8")
    monkeypatch.setattr("app.utils.project_store.json.dump", boom)
    import pytest
    with pytest.raises(RuntimeError):
        cfg.Config.save()
    # original file survived the failed write
    assert _json.loads(target.read_text(encoding="utf-8")) == {"existing": 1}
    assert not (tmp_path / "config.json.tmp").exists()


def test_config_honors_ai_sub_pro_data_dir_env(tmp_path, monkeypatch):
    import app.config as cfg

    runtime_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("AI_SUB_PRO_DATA_DIR", str(runtime_dir))
    reloaded = importlib.reload(cfg)
    try:
        assert reloaded.DATA_DIR == runtime_dir
        assert reloaded.PROJECTS_DIR == runtime_dir / "projects"
        assert reloaded.CONFIG_FILE == runtime_dir / "config.json"
        assert reloaded.KB_FILE == runtime_dir / "knowledge.json"
        assert reloaded.DATA_DIR.exists()
        assert reloaded.PROJECTS_DIR.exists()
    finally:
        monkeypatch.delenv("AI_SUB_PRO_DATA_DIR", raising=False)
        importlib.reload(cfg)
