from app.services.provider_readiness import (
    _PROVIDER_LABELS,
    _configured_translation_providers,
    _dict_section,
    _provider_readiness,
    _translation_readiness,
)
"""
Settings and knowledge base API routes.
"""
import copy
import json
import logging
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config import Config
from app.version import APP_VERSION
from app.engines.model_catalog import CATALOG, model_ids, catalog_response
import app.engines.providers  # noqa: F401  (load provider modules before concurrent requests)
from app.engines.asr_capabilities import ASR_BACKENDS, ASR_MODES, detect_asr_capabilities, recommend_asr_settings
from app.engines.knowledge import _get_singleton as _kb_singleton, invalidate_translator_kb

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["settings"])

_ASR_BACKEND_LABELS = {
    "mlx_whisper": "MLX Whisper",
    "faster_whisper": "faster-whisper",
    "openai_whisper": "openai-whisper",
}


class TestKeyRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None


class TestTmdbKeyRequest(BaseModel):
    api_key: Optional[str] = None
    language: Optional[str] = None


def _test_key_failure_message(provider: str) -> str:
    if provider == "claude_cli":
        return "Claude CLI 检测失败，请确认已安装、已登录且模型名称有效"
    if provider == "codex_cli":
        return "Codex CLI 检测失败，请确认已安装、已登录且模型名称有效"
    return "连接失败，请检查 API 密钥、模型或网络设置"



_OBJECT_CONFIG_SECTIONS = {
    "api_keys",
    "tmdb",
    "trailer",
    "asr",
    "translation",
    "providers",
    "concurrency",
    "general",
}



def _asr_backend_installed(caps: dict, backend: str) -> bool:
    backends = caps.get("backends") if isinstance(caps, dict) else None
    info = backends.get(backend) if isinstance(backends, dict) else None
    return bool(isinstance(info, dict) and info.get("installed"))


def _asr_install_prompts(caps: dict, recommendation: dict) -> list[dict]:
    if not isinstance(caps, dict):
        return []
    backends = caps.get("backends") if isinstance(caps.get("backends"), dict) else {}
    selected_backend = caps.get("selected_backend") if isinstance(caps.get("selected_backend"), str) else "auto"
    selected_backend = selected_backend.strip()
    installed = [
        backend
        for backend in ASR_BACKENDS
        if backend != "auto" and _asr_backend_installed(caps, backend)
    ]

    missing_backend = ""
    if selected_backend in ASR_BACKENDS and selected_backend != "auto":
        if not _asr_backend_installed(caps, selected_backend):
            missing_backend = selected_backend
    elif not installed and backends:
        missing_backend = "local_asr_backend"

    if not missing_backend:
        return []

    if missing_backend == "local_asr_backend":
        title = "未检测到本地 ASR 后端"
        message = "未检测到本地 ASR 后端。请安装 requirements-asr.txt 中的 ASR 依赖。"
        backend = ""
        severity = "error"
    else:
        label = _ASR_BACKEND_LABELS.get(missing_backend, missing_backend)
        title = f"{label} 未安装"
        message = f"已选择 {missing_backend} 后端，但本机未检测到该依赖。请安装 ASR 依赖或切回自动。"
        backend = missing_backend
        severity = "warning"

    if isinstance(recommendation, dict):
        reason = recommendation.get("reason")
        if isinstance(reason, str) and reason.strip():
            message = reason.strip()

    return [{
        "id": f"asr-backend-{missing_backend}-missing",
        "severity": severity,
        "backend": backend,
        "title": title,
        "message": message,
        "install_command": "python3 -m pip install -r requirements-asr.txt",
    }]


def _validate_provider_field(field: str, provider: Optional[str], *, allow_empty: bool = True) -> Optional[str]:
    if provider is None:
        if allow_empty:
            return None
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {field} must not be empty",
        )
    if not isinstance(provider, str):
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {field} must be a string",
        )
    provider = provider.strip()
    if not provider:
        if allow_empty:
            return ""
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {field} must not be empty",
        )
    if provider not in _PROVIDER_LABELS:
        allowed = ", ".join(_PROVIDER_LABELS)
        raise HTTPException(
            status_code=400,
            detail=f"Unknown translation {field}: {provider}. Allowed: {allowed}",
        )
    return provider


def _require_int(
    section_name: str,
    section: dict,
    field: str,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> None:
    if field not in section:
        return
    value = section[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {section_name}.{field} must be an integer",
        )
    if min_value is not None and value < min_value:
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {section_name}.{field} must be >= {min_value}",
        )
    if max_value is not None and value > max_value:
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {section_name}.{field} must be <= {max_value}",
        )


def _require_bool(section_name: str, section: dict, field: str) -> None:
    if field not in section:
        return
    if not isinstance(section[field], bool):
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {section_name}.{field} must be a boolean",
        )


def _require_str(section_name: str, section: dict, field: str) -> None:
    if field not in section:
        return
    if not isinstance(section[field], str):
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {section_name}.{field} must be a string",
        )


def _require_non_blank_str(section_name: str, section: dict, field: str) -> None:
    _require_str(section_name, section, field)
    if field in section and not section[field].strip():
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {section_name}.{field} must not be empty",
        )


def _validate_choice_field(
    section_name: str,
    section: dict,
    field: str,
    *,
    allowed: set[str],
) -> None:
    if field not in section:
        return
    _require_non_blank_str(section_name, section, field)
    normalized = section[field].strip().lower()
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {section_name}.{field} must be one of: {allowed_text}",
        )
    section[field] = normalized


def _reject_non_finite_numbers(value, path: str = "settings") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise HTTPException(
            status_code=400,
            detail=f"Settings value {path} must be finite",
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite_numbers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_finite_numbers(item, f"{path}[{index}]")








def current_translation_readiness() -> dict:
    """Return readiness for the current persisted translation configuration."""
    return _translation_readiness(Config.to_dict())


def require_translation_ready() -> dict:
    """Raise a client-facing error when translation-dependent workflows cannot run."""
    readiness = current_translation_readiness()
    if not readiness.get("translation_ready"):
        raise HTTPException(
            status_code=400,
            detail=readiness.get("translation_hint") or "请先配置翻译服务",
        )
    return readiness


@router.get("/settings")
def get_settings():
    """Get current configuration."""
    settings = Config.public_dict()
    settings["app_info"] = {
        "name": "AI Sub Pro",
        "version": APP_VERSION,
    }
    return settings


def _validate_settings_update(data: dict) -> None:
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Settings update must be an object")
    _reject_non_finite_numbers(data)

    for section in _OBJECT_CONFIG_SECTIONS:
        if section in data and not isinstance(data[section], dict):
            raise HTTPException(
                status_code=400,
                detail=f"Settings section {section} must be an object",
            )

    api_keys = data.get("api_keys") if isinstance(data, dict) else None
    if isinstance(api_keys, dict):
        for field in api_keys:
            _require_str("api_keys", api_keys, field)

    tmdb = data.get("tmdb") if isinstance(data, dict) else None
    if isinstance(tmdb, dict):
        _require_str("tmdb", tmdb, "api_key")
        _require_non_blank_str("tmdb", tmdb, "language")

    translation = data.get("translation") if isinstance(data, dict) else None
    if isinstance(translation, dict):
        if "primary_provider" in translation:
            translation["primary_provider"] = _validate_provider_field(
                "primary_provider", translation.get("primary_provider"), allow_empty=False
            )
        if "polish_provider" in translation:
            translation["polish_provider"] = _validate_provider_field(
                "polish_provider", translation.get("polish_provider")
            )
        _require_non_blank_str("translation", translation, "primary_model")
        _require_str("translation", translation, "polish_model")
        _validate_choice_field(
            "translation",
            translation,
            "primary_effort",
            allowed={"auto", "low", "medium", "high", "xhigh", "max", "ultra"},
        )
        _validate_choice_field(
            "translation",
            translation,
            "polish_effort",
            allowed={"auto", "low", "medium", "high", "xhigh", "max", "ultra"},
        )
        _require_non_blank_str("translation", translation, "target_language")
        _require_int("translation", translation, "batch_size", min_value=0, max_value=200)
        _require_int("translation", translation, "context_window", min_value=0, max_value=50)
        _validate_choice_field(
            "translation",
            translation,
            "memory_retrieval_backend",
            allowed={"auto", "fts5", "ngram"},
        )
        _validate_choice_field(
            "translation",
            translation,
            "phrase_retrieval_backend",
            allowed={"auto", "fts5", "ngram"},
        )
        _validate_choice_field(
            "translation",
            translation,
            "quality_mode",
            allowed={"fast", "professional"},
        )
        _require_int("translation", translation, "max_memory_examples", min_value=0, max_value=20)
        _require_int("translation", translation, "max_phrase_examples", min_value=0, max_value=20)
        _require_int("translation", translation, "repetitive_threshold", min_value=1, max_value=100)
        _require_int("translation", translation, "missing_translation_retries", min_value=0, max_value=4)
        _require_int("translation", translation, "missing_translation_retry_batch_size", min_value=1, max_value=20)
        _require_int("translation", translation, "missing_translation_retry_max_blocks", min_value=0, max_value=5000)
        _require_int("translation", translation, "missing_translation_abort_min_blocks", min_value=0, max_value=5000)
        _require_int("translation", translation, "missing_translation_abort_missing_pct", min_value=0, max_value=100)
        _require_int("translation", translation, "qa_auto_repair_rounds", min_value=0, max_value=4)
        _require_int("translation", translation, "semantic_qa_batch_size", min_value=5, max_value=80)
        _require_int("translation", translation, "semantic_qa_max_blocks", min_value=0, max_value=5000)
        _require_bool("translation", translation, "filter_repetitive")
        _require_bool("translation", translation, "filter_interjections")
        _require_bool("translation", translation, "full_doc_mode")
        _require_bool("translation", translation, "use_translation_memory")
        _require_bool("translation", translation, "use_phrase_library")
        _require_bool("translation", translation, "require_kb_suggestion_review")
        _require_bool("translation", translation, "qa_auto_repair")
        _require_bool("translation", translation, "semantic_qa")

    asr = data.get("asr") if isinstance(data, dict) else None
    if isinstance(asr, dict):
        _require_non_blank_str("asr", asr, "mode")
        if "mode" in asr:
            asr["mode"] = asr["mode"].strip()
            if asr["mode"] not in ASR_MODES:
                allowed = ", ".join(ASR_MODES)
                raise HTTPException(status_code=400, detail=f"ASR mode must be one of: {allowed}")
        _validate_choice_field("asr", asr, "backend", allowed=set(ASR_BACKENDS))
        _require_non_blank_str("asr", asr, "model_size")
        _require_non_blank_str("asr", asr, "language")
        _require_int("asr", asr, "beam_size", min_value=1, max_value=20)
        _require_int("asr", asr, "offset_ms")
        _require_bool("asr", asr, "vad_filter")
        _require_bool("asr", asr, "use_demucs")

    trailer = data.get("trailer") if isinstance(data, dict) else None
    if isinstance(trailer, dict):
        _require_int("trailer", trailer, "max_video_height", min_value=0, max_value=4320)

    concurrency = data.get("concurrency") if isinstance(data, dict) else None
    if isinstance(concurrency, dict):
        for field in ("asr", "translate", "download", "burn"):
            _require_int("concurrency", concurrency, field, min_value=1, max_value=16)

    general = data.get("general") if isinstance(data, dict) else None
    if isinstance(general, dict):
        _require_int("general", general, "max_workers", min_value=1, max_value=16)

    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        return

    for provider_name in ("claude_cli", "codex_cli"):
        provider_cfg = providers.get(provider_name)
        if provider_name in providers and not isinstance(provider_cfg, dict):
            raise HTTPException(status_code=400, detail=f"Settings section providers.{provider_name} must be an object")
        if not isinstance(provider_cfg, dict):
            continue
        section = f"providers.{provider_name}"
        provider_cfg.pop("model", None)
        _require_bool(section, provider_cfg, "enabled")
        _require_int(section, provider_cfg, "timeout_sec", min_value=5, max_value=3600)


@router.post("/settings")
def update_settings(data: dict):
    """Update configuration (partial update)."""
    payload = copy.deepcopy(data) if isinstance(data, dict) else data
    if isinstance(payload, dict):
        for field in ("app_info", "credentials_configured", "_credential_refs"):
            payload.pop(field, None)
        clear = payload.pop("clear_credentials", [])
        if not isinstance(clear, list) or any(k not in {"openai", "deepseek", "gemini", "tmdb"} for k in clear):
            raise HTTPException(status_code=400, detail="Invalid credential removal list")
        # Blank fields represent an unchanged secret. Deletion is explicit.
        for section, key in [("api_keys", p) for p in ("openai", "deepseek", "gemini")] + [("tmdb", "api_key")]:
            fields = payload.get(section)
            name = key if section == "api_keys" else "tmdb"
            if isinstance(fields, dict) and fields.get(key) == "" and name not in clear:
                fields.pop(key, None)
        for name in clear:
            section, key = ("tmdb", "api_key") if name == "tmdb" else ("api_keys", name)
            payload.setdefault(section, {})[key] = ""
    _validate_settings_update(payload)
    from app.credentials import CredentialError
    try:
        Config.update(payload)
    except CredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"status": "ok", "credentials_configured": Config.public_dict()["credentials_configured"]}


@router.post("/settings/test-key")
def test_api_key(req: TestKeyRequest):
    """Test if an API key / provider is usable."""
    provider = _validate_provider_field("provider", req.provider, allow_empty=False)
    try:
        if provider == "claude_cli":
            from app.engines.providers.claude_cli import ClaudeCliProvider
            p = ClaudeCliProvider({"model": req.model or "claude-opus-4-7", "timeout_sec": 15})
            ok = p.test_connection()
            return {
                "success": ok,
                "message": "OK" if ok else "Claude CLI 未安装或未登录 (CLI not installed or not logged in)",
            }
        if provider == "codex_cli":
            from app.engines.providers.codex_cli import CodexCliProvider
            p = CodexCliProvider({"model": req.model or "gpt-5.5", "timeout_sec": 15})
            ok = p.test_connection()
            return {
                "success": ok,
                "message": "OK" if ok else "Codex CLI 未安装或未登录 (CLI not installed or not logged in)",
            }
        from app.engines.translator import TranslationProvider
        translation_provider = TranslationProvider(provider, req.api_key or Config.get("api_keys", provider, default=""), req.model or "")
        success = translation_provider.test_connection()
        return {"success": success, "message": "连接成功" if success else "连接失败"}
    except Exception as e:
        log.warning("Provider key test failed provider=%s exc=%s", provider, type(e).__name__)
        # SDK exceptions can embed user credentials; keep logs to exception type.
        return {"success": False, "message": _test_key_failure_message(provider)}


@router.post("/settings/test-tmdb-key")
async def test_tmdb_key(req: TestTmdbKeyRequest):
    """Test if a TMDB key can reach the TMDB API without saving it."""
    api_key = (req.api_key or Config.get("tmdb", "api_key", default="")).strip()
    if not api_key:
        return {"success": False, "message": "请先填写 TMDB API 密钥"}
    language = req.language.strip() if isinstance(req.language, str) and req.language.strip() else "zh-CN"

    from app.engines import tmdb

    try:
        ok = await tmdb.test_connection(api_key=api_key, language=language)
        return {"success": bool(ok), "message": "连接成功" if ok else "连接失败"}
    except Exception as e:
        from app.utils.errors import redact_error_message

        safe_detail = tmdb.public_error_message(e)
        safe_detail = redact_error_message(safe_detail).replace(api_key, "<redacted>")
        log.warning("TMDB key test failed: %s", safe_detail)
        return {"success": False, "message": "连接失败，请检查 TMDB API 密钥或网络设置"}


@router.get("/settings/claude-cli/status")
def claude_cli_status():
    """Report whether Claude Code CLI is installed and logged in."""
    from app.engines.providers.claude_cli import ClaudeCliProvider
    try:
        installed = ClaudeCliProvider.check_cli_available()
    except Exception as e:
        log.warning("Claude CLI availability check failed: %s", e)
        installed = False
    try:
        logged_in = ClaudeCliProvider.check_logged_in() if installed else False
    except Exception as e:
        log.warning("Claude CLI login check failed: %s", e)
        logged_in = False
    return {
        "installed": installed,
        "logged_in": logged_in,
    }


@router.get("/settings/codex-cli/status")
def codex_cli_status():
    """Report whether Codex CLI is installed and logged in."""
    from app.engines.providers.codex_cli import CodexCliProvider
    try:
        installed = CodexCliProvider.check_cli_available()
    except Exception as e:
        log.warning("Codex CLI availability check failed: %s", e)
        installed = False
    try:
        logged_in = CodexCliProvider.check_logged_in() if installed else False
    except Exception as e:
        log.warning("Codex CLI login check failed: %s", e)
        logged_in = False
    return {
        "installed": installed,
        "logged_in": logged_in,
    }


def _network_downloader_status() -> dict:
    try:
        import importlib.metadata as importlib_metadata
        import yt_dlp
    except Exception as e:
        return {
            "network_downloader_ready": False,
            "network_downloader_version": "",
            "network_downloader_hint": f"未检测到 yt-dlp：{str(e)[:160]}。请安装 yt-dlp 以启用网络视频下载。",
        }

    version = getattr(yt_dlp.version, "__version__", "")
    if not version:
        try:
            version = importlib_metadata.version("yt-dlp")
        except Exception:
            version = ""
    return {
        "network_downloader_ready": True,
        "network_downloader_version": version,
        "network_downloader_hint": "yt-dlp 可用，网络视频可直接下载到项目文件夹。",
    }


@router.get("/system-check")
def system_check():
    """Check system readiness for other Macs."""
    import shutil
    import pathlib
    from app.utils.media import check_ffmpeg

    # Check ffmpeg
    has_ffmpeg = check_ffmpeg()

    # Check configured MLX Whisper model. This may be a bundled model inside
    # the .app, a user-provided local path, or the Hugging Face cache.
    cfg = Config.to_dict()
    raw_asr = cfg.get("asr", {})
    asr_cfg = raw_asr if isinstance(raw_asr, dict) else {}
    asr_mode = asr_cfg.get("mode") if isinstance(asr_cfg.get("mode"), str) else "speed"
    if asr_mode not in ASR_MODES:
        asr_mode = "speed"
    asr_capabilities = detect_asr_capabilities(asr_cfg)
    asr_recommendation = recommend_asr_settings(asr_mode, asr_capabilities)
    model_name = asr_cfg.get("model_size") if isinstance(asr_cfg.get("model_size"), str) else "large-v3-turbo"
    from app.engines.asr import resolve_mlx_model_source
    model_source = resolve_mlx_model_source(model_name)
    cache_dir = pathlib.Path(model_source.get("path", ""))
    has_model = bool(model_source.get("available"))
    model_size = ""
    if has_model:
        import subprocess
        try:
            result = subprocess.check_output(["du", "-sh", str(cache_dir)]).decode().split()[0]
            model_size = result
        except Exception:
            model_size = "unknown"

    # Check selected translation provider readiness. For API providers this
    # means the selected provider has a key; for local CLI providers it means
    # the CLI exists and is logged in.
    translation = current_translation_readiness()

    # Check mlx_whisper
    has_mlx = False
    mlx_error = ""
    try:
        import mlx_whisper
        has_mlx = True
    except Exception as e:
        mlx_error = str(e)[:200]

    return {
        "ffmpeg": has_ffmpeg,
        **_network_downloader_status(),
        "whisper_model": has_model,
        "model_size": model_size,
        "model_name": model_name,
        "whisper_model_source": model_source.get("source", "unknown"),
        "asr_mode": asr_mode,
        "asr_capabilities": asr_capabilities,
        "asr_recommendation": asr_recommendation,
        "asr_model_options": asr_capabilities.get("model_options", []),
        "asr_install_prompts": _asr_install_prompts(asr_capabilities, asr_recommendation),
        **translation,
        "mlx_whisper": has_mlx,
        "mlx_error": mlx_error,
        "ready": has_ffmpeg and translation["translation_ready"],
    }


@router.get("/model-catalog.js")
def model_catalog_script():
    """Bootstrap the UI from the same capability catalog used by providers."""
    from fastapi.responses import Response
    return Response("globalThis.AISUBPRO_MODEL_CATALOG = " + json.dumps(CATALOG) + ";",
                    media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/models/{provider}")
def list_models(provider: str):
    """Fetch available models from a provider using the configured API key."""
    from app.engines.translator import PROVIDER_URLS
    from openai import OpenAI

    provider = _validate_provider_field("provider", provider, allow_empty=False)

    if provider in ("claude_cli", "codex_cli"):
        return catalog_response(provider, model_ids(provider), "static", "cli")

    cfg = Config.to_dict()
    api_key = _dict_section(cfg, "api_keys").get(provider, "")
    if not isinstance(api_key, str) or not api_key.strip():
        # No key — return fallback instead of error
        return catalog_response(provider, model_ids(provider), "fallback", "missing_key")
    api_key = api_key.strip()

    base_url = PROVIDER_URLS.get(provider, PROVIDER_URLS["openai"])

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=10)
        resp = client.models.list()
        models = []
        for m in resp.data:
            mid = getattr(m, "id", None)
            if not isinstance(mid, str) or not mid.strip():
                continue
            mid = mid.strip()
            # Strip "models/" prefix (Gemini returns this)
            if mid.startswith("models/"):
                mid = mid[7:]
            lower = mid.lower()
            # Filter out non-chat models
            skip_keywords = ["embed", "tts", "whisper", "dall-e", "moderation",
                             "babbage", "davinci", "search", "similarity",
                             "realtime", "audio", "transcri", "imagen",
                             "veo", "gemma", "aqa", "robotics", "-live", "omni", "sora",
                             "customtools", "computer-use", "-image",
                             "lyria", "deep-research"]
            if any(k in lower for k in skip_keywords):
                continue
            models.append(mid)
        models = sorted(set(models))
        if not models:
            return catalog_response(provider, model_ids(provider), "fallback", "empty")
        return catalog_response(provider, models, "remote")
    except Exception as e:
        from app.utils.errors import redact_error_message
        log.warning("Failed to fetch models for %s: %s", provider, redact_error_message(e))
        return catalog_response(provider, model_ids(provider), "fallback", "unreachable")


@router.get("/knowledge")
def get_knowledge():
    """Get knowledge base."""
    return _kb_singleton().get_all()


@router.post("/knowledge")
def update_knowledge(data: dict):
    """Update knowledge base."""
    _kb_singleton().update_all(data)
    # Invalidate translator's shared KB so next translation sees the update
    invalidate_translator_kb()
    return {"status": "ok"}
