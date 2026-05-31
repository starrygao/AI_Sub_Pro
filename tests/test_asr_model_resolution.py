def test_large_v3_turbo_uses_mlx_turbo_repo(monkeypatch, tmp_path):
    from app.engines import asr

    monkeypatch.setattr(asr, "_candidate_bundle_roots", lambda: [tmp_path / "missing"])

    source = asr.resolve_mlx_model_source("large-v3-turbo")

    assert source["path_or_repo"] == "mlx-community/whisper-large-v3-turbo"
    assert source["repo_id"] == "mlx-community/whisper-large-v3-turbo"


def test_blank_mlx_model_defaults_to_turbo(monkeypatch, tmp_path):
    from app.engines import asr

    monkeypatch.setattr(asr, "_candidate_bundle_roots", lambda: [tmp_path / "missing"])

    source = asr.resolve_mlx_model_source(" ")

    assert source["path_or_repo"] == "mlx-community/whisper-large-v3-turbo"


def test_bundled_mlx_model_directory_takes_precedence(monkeypatch, tmp_path):
    from app.engines import asr

    model_root = tmp_path / "models"
    bundled = model_root / "large-v3-turbo"
    bundled.mkdir(parents=True)
    monkeypatch.setenv("AISUBPRO_ASR_MODEL_DIR", str(model_root))

    source = asr.resolve_mlx_model_source("large-v3-turbo")

    assert source["source"] == "bundled"
    assert source["available"] is True
    assert source["path_or_repo"] == str(bundled)


def test_bundled_mlx_model_repo_slug_layout_is_supported(monkeypatch, tmp_path):
    from app.engines import asr

    model_root = tmp_path / "models"
    bundled = model_root / "mlx-community--whisper-large-v3-turbo"
    bundled.mkdir(parents=True)
    monkeypatch.setenv("AISUBPRO_ASR_MODEL_DIR", str(model_root))

    source = asr.resolve_mlx_model_source("large-v3-turbo")

    assert source["source"] == "bundled"
    assert source["path_or_repo"] == str(bundled)
