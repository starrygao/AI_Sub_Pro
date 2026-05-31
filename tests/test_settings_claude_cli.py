"""Tests for claude_cli settings endpoints (status + test-key branch)."""
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_claude_cli_status_endpoint_reports_installed_and_logged_in():
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available", return_value=True), \
         patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_logged_in", return_value=True):
        r = client.get("/api/settings/claude-cli/status")
    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is True
    assert data["logged_in"] is True


def test_claude_cli_status_endpoint_reports_not_installed():
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available", return_value=False):
        r = client.get("/api/settings/claude-cli/status")
    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is False


def test_claude_cli_status_endpoint_tolerates_probe_errors():
    from app.main import app
    client = TestClient(app)

    with patch(
        "app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available",
        side_effect=RuntimeError("probe failed"),
    ):
        r = client.get("/api/settings/claude-cli/status")

    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is False
    assert data["logged_in"] is False


def test_codex_cli_status_endpoint_reports_installed_and_logged_in():
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.providers.codex_cli.CodexCliProvider.check_cli_available", return_value=True), \
         patch("app.engines.providers.codex_cli.CodexCliProvider.check_logged_in", return_value=True):
        r = client.get("/api/settings/codex-cli/status")

    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is True
    assert data["logged_in"] is True


def test_codex_cli_status_endpoint_tolerates_probe_errors():
    from app.main import app
    client = TestClient(app)

    with patch(
        "app.engines.providers.codex_cli.CodexCliProvider.check_cli_available",
        side_effect=RuntimeError("probe failed"),
    ):
        r = client.get("/api/settings/codex-cli/status")

    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is False
    assert data["logged_in"] is False


def test_test_key_supports_claude_cli():
    """POST /api/settings/test-key should accept provider=claude_cli (no api_key needed)."""
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.test_connection", return_value=True):
        r = client.post("/api/settings/test-key", json={"provider": "claude_cli", "model": "claude-opus-4-7"})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True


def test_test_key_supports_codex_cli():
    """POST /api/settings/test-key should accept provider=codex_cli (no api_key needed)."""
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.providers.codex_cli.CodexCliProvider.test_connection", return_value=True):
        r = client.post("/api/settings/test-key", json={"provider": "codex_cli", "model": "gpt-5.5"})

    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True


def test_test_key_rejects_unknown_provider():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/settings/test-key", json={"provider": "not-a-provider"})

    assert r.status_code == 400
    assert "provider" in r.json()["detail"]


def test_test_key_rejects_blank_provider():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/settings/test-key", json={"provider": "  "})

    assert r.status_code == 400
    assert "provider" in r.json()["detail"]


def test_test_key_hides_internal_exception_details():
    from app.main import app
    client = TestClient(app)

    raw_error = (
        "Traceback from /Users/example/Desktop/AI_Sub_Pro/app/secret.py "
        "using key sk-live-secret"
    )
    with patch("app.engines.translator.TranslationProvider", side_effect=RuntimeError(raw_error)):
        r = client.post("/api/settings/test-key", json={
            "provider": "openai",
            "api_key": "sk-live-secret",
            "model": "gpt-4o",
        })

    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert "/Users/example" not in data["message"]
    assert "sk-live-secret" not in data["message"]
    assert "连接失败" in data["message"]


def test_test_key_strips_provider_before_dispatch():
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.translator.TranslationProvider") as provider_cls:
        provider_cls.return_value.test_connection.return_value = True
        r = client.post("/api/settings/test-key", json={
            "provider": " openai ",
            "api_key": "sk-test",
            "model": "gpt-4o",
        })

    assert r.status_code == 200
    provider_cls.assert_called_once_with("openai", "sk-test", "gpt-4o")


def test_tmdb_key_test_uses_submitted_key_and_language():
    from app.main import app
    client = TestClient(app)

    async def fake_test_connection(api_key=None, language=None):
        assert api_key == "tmdb-test-key"
        assert language == "en-US"
        return True

    with patch("app.engines.tmdb.test_connection", side_effect=fake_test_connection):
        r = client.post("/api/settings/test-tmdb-key", json={
            "api_key": " tmdb-test-key ",
            "language": " en-US ",
        })

    assert r.status_code == 200
    assert r.json() == {"success": True, "message": "连接成功"}


def test_tmdb_key_test_redacts_submitted_key_from_failure_message():
    from app.main import app
    client = TestClient(app)

    async def fake_test_connection(api_key=None, language=None):
        raise RuntimeError(f"api_key={api_key}&language=zh-CN failed")

    with patch("app.engines.tmdb.test_connection", side_effect=fake_test_connection):
        r = client.post("/api/settings/test-tmdb-key", json={
            "api_key": "tmdb-secret-token",
            "language": "zh-CN",
        })

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert "tmdb-secret-token" not in body["message"]
    assert "连接失败" in body["message"]


def test_tmdb_key_test_reports_blank_key_without_network_call():
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.tmdb.test_connection") as test_connection:
        r = client.post("/api/settings/test-tmdb-key", json={
            "api_key": " ",
            "language": "zh-CN",
        })

    assert r.status_code == 200
    assert r.json()["success"] is False
    assert "TMDB API 密钥" in r.json()["message"]
    test_connection.assert_not_called()


def test_update_settings_rejects_unknown_claude_cli_model():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/settings", json={
        "providers": {
            "claude_cli": {
                "model": "not-a-real-claude-model",
            }
        }
    })
    assert r.status_code == 400
    assert "Claude CLI model" in r.json()["detail"]


def test_update_settings_accepts_codex_cli_provider_config():
    from app.main import app
    client = TestClient(app)

    with patch("app.api.settings.Config.update", return_value=None) as update:
        r = client.post("/api/settings", json={
            "translation": {
                "primary_provider": "codex_cli",
                "polish_provider": " claude_cli ",
            },
            "providers": {
                "codex_cli": {
                    "enabled": True,
                    "model": " gpt-5.5 ",
                    "timeout_sec": 300,
                },
            },
        })

    assert r.status_code == 200
    payload = update.call_args.args[0]
    assert payload["translation"]["primary_provider"] == "codex_cli"
    assert payload["translation"]["polish_provider"] == "claude_cli"
    assert payload["providers"]["codex_cli"]["model"] == "gpt-5.5"


def test_update_settings_accepts_supported_display_language():
    from app.main import app
    client = TestClient(app)

    with patch("app.api.settings.Config.update", return_value=None) as update:
        r = client.post("/api/settings", json={
            "general": {
                "display_language": " en-US ",
            },
        })

    assert r.status_code == 200
    assert update.call_args.args[0]["general"]["display_language"] == "en-US"


def test_update_settings_rejects_unknown_display_language():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/settings", json={
        "general": {
            "display_language": "fr-FR",
        },
    })

    assert r.status_code == 400
    assert "display_language" in r.json()["detail"]


def test_update_settings_rejects_unknown_translation_provider():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/settings", json={
        "translation": {
            "primary_provider": "not-a-provider",
            "polish_provider": "openai",
        }
    })
    assert r.status_code == 400
    assert "primary_provider" in r.json()["detail"]

    r = client.post("/api/settings", json={
        "translation": {
            "primary_provider": "openai",
            "polish_provider": "not-a-provider",
        }
    })
    assert r.status_code == 400
    assert "polish_provider" in r.json()["detail"]


def test_update_settings_rejects_blank_primary_provider_but_allows_blank_polish_provider():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/settings", json={
        "translation": {
            "primary_provider": " ",
        }
    })
    assert r.status_code == 400
    assert "primary_provider" in r.json()["detail"]

    with patch("app.api.settings.Config.update", return_value=None) as update:
        r = client.post("/api/settings", json={
            "translation": {
                "polish_provider": "",
            }
        })
    assert r.status_code == 200
    update.assert_called_once()


def test_update_settings_rejects_non_string_translation_provider():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/settings", json={
        "translation": {
            "primary_provider": ["openai"],
        }
    })

    assert r.status_code == 400
    assert "primary_provider" in r.json()["detail"]


def test_update_settings_strips_translation_providers_before_persist():
    from app.main import app
    client = TestClient(app)

    with patch("app.api.settings.Config.update", return_value=None) as update:
        r = client.post("/api/settings", json={
            "translation": {
                "primary_provider": " openai ",
                "polish_provider": " claude_cli ",
            }
        })

    assert r.status_code == 200
    update.assert_called_once()
    payload = update.call_args.args[0]
    assert payload["translation"]["primary_provider"] == "openai"
    assert payload["translation"]["polish_provider"] == "claude_cli"


def test_translation_readiness_requires_configured_polish_api_provider():
    from app.api.settings import _translation_readiness

    payload = _translation_readiness({
        "translation": {
            "primary_provider": "openai",
            "polish_provider": "deepseek",
        },
        "api_keys": {
            "openai": "sk-openai",
        },
    })

    assert payload["translation_ready"] is False
    assert payload["api_key"] is False
    assert payload["translation_provider"] == "deepseek"
    assert "润色引擎" in payload["translation_hint"]
    assert "DeepSeek API 密钥" in payload["translation_hint"]


def test_translation_readiness_accepts_shared_primary_and_polish_provider_key():
    from app.api.settings import _translation_readiness

    payload = _translation_readiness({
        "translation": {
            "primary_provider": "openai",
            "polish_provider": "openai",
        },
        "api_keys": {
            "openai": "sk-openai",
        },
    })

    assert payload["translation_ready"] is True
    assert payload["api_key"] is True
    assert payload["translation_required_providers"] == ["openai"]


def test_translation_readiness_requires_configured_polish_claude_cli():
    from app.api.settings import _translation_readiness

    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available", return_value=False):
        payload = _translation_readiness({
            "translation": {
                "primary_provider": "openai",
                "polish_provider": "claude_cli",
            },
            "api_keys": {
                "openai": "sk-openai",
            },
        })

    assert payload["translation_ready"] is False
    assert payload["translation_provider"] == "claude_cli"
    assert "润色引擎" in payload["translation_hint"]
    assert "未检测到 claude 命令" in payload["translation_hint"]


def test_translation_readiness_requires_configured_polish_codex_cli():
    from app.api.settings import _translation_readiness

    with patch("app.engines.providers.codex_cli.CodexCliProvider.check_cli_available", return_value=False):
        payload = _translation_readiness({
            "translation": {
                "primary_provider": "openai",
                "polish_provider": "codex_cli",
            },
            "api_keys": {
                "openai": "sk-openai",
            },
        })

    assert payload["translation_ready"] is False
    assert payload["translation_provider"] == "codex_cli"
    assert "润色引擎" in payload["translation_hint"]
    assert "未检测到 codex 命令" in payload["translation_hint"]


def test_update_settings_rejects_non_object_sections():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/settings", json={"translation": None})
    assert r.status_code == 400
    assert "translation" in r.json()["detail"]

    r = client.post("/api/settings", json={"api_keys": []})
    assert r.status_code == 400
    assert "api_keys" in r.json()["detail"]


def test_update_settings_rejects_invalid_numeric_values(monkeypatch):
    from app.main import app
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.settings.Config.update",
        lambda data: (_ for _ in ()).throw(AssertionError("Config.update should not be called")),
    )

    cases = [
        ({"trailer": {"max_video_height": "1080"}}, "max_video_height"),
        ({"translation": {"batch_size": -1}}, "batch_size"),
        ({"concurrency": {"translate": 0}}, "translate"),
        ({"providers": {"claude_cli": {"timeout_sec": 0}}}, "timeout_sec"),
    ]

    for payload, field in cases:
        r = client.post("/api/settings", json=payload)
        assert r.status_code == 400
        assert field in r.json()["detail"]


def test_update_settings_rejects_non_finite_numbers(monkeypatch):
    from app.main import app
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.settings.Config.update",
        lambda data: (_ for _ in ()).throw(AssertionError("Config.update should not be called")),
    )

    r = client.post(
        "/api/settings",
        content='{"general":{"theme":NaN}}',
        headers={"content-type": "application/json"},
    )

    assert r.status_code == 400
    assert "general.theme" in r.json()["detail"]


def test_update_settings_rejects_invalid_boolean_values(monkeypatch):
    from app.main import app
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.settings.Config.update",
        lambda data: (_ for _ in ()).throw(AssertionError("Config.update should not be called")),
    )

    cases = [
        ({"translation": {"filter_repetitive": "false"}}, "filter_repetitive"),
        ({"translation": {"full_doc_mode": 1}}, "full_doc_mode"),
        ({"asr": {"use_demucs": "yes"}}, "use_demucs"),
        ({"providers": {"claude_cli": {"enabled": "true"}}}, "enabled"),
    ]

    for payload, field in cases:
        r = client.post("/api/settings", json=payload)
        assert r.status_code == 400
        assert field in r.json()["detail"]


def test_update_settings_rejects_invalid_string_values(monkeypatch):
    from app.main import app
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.settings.Config.update",
        lambda data: (_ for _ in ()).throw(AssertionError("Config.update should not be called")),
    )

    cases = [
        ({"api_keys": {"openai": 123}}, "api_keys.openai"),
        ({"tmdb": {"api_key": {"bad": "value"}}}, "tmdb.api_key"),
        ({"translation": {"primary_model": ["gpt-4o"]}}, "primary_model"),
        ({"asr": {"language": 7}}, "asr.language"),
    ]

    for payload, field in cases:
        r = client.post("/api/settings", json=payload)
        assert r.status_code == 400
        assert field in r.json()["detail"]


def test_update_settings_rejects_blank_required_string_values(monkeypatch):
    from app.main import app
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.settings.Config.update",
        lambda data: (_ for _ in ()).throw(AssertionError("Config.update should not be called")),
    )

    cases = [
        ({"tmdb": {"language": "  "}}, "tmdb.language"),
        ({"translation": {"primary_model": ""}}, "primary_model"),
        ({"translation": {"target_language": "  "}}, "target_language"),
        ({"asr": {"model_size": ""}}, "asr.model_size"),
        ({"asr": {"language": "  "}}, "asr.language"),
    ]

    for payload, field in cases:
        r = client.post("/api/settings", json=payload)
        assert r.status_code == 400
        assert field in r.json()["detail"]


def test_models_endpoint_returns_claude_cli_static_models_without_api_key():
    from app.main import app
    client = TestClient(app)

    r = client.get("/api/models/claude_cli")
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True
    assert body["models"] == [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]


def test_models_endpoint_returns_codex_cli_static_models_without_api_key():
    from app.main import app
    client = TestClient(app)

    r = client.get("/api/models/codex_cli")

    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True
    assert "gpt-5.5" in body["models"]
    assert "gpt-5.4" in body["models"]


def test_models_endpoint_treats_malformed_api_keys_as_missing():
    from app.main import app
    client = TestClient(app)

    with patch("app.api.settings.Config.to_dict", return_value={"api_keys": []}):
        r = client.get("/api/models/openai")

    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True
    assert "gpt-4o" in body["models"]


def test_models_endpoint_treats_malformed_provider_key_as_missing():
    from app.main import app
    client = TestClient(app)

    with patch("app.api.settings.Config.to_dict", return_value={"api_keys": {"openai": {"bad": "shape"}}}):
        r = client.get("/api/models/openai")

    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True
    assert "gpt-4o" in body["models"]


def test_models_endpoint_rejects_unknown_provider():
    from app.main import app
    client = TestClient(app)

    r = client.get("/api/models/not-a-provider")
    assert r.status_code == 400
    assert "provider" in r.json()["detail"]


def test_models_endpoint_rejects_blank_provider():
    from app.main import app
    client = TestClient(app)

    r = client.get("/api/models/%20%20")
    assert r.status_code == 400
    assert "provider" in r.json()["detail"]


def test_models_endpoint_uses_fallback_when_remote_models_are_all_filtered():
    from app.main import app
    client = TestClient(app)

    class FakeOpenAI:
        def __init__(self, **kwargs):
            pass

        class models:
            @staticmethod
            def list():
                return SimpleNamespace(data=[
                    SimpleNamespace(id="text-embedding-3-small"),
                    SimpleNamespace(id="whisper-1"),
                    SimpleNamespace(id="gpt-realtime"),
                ])

    with patch("app.api.settings.Config.to_dict", return_value={"api_keys": {"openai": "sk-test"}}), \
         patch("openai.OpenAI", FakeOpenAI):
        r = client.get("/api/models/openai")

    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True
    assert "gpt-4o" in body["models"]


def test_models_endpoint_redacts_remote_error_in_logs(caplog):
    import logging
    from app.main import app
    client = TestClient(app)
    query_value = "query-value-123"
    provider_secret = "sk-" + "live-secret-token"

    class FakeOpenAI:
        def __init__(self, **kwargs):
            pass

        class models:
            @staticmethod
            def list():
                raise RuntimeError(
                    f"GET https://api.test?api_key={query_value} failed with {provider_secret}"
                )

    caplog.set_level(logging.WARNING, logger="app.api.settings")
    with patch("app.api.settings.Config.to_dict", return_value={"api_keys": {"openai": "sk-test"}}), \
         patch("openai.OpenAI", FakeOpenAI):
        r = client.get("/api/models/openai")

    assert r.status_code == 200
    assert r.json()["fallback"] is True
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert query_value not in logs
    assert provider_secret not in logs
    assert "api_key=<redacted>" in logs
    assert "sk-<redacted>" in logs


def _system_check_config(primary_provider="openai", polish_provider="", api_keys=None):
    return {
        "api_keys": api_keys or {},
        "translation": {
            "primary_provider": primary_provider,
            "polish_provider": polish_provider,
        },
        "providers": {
            "claude_cli": {
                "enabled": True,
                "model": "claude-opus-4-7",
                "timeout_sec": 180,
            }
        },
    }


def test_system_check_requires_current_api_provider_key():
    """A key for a different provider must not make the selected engine look ready."""
    from app.main import app
    client = TestClient(app)

    with patch("app.utils.media.check_ffmpeg", return_value=True), \
         patch("app.api.settings.Config.to_dict", return_value=_system_check_config(
             primary_provider="openai",
             api_keys={"openai": "", "deepseek": "sk-deepseek"},
         )):
        r = client.get("/api/system-check")

    assert r.status_code == 200
    data = r.json()
    assert data["translation_provider"] == "openai"
    assert data["api_key"] is False
    assert data["translation_ready"] is False
    assert data["ready"] is False


def test_system_check_requires_configured_polish_provider_key():
    from app.main import app
    client = TestClient(app)

    with patch("app.utils.media.check_ffmpeg", return_value=True), \
         patch("app.api.settings.Config.to_dict", return_value=_system_check_config(
             primary_provider="openai",
             polish_provider="deepseek",
             api_keys={"openai": "sk-openai", "deepseek": ""},
         )):
        r = client.get("/api/system-check")

    assert r.status_code == 200
    data = r.json()
    assert data["translation_provider"] == "deepseek"
    assert data["translation_ready"] is False
    assert data["ready"] is False
    assert data["translation_required_providers"] == ["openai", "deepseek"]
    assert "润色引擎" in data["translation_hint"]
    assert "DeepSeek API 密钥" in data["translation_hint"]


def test_system_check_treats_malformed_provider_and_key_as_not_ready():
    from app.main import app
    client = TestClient(app)

    with patch("app.utils.media.check_ffmpeg", return_value=True), \
         patch("app.api.settings.Config.to_dict", return_value={
             "translation": {"primary_provider": ["openai"]},
             "api_keys": {"openai": {"bad": "shape"}},
         }):
        r = client.get("/api/system-check")

    assert r.status_code == 200
    data = r.json()
    assert data["translation_provider"] == "openai"
    assert data["translation_ready"] is False
    assert data["ready"] is False


def test_system_check_accepts_selected_api_provider_key():
    from app.main import app
    client = TestClient(app)

    with patch("app.utils.media.check_ffmpeg", return_value=True), \
         patch("app.api.settings.Config.to_dict", return_value=_system_check_config(
             primary_provider="deepseek",
             api_keys={"openai": "", "deepseek": "sk-deepseek"},
         )):
        r = client.get("/api/system-check")

    assert r.status_code == 200
    data = r.json()
    assert data["translation_provider"] == "deepseek"
    assert data["api_key"] is True
    assert data["translation_ready"] is True
    assert data["ready"] is True


def test_system_check_strips_configured_primary_provider():
    from app.main import app
    client = TestClient(app)

    with patch("app.utils.media.check_ffmpeg", return_value=True), \
         patch("app.api.settings.Config.to_dict", return_value=_system_check_config(
             primary_provider=" openai ",
             api_keys={"openai": "sk-test"},
         )):
        r = client.get("/api/system-check")

    assert r.status_code == 200
    data = r.json()
    assert data["translation_provider"] == "openai"
    assert data["translation_ready"] is True
    assert data["ready"] is True


def test_system_check_accepts_logged_in_claude_cli_without_api_key():
    from app.main import app
    client = TestClient(app)

    with patch("app.utils.media.check_ffmpeg", return_value=True), \
         patch("app.api.settings.Config.to_dict", return_value=_system_check_config(
             primary_provider="claude_cli",
             api_keys={"openai": "", "deepseek": "", "gemini": ""},
         )), \
         patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available", return_value=True), \
         patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_logged_in", return_value=True):
        r = client.get("/api/system-check")

    assert r.status_code == 200
    data = r.json()
    assert data["translation_provider"] == "claude_cli"
    assert data["api_key"] is True
    assert data["translation_ready"] is True
    assert data["claude_cli_installed"] is True
    assert data["claude_cli_logged_in"] is True
    assert data["ready"] is True


def test_system_check_accepts_logged_in_codex_cli_without_api_key():
    from app.main import app
    client = TestClient(app)

    with patch("app.utils.media.check_ffmpeg", return_value=True), \
         patch("app.api.settings.Config.to_dict", return_value=_system_check_config(
             primary_provider="codex_cli",
             api_keys={"openai": "", "deepseek": "", "gemini": ""},
         )), \
         patch("app.engines.providers.codex_cli.CodexCliProvider.check_cli_available", return_value=True), \
         patch("app.engines.providers.codex_cli.CodexCliProvider.check_logged_in", return_value=True):
        r = client.get("/api/system-check")

    assert r.status_code == 200
    data = r.json()
    assert data["translation_provider"] == "codex_cli"
    assert data["api_key"] is True
    assert data["translation_ready"] is True
    assert data["codex_cli_installed"] is True
    assert data["codex_cli_logged_in"] is True
    assert data["ready"] is True


def test_system_check_reports_configured_bundled_asr_model(monkeypatch, tmp_path):
    from app.main import app
    client = TestClient(app)

    model_root = tmp_path / "asr-models"
    bundled = model_root / "large-v3-turbo"
    bundled.mkdir(parents=True)
    monkeypatch.setenv("AISUBPRO_ASR_MODEL_DIR", str(model_root))

    with patch("app.utils.media.check_ffmpeg", return_value=True), \
         patch("app.api.settings.Config.to_dict", return_value={
             "asr": {"model_size": "large-v3-turbo"},
             "translation": {"primary_provider": "openai"},
             "api_keys": {"openai": "sk-test"},
         }):
        r = client.get("/api/system-check")

    assert r.status_code == 200
    data = r.json()
    assert data["whisper_model"] is True
    assert data["model_name"] == "large-v3-turbo"
    assert data["whisper_model_source"] == "bundled"
