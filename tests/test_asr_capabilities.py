def test_detect_asr_capabilities_prefers_apple_silicon_mlx(monkeypatch, tmp_path):
    from app.engines import asr_capabilities

    monkeypatch.setattr(asr_capabilities.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(asr_capabilities.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        asr_capabilities.importlib.util,
        "find_spec",
        lambda name: object() if name == "mlx_whisper" else None,
    )
    monkeypatch.setattr(
        asr_capabilities,
        "resolve_mlx_model_source",
        lambda model: {
            "source": "bundled",
            "available": True,
            "path": str(tmp_path / model),
            "path_or_repo": str(tmp_path / model),
        },
    )

    caps = asr_capabilities.detect_asr_capabilities({"model_size": "large-v3-turbo"})

    assert caps["platform"]["system"] == "Darwin"
    assert caps["backends"]["mlx_whisper"]["installed"] is True
    assert caps["backends"]["mlx_whisper"]["accelerated"] is True
    assert caps["models"]["large-v3-turbo"]["available"] is True
    assert caps["models"]["large-v3-turbo"]["availability_scope"] == "mlx_whisper"
    assert caps["models"]["large-v3-turbo"]["mlx_whisper"]["available"] is True


def test_recommend_asr_settings_maps_speed_accuracy_and_offline(monkeypatch):
    from app.engines.asr_capabilities import recommend_asr_settings

    caps = {
        "platform": {"system": "Darwin", "machine": "arm64"},
        "backends": {
            "mlx_whisper": {
                "installed": True,
                "accelerated": True,
                "supports_vad": False,
                "supports_beam": False,
            },
            "faster_whisper": {
                "installed": True,
                "accelerated": False,
                "supports_vad": True,
                "supports_beam": True,
            },
            "openai_whisper": {
                "installed": False,
                "accelerated": False,
                "supports_vad": False,
                "supports_beam": True,
            },
        },
        "models": {
            "small": {"available": True, "download_hint": "~900MB", "source": "cache"},
            "large-v3": {"available": False, "download_hint": "~3GB", "source": "download"},
            "large-v3-turbo": {"available": True, "download_hint": "~1.6GB", "source": "bundled"},
        },
    }

    speed = recommend_asr_settings("speed", caps)
    accuracy = recommend_asr_settings("accuracy", caps)
    offline = recommend_asr_settings("offline", caps)

    assert speed["mode"] == "speed"
    assert speed["backend"] == "mlx_whisper"
    assert speed["model_size"] == "large-v3-turbo"
    assert accuracy["backend"] == "faster_whisper"
    assert accuracy["model_size"] == "large-v3"
    assert accuracy["download_required"] is True
    assert offline["download_required"] is False
    assert offline["model_size"] in {"small", "large-v3-turbo"}


def test_faster_whisper_recommendation_does_not_reuse_mlx_model_availability():
    from app.engines.asr_capabilities import recommend_asr_settings

    caps = {
        "platform": {"system": "Darwin", "machine": "arm64"},
        "backends": {
            "mlx_whisper": {
                "installed": False,
                "accelerated": True,
                "supports_vad": False,
                "supports_beam": False,
            },
            "faster_whisper": {
                "installed": True,
                "accelerated": False,
                "supports_vad": True,
                "supports_beam": True,
            },
            "openai_whisper": {
                "installed": False,
                "accelerated": False,
                "supports_vad": False,
                "supports_beam": True,
            },
        },
        "models": {
            "large-v3": {
                "model_size": "large-v3",
                "download_hint": "~3GB",
                "availability_scope": "mlx_whisper",
                "available": True,
                "source": "bundled",
                "path": "/tmp/mlx/large-v3",
                "mlx_whisper": {
                    "available": True,
                    "source": "bundled",
                    "path": "/tmp/mlx/large-v3",
                    "download_hint": "~3GB",
                },
                "faster_whisper": {
                    "available": False,
                    "source": "unknown",
                    "path": "",
                    "download_hint": "~3GB",
                },
            }
        },
    }

    rec = recommend_asr_settings("accuracy", caps)

    assert rec["backend"] == "faster_whisper"
    assert rec["model_size"] == "large-v3"
    assert rec["download_required"] is True
    assert rec["model_source"] == "unknown"


def test_recommendation_degrades_when_no_backend_is_installed():
    from app.engines.asr_capabilities import recommend_asr_settings

    caps = {
        "platform": {"system": "Linux", "machine": "x86_64"},
        "backends": {
            "mlx_whisper": {
                "installed": False,
                "accelerated": False,
                "supports_vad": False,
                "supports_beam": False,
            },
            "faster_whisper": {
                "installed": False,
                "accelerated": False,
                "supports_vad": True,
                "supports_beam": True,
            },
            "openai_whisper": {
                "installed": False,
                "accelerated": False,
                "supports_vad": False,
                "supports_beam": True,
            },
        },
        "models": {},
    }

    rec = recommend_asr_settings("offline", caps)

    assert rec["backend"] == ""
    assert rec["ready"] is False
    assert "安装" in rec["reason"]
