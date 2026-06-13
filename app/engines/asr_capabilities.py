"""ASR capability detection and intent-level recommendations."""
from __future__ import annotations

import importlib.util
import platform
from typing import Any

from app.engines.asr import ASR_BACKENDS, MODEL_DOWNLOAD_HINTS, resolve_mlx_model_source

ASR_MODES = ("speed", "accuracy", "offline")
BACKEND_ORDER = tuple(backend for backend in ASR_BACKENDS if backend != "auto")
MODEL_ORDER = ("tiny", "base", "small", "medium", "large-v3-turbo", "large-v3")
OFFLINE_MODEL_ORDER = ("large-v3-turbo", "small", "base", "tiny", "medium", "large-v3")
MODEL_LABELS = {
    "tiny": "tiny (最快)",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large-v3-turbo": "large-v3-turbo (推荐)",
    "large-v3": "large-v3 (最准)",
}


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _backend(
    installed: bool,
    *,
    accelerated: bool,
    supports_vad: bool,
    supports_beam: bool,
) -> dict[str, Any]:
    return {
        "installed": bool(installed),
        "accelerated": bool(accelerated),
        "supports_vad": bool(supports_vad),
        "supports_beam": bool(supports_beam),
    }


def _unknown_model_info(model: str) -> dict[str, Any]:
    return {
        "available": False,
        "source": "unknown",
        "path": "",
        "path_or_repo": "",
        "download_hint": MODEL_DOWNLOAD_HINTS.get(model, ""),
    }


def _model_info(model: str) -> dict[str, Any]:
    source = resolve_mlx_model_source(model)
    mlx_info = {
        "available": bool(source.get("available")),
        "source": source.get("source", "unknown"),
        "path": source.get("path", ""),
        "path_or_repo": source.get("path_or_repo", ""),
        "download_hint": MODEL_DOWNLOAD_HINTS.get(model, ""),
    }
    return {
        "model_size": model,
        "download_hint": MODEL_DOWNLOAD_HINTS.get(model, ""),
        "mlx_whisper": mlx_info,
        "faster_whisper": _unknown_model_info(model),
        "openai_whisper": _unknown_model_info(model),
        # Backward-compatible aliases are MLX-scoped. Recommendation code must
        # use the backend-specific entries above instead of these fields.
        "availability_scope": "mlx_whisper",
        "available": mlx_info["available"],
        "source": mlx_info["source"],
        "path": mlx_info["path"],
        "path_or_repo": mlx_info["path_or_repo"],
    }


def _model_option(model: str) -> dict[str, Any]:
    return {
        "model_size": model,
        "label": MODEL_LABELS.get(model, model),
        "download_hint": MODEL_DOWNLOAD_HINTS.get(model, ""),
    }


def asr_model_options(selected_model: str = "") -> list[dict[str, Any]]:
    models = list(MODEL_ORDER)
    if isinstance(selected_model, str):
        selected_model = selected_model.strip()
        if selected_model and selected_model not in models:
            models.append(selected_model)
    return [_model_option(model) for model in models]


def detect_asr_capabilities(asr_cfg: dict | None = None) -> dict[str, Any]:
    cfg = asr_cfg if isinstance(asr_cfg, dict) else {}
    system = platform.system()
    machine = platform.machine()
    apple_silicon = system == "Darwin" and machine in {"arm64", "aarch64"}
    selected_model = cfg.get("model_size") if isinstance(cfg.get("model_size"), str) else ""
    selected_backend = cfg.get("backend") if isinstance(cfg.get("backend"), str) else "auto"
    selected_backend = selected_backend.strip()
    if selected_backend not in ASR_BACKENDS:
        selected_backend = "auto"

    model_options = asr_model_options(selected_model)
    models = {item["model_size"]: _model_info(item["model_size"]) for item in model_options}

    return {
        "platform": {
            "system": system,
            "machine": machine,
            "apple_silicon": apple_silicon,
        },
        "selected_backend": selected_backend,
        "backends": {
            "mlx_whisper": _backend(
                _has_module("mlx_whisper"),
                accelerated=apple_silicon,
                supports_vad=False,
                supports_beam=False,
            ),
            "faster_whisper": _backend(
                _has_module("faster_whisper"),
                accelerated=False,
                supports_vad=True,
                supports_beam=True,
            ),
            "openai_whisper": _backend(
                _has_module("whisper"),
                accelerated=False,
                supports_vad=False,
                supports_beam=True,
            ),
        },
        "models": models,
        "model_options": model_options,
    }


def _backends(caps: dict[str, Any]) -> dict[str, Any]:
    backends = caps.get("backends", {}) if isinstance(caps, dict) else {}
    return backends if isinstance(backends, dict) else {}


def _installed(caps: dict[str, Any], backend: str) -> bool:
    info = _backends(caps).get(backend, {})
    return bool(isinstance(info, dict) and info.get("installed"))


def _installed_backends(caps: dict[str, Any]) -> list[str]:
    return [backend for backend in BACKEND_ORDER if _installed(caps, backend)]


def _selected_backend(caps: dict[str, Any]) -> str:
    selected = caps.get("selected_backend") if isinstance(caps, dict) else ""
    if isinstance(selected, str):
        selected = selected.strip()
        if selected in BACKEND_ORDER:
            return selected
    return ""


def _model(caps: dict[str, Any], model: str) -> dict[str, Any]:
    models = caps.get("models", {}) if isinstance(caps, dict) else {}
    info = models.get(model) if isinstance(models, dict) else None
    if isinstance(info, dict):
        return info
    return {
        "available": False,
        "source": "unknown",
        "download_hint": MODEL_DOWNLOAD_HINTS.get(model, ""),
    }


def _backend_model_info(caps: dict[str, Any], model: str, backend: str) -> dict[str, Any]:
    info = _model(caps, model)
    backend_info = info.get(backend)
    if isinstance(backend_info, dict):
        merged = _unknown_model_info(model)
        merged.update(backend_info)
        return merged
    if backend == "mlx_whisper":
        return {
            "available": bool(info.get("available")),
            "source": info.get("source", "unknown"),
            "path": info.get("path", ""),
            "path_or_repo": info.get("path_or_repo", ""),
            "download_hint": info.get("download_hint", MODEL_DOWNLOAD_HINTS.get(model, "")),
        }
    return _unknown_model_info(model)


def _first_offline_model(caps: dict[str, Any], backend: str) -> str:
    for model in OFFLINE_MODEL_ORDER:
        if _backend_model_info(caps, model, backend).get("available"):
            return model
    return OFFLINE_MODEL_ORDER[0]


def _recommendation(
    *,
    mode: str,
    backend: str,
    model: str,
    ready: bool,
    reason: str,
    caps: dict[str, Any],
) -> dict[str, Any]:
    info = _backend_model_info(caps, model, backend) if model and backend else {}
    backend_info = _backends(caps).get(backend, {}) if backend else {}
    if not isinstance(backend_info, dict):
        backend_info = {}
    return {
        "mode": mode,
        "backend": backend,
        "model_size": model,
        "ready": ready,
        "download_required": bool(model and not info.get("available")),
        "download_hint": info.get("download_hint", ""),
        "model_source": info.get("source", ""),
        "supports_vad": bool(backend_info.get("supports_vad")),
        "supports_beam": bool(backend_info.get("supports_beam")),
        "reason": reason,
    }


def _model_for_mode(mode: str, backend: str, caps: dict[str, Any]) -> str:
    if mode == "accuracy":
        return "large-v3"
    if mode == "offline":
        return _first_offline_model(caps, backend)
    return "large-v3-turbo" if backend == "mlx_whisper" else "small"


def recommend_asr_settings(mode: str, caps: dict[str, Any]) -> dict[str, Any]:
    selected_mode = mode if mode in ASR_MODES else "speed"
    explicit_backend = _selected_backend(caps)
    if explicit_backend:
        model = _model_for_mode(selected_mode, explicit_backend, caps)
        if not _installed(caps, explicit_backend):
            return _recommendation(
                mode=selected_mode,
                backend=explicit_backend,
                model=model,
                ready=False,
                reason=f"已选择 {explicit_backend} 后端，但本机未检测到该依赖。",
                caps=caps,
            )
        return _recommendation(
            mode=selected_mode,
            backend=explicit_backend,
            model=model,
            ready=True,
            reason=f"已按设置使用 {explicit_backend} 后端；模式用于选择模型大小和下载提示。",
            caps=caps,
        )

    installed = _installed_backends(caps)
    if not installed:
        return _recommendation(
            mode=selected_mode,
            backend="",
            model="",
            ready=False,
            reason="未检测到本地 ASR 后端，请安装 mlx-whisper、faster-whisper 或 openai-whisper。",
            caps=caps,
        )

    if selected_mode == "accuracy":
        backend = "faster_whisper" if _installed(caps, "faster_whisper") else installed[0]
        reason = "准确优先：使用更大模型，并在可用时选择支持 VAD 和 beam search 的后端。"
    elif selected_mode == "offline":
        backend = "mlx_whisper" if _installed(caps, "mlx_whisper") else installed[0]
        reason = "离线优先：优先选择已缓存或内置模型，减少下载依赖。"
    else:
        backend = "mlx_whisper" if _installed(caps, "mlx_whisper") else installed[0]
        reason = "速度优先：优先选择 Apple Silicon/本地快速后端和较快模型。"
    model = _model_for_mode(selected_mode, backend, caps)

    return _recommendation(
        mode=selected_mode,
        backend=backend,
        model=model,
        ready=True,
        reason=reason,
        caps=caps,
    )
