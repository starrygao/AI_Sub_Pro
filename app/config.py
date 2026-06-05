"""
Global configuration management with persistence.
"""
import os
import json
import copy
import shutil
from datetime import datetime, timezone
from pathlib import Path

import sys as _sys

_ENV_DATA_DIR = os.environ.get("AI_SUB_PRO_DATA_DIR", "").strip()
if _ENV_DATA_DIR:
    DATA_DIR = Path(_ENV_DATA_DIR).expanduser()
    BASE_DIR = DATA_DIR.parent
elif getattr(_sys, '_MEIPASS', None):
    # In PyInstaller bundle, use a writable user directory.
    BASE_DIR = Path.home() / "AI_Sub_Pro_Data"
    DATA_DIR = BASE_DIR / "data"
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"

PROJECTS_DIR = DATA_DIR / "projects"
CONFIG_FILE = DATA_DIR / "config.json"
KB_FILE = DATA_DIR / "knowledge.json"

# Ensure dirs exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "api_keys": {
        "openai": "",
        "deepseek": "",
        "gemini": "",
    },
    "tmdb": {
        "api_key": "",
        "language": "zh-CN",
    },
    "trailer": {
        "max_video_height": 1080,    # 0 = best available; otherwise cap (1080 / 720 / 480)
    },
    "asr": {
        "mode": "speed",
        "model_size": "large-v3-turbo",
        "language": "auto",
        "vad_filter": True,
        "offset_ms": 0,
        "beam_size": 5,
        "use_demucs": True,
    },
    "translation": {
        "primary_provider": "openai",
        "primary_model": "gpt-4o",
        "polish_provider": "",
        "polish_model": "",
        "batch_size": 10,
        "context_window": 3,
        "target_language": "简体中文",
        "filter_repetitive": True,
        "repetitive_threshold": 3,
        "filter_interjections": True,
        "full_doc_mode": False,
        "use_translation_memory": True,
        "use_phrase_library": True,
        "memory_retrieval_backend": "auto",
        "phrase_retrieval_backend": "auto",
        "max_memory_examples": 6,
        "max_phrase_examples": 6,
        "qa_auto_repair": False,
        "qa_auto_repair_rounds": 1,
    },
    "providers": {
        "claude_cli": {
            "enabled": True,
            "model": "claude-opus-4-7",
            "timeout_sec": 180,
        },
        "codex_cli": {
            "enabled": True,
            "model": "gpt-5.5",
            "timeout_sec": 180,
        },
    },
    "concurrency": {
        "asr": 2,
        "translate": 4,
        "download": 3,
        "burn": 1,
    },
    "general": {
        "max_workers": 4,
        "theme": "dark",
    },
}


def _reject_json_constant(value: str):
    raise ValueError(f"Invalid JSON constant: {value}")


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, filling missing keys from base."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict):
            if isinstance(v, dict):
                result[k] = _deep_merge(result[k], v)
            else:
                result[k] = copy.deepcopy(result[k])
        else:
            result[k] = copy.deepcopy(v)
    return result


def _backup_invalid_config() -> None:
    if not CONFIG_FILE.exists():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = CONFIG_FILE.with_name(f"{CONFIG_FILE.stem}.invalid-{stamp}{CONFIG_FILE.suffix}")
    counter = 1
    while backup.exists():
        backup = CONFIG_FILE.with_name(
            f"{CONFIG_FILE.stem}.invalid-{stamp}-{counter}{CONFIG_FILE.suffix}"
        )
        counter += 1
    shutil.copy2(CONFIG_FILE, backup)


class Config:
    _data: dict = {}

    @classmethod
    def load(cls) -> dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f, parse_constant=_reject_json_constant)
                cls._data = _deep_merge(DEFAULT_CONFIG, saved)
            except Exception:
                _backup_invalid_config()
                cls._data = copy.deepcopy(DEFAULT_CONFIG)
        else:
            cls._data = copy.deepcopy(DEFAULT_CONFIG)
        cls.save()
        return cls._data

    @classmethod
    def save(cls):
        from app.utils.project_store import atomic_write_json
        atomic_write_json(CONFIG_FILE, cls._data)

    @classmethod
    def get(cls, *keys, default=None):
        d = cls._data
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d

    @classmethod
    def set_val(cls, *keys_and_value):
        """set_val('api_keys', 'openai', 'sk-xxx') -> config[api_keys][openai] = 'sk-xxx'"""
        keys, value = keys_and_value[:-1], keys_and_value[-1]
        d = cls._data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        cls.save()

    @classmethod
    def update(cls, data: dict):
        cls._data = _deep_merge(cls._data, data)
        cls.save()

    @classmethod
    def to_dict(cls) -> dict:
        return copy.deepcopy(cls._data)
