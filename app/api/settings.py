"""
Settings and knowledge base API routes.
"""
import copy
import logging
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config import Config
from app.version import APP_VERSION
import app.engines.providers  # noqa: F401  (load provider modules before concurrent requests)
from app.engines.asr_capabilities import ASR_MODES, detect_asr_capabilities, recommend_asr_settings
from app.engines.knowledge import _get_singleton as _kb_singleton, invalidate_translator_kb

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["settings"])


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


_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "claude_cli": "Claude CLI",
    "codex_cli": "Codex CLI",
}

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

def _dict_section(cfg: dict, key: str) -> dict:
    value = cfg.get(key) if isinstance(cfg, dict) else None
    return value if isinstance(value, dict) else {}


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


def _provider_readiness(provider: str, *, role_label: str, cfg: dict) -> dict:
    label = _PROVIDER_LABELS.get(provider, provider)

    if provider == "claude_cli":
        from app.engines.providers.claude_cli import ClaudeCliProvider

        try:
            installed = ClaudeCliProvider.check_cli_available()
        except Exception:
            installed = False
        try:
            logged_in = ClaudeCliProvider.check_logged_in() if installed else False
        except Exception:
            logged_in = False

        ready = installed and logged_in
        if ready:
            hint = f"{role_label} Claude Code 已就绪"
        elif installed:
            hint = f"{role_label}请运行 claude 完成登录"
        else:
            hint = f"{role_label}未检测到 claude 命令"
        return {
            "translation_provider": provider,
            "translation_label": label,
            "translation_ready": ready,
            "translation_hint": hint,
            "claude_cli_installed": installed,
            "claude_cli_logged_in": logged_in,
            "codex_cli_installed": None,
            "codex_cli_logged_in": None,
        }

    if provider == "codex_cli":
        from app.engines.providers.codex_cli import CodexCliProvider

        try:
            installed = CodexCliProvider.check_cli_available()
        except Exception:
            installed = False
        try:
            logged_in = CodexCliProvider.check_logged_in() if installed else False
        except Exception:
            logged_in = False

        ready = installed and logged_in
        if ready:
            hint = f"{role_label}Codex CLI 已就绪"
        elif installed:
            hint = f"{role_label}请运行 codex login 完成登录"
        else:
            hint = f"{role_label}未检测到 codex 命令"
        return {
            "translation_provider": provider,
            "translation_label": label,
            "translation_ready": ready,
            "translation_hint": hint,
            "claude_cli_installed": None,
            "claude_cli_logged_in": None,
            "codex_cli_installed": installed,
            "codex_cli_logged_in": logged_in,
        }

    api_keys = _dict_section(cfg, "api_keys")
    api_key = api_keys.get(provider)
    has_key = bool(api_key) if isinstance(api_key, str) else False
    return {
        "translation_provider": provider,
        "translation_label": label,
        "translation_ready": has_key,
        "translation_hint": f"{role_label}已配置" if has_key else f"{role_label}请配置 {label} API 密钥",
        "claude_cli_installed": None,
        "claude_cli_logged_in": None,
        "codex_cli_installed": None,
        "codex_cli_logged_in": None,
    }


def _configured_translation_providers(translation: dict) -> list[tuple[str, str]]:
    raw_primary = translation.get("primary_provider")
    primary_value = raw_primary.strip() if isinstance(raw_primary, str) else ""
    primary = primary_value if primary_value in _PROVIDER_LABELS else "openai"

    raw_polish = translation.get("polish_provider")
    polish_value = raw_polish.strip() if isinstance(raw_polish, str) else ""
    polish = polish_value if polish_value in _PROVIDER_LABELS else ""

    providers = [("主翻译引擎：", primary)]
    if polish and polish != primary:
        providers.append(("润色引擎：", polish))
    return providers


def _translation_readiness(cfg: dict) -> dict:
    """Return readiness for all configured translation workflow providers."""
    translation = _dict_section(cfg, "translation")
    provider_checks = [
        _provider_readiness(provider, role_label=role_label, cfg=cfg)
        for role_label, provider in _configured_translation_providers(translation)
    ]
    blocking = [check for check in provider_checks if not check.get("translation_ready")]
    ready = not blocking

    primary_check = provider_checks[0] if provider_checks else _provider_readiness(
        "openai", role_label="主翻译引擎：", cfg=cfg
    )
    status_source = blocking[0] if blocking else primary_check
    hints = [check["translation_hint"] for check in blocking]
    if not hints:
        configured_labels = [check["translation_label"] for check in provider_checks]
        hint = "、".join(configured_labels) + " 已配置"
    else:
        hint = "；".join(hints)

    claude_checks = [check for check in provider_checks if check["translation_provider"] == "claude_cli"]
    claude_installed = claude_checks[0]["claude_cli_installed"] if claude_checks else None
    claude_logged_in = claude_checks[0]["claude_cli_logged_in"] if claude_checks else None
    codex_checks = [check for check in provider_checks if check["translation_provider"] == "codex_cli"]
    codex_installed = codex_checks[0]["codex_cli_installed"] if codex_checks else None
    codex_logged_in = codex_checks[0]["codex_cli_logged_in"] if codex_checks else None

    return {
        "translation_provider": status_source["translation_provider"],
        "translation_label": status_source["translation_label"],
        "translation_ready": ready,
        # Backward-compatible alias consumed by the existing home screen.
        "api_key": ready,
        "translation_hint": hint,
        "translation_required_providers": [
            check["translation_provider"] for check in provider_checks
        ],
        "claude_cli_installed": claude_installed,
        "claude_cli_logged_in": claude_logged_in,
        "codex_cli_installed": codex_installed,
        "codex_cli_logged_in": codex_logged_in,
    }


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
    settings = Config.to_dict()
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
        _require_int("translation", translation, "max_memory_examples", min_value=0, max_value=20)
        _require_int("translation", translation, "max_phrase_examples", min_value=0, max_value=20)
        _require_int("translation", translation, "repetitive_threshold", min_value=1, max_value=100)
        _require_int("translation", translation, "qa_auto_repair_rounds", min_value=0, max_value=2)
        _require_bool("translation", translation, "filter_repetitive")
        _require_bool("translation", translation, "filter_interjections")
        _require_bool("translation", translation, "full_doc_mode")

    asr = data.get("asr") if isinstance(data, dict) else None
    if isinstance(asr, dict):
        _require_non_blank_str("asr", asr, "mode")
        if "mode" in asr:
            asr["mode"] = asr["mode"].strip()
            if asr["mode"] not in ASR_MODES:
                allowed = ", ".join(ASR_MODES)
                raise HTTPException(status_code=400, detail=f"ASR mode must be one of: {allowed}")
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
        _require_bool(section, provider_cfg, "enabled")
        _require_int(section, provider_cfg, "timeout_sec", min_value=5, max_value=3600)
        if "model" not in provider_cfg:
            continue
        _require_non_blank_str(section, provider_cfg, "model")
        provider_cfg["model"] = provider_cfg["model"].strip()

    claude_cfg = providers.get("claude_cli")
    if isinstance(claude_cfg, dict) and "model" in claude_cfg:
        from app.engines.providers.claude_cli import ALLOWED_CLAUDE_CLI_MODELS

        model = claude_cfg.get("model")
        if model not in ALLOWED_CLAUDE_CLI_MODELS:
            allowed = ", ".join(sorted(ALLOWED_CLAUDE_CLI_MODELS))
            raise HTTPException(
                status_code=400,
                detail=f"Claude CLI model must be one of: {allowed}",
            )


@router.post("/settings")
def update_settings(data: dict):
    """Update configuration (partial update)."""
    payload = copy.deepcopy(data) if isinstance(data, dict) else data
    if isinstance(payload, dict):
        payload.pop("app_info", None)
    _validate_settings_update(payload)
    Config.update(payload)
    return {"status": "ok"}


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
        translation_provider = TranslationProvider(provider, req.api_key or "", req.model or "")
        success = translation_provider.test_connection()
        return {"success": success, "message": "连接成功" if success else "连接失败"}
    except Exception as e:
        log.warning("Provider key test failed provider=%s exc=%s", provider, type(e).__name__)
        log.debug("Provider key test failure detail", exc_info=e)
        return {"success": False, "message": _test_key_failure_message(provider)}


@router.post("/settings/test-tmdb-key")
async def test_tmdb_key(req: TestTmdbKeyRequest):
    """Test if a TMDB key can reach the TMDB API without saving it."""
    api_key = req.api_key.strip() if isinstance(req.api_key, str) else ""
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
        "whisper_model": has_model,
        "model_size": model_size,
        "model_name": model_name,
        "whisper_model_source": model_source.get("source", "unknown"),
        "asr_mode": asr_mode,
        "asr_capabilities": asr_capabilities,
        "asr_recommendation": asr_recommendation,
        **translation,
        "mlx_whisper": has_mlx,
        "mlx_error": mlx_error,
        "ready": has_ffmpeg and translation["translation_ready"],
    }


@router.get("/models/{provider}")
def list_models(provider: str):
    """Fetch available models from a provider using the configured API key."""
    from app.engines.providers.claude_cli import CLAUDE_CLI_MODELS
    from app.engines.providers.codex_cli import CODEX_CLI_MODELS
    from app.engines.translator import PROVIDER_URLS
    from openai import OpenAI

    # Static fallback model lists (kept up-to-date)
    fallback = {
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "o3-mini", "o4-mini"],
        "deepseek": ["deepseek-chat", "deepseek-reasoner"],
        "gemini": [
            "gemini-3.1-pro-preview", "gemini-3.1-flash-lite-preview",
            "gemini-3-pro-preview", "gemini-3-flash-preview",
            "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
            "gemini-2.0-flash", "gemini-2.0-flash-lite",
        ],
        "claude_cli": CLAUDE_CLI_MODELS,
        "codex_cli": CODEX_CLI_MODELS,
    }

    provider = _validate_provider_field("provider", provider, allow_empty=False)

    if provider in ("claude_cli", "codex_cli"):
        return {"models": fallback[provider], "fallback": True}

    cfg = Config.to_dict()
    api_key = _dict_section(cfg, "api_keys").get(provider, "")
    if not isinstance(api_key, str) or not api_key.strip():
        # No key — return fallback instead of error
        return {"models": fallback.get(provider, []), "fallback": True}
    api_key = api_key.strip()

    base_url = PROVIDER_URLS.get(provider, PROVIDER_URLS["openai"])

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=10)
        resp = client.models.list()
        models = []
        for m in resp.data:
            mid = getattr(m, "id", None)
            if not isinstance(mid, str) or not mid:
                continue
            # Strip "models/" prefix (Gemini returns this)
            if mid.startswith("models/"):
                mid = mid[7:]
            lower = mid.lower()
            # Filter out non-chat models
            skip_keywords = ["embed", "tts", "whisper", "dall-e", "moderation",
                             "babbage", "davinci", "search", "similarity",
                             "realtime", "audio", "transcri", "imagen",
                             "veo", "gemma", "aqa", "robotics", "nano",
                             "customtools", "computer-use", "-image",
                             "lyria", "deep-research"]
            if any(k in lower for k in skip_keywords):
                continue
            models.append(mid)
        models.sort()
        if not models:
            return {"models": fallback.get(provider, []), "fallback": True}
        return {"models": models}
    except Exception as e:
        from app.utils.errors import redact_error_message
        log.warning("Failed to fetch models for %s: %s", provider, redact_error_message(e))
        return {"models": fallback.get(provider, []), "fallback": True}


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
