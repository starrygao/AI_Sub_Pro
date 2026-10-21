"""
Global configuration management with persistence.
"""
import os
import json
import copy
import shutil
import threading
import uuid
import logging
from app.credentials import SystemCredentialStore, CredentialError
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
        "backend": "auto",
        "model_size": "large-v3-turbo",
        "language": "auto",
        "vad_filter": True,
        "offset_ms": 0,
        "beam_size": 5,
        "use_demucs": True,
    },
    "translation": {
        "primary_provider": "omp_cli",
        "primary_model": "openai-codex/gpt-6-astra",
        "primary_effort": "medium",
        "polish_provider": "",
        "polish_model": "",
        "polish_effort": "auto",
        "review_provider": "omp_cli",
        "review_model": "openai-codex/gpt-6.1-sol",
        "review_effort": "xhigh",
        "batch_size": 10,
        "context_window": 3,
        "target_language": "简体中文",
        "filter_repetitive": True,
        "repetitive_threshold": 3,
        "filter_interjections": True,
        "quality_mode": "professional",
        "full_doc_mode": False,
        "use_translation_memory": True,
        "use_phrase_library": True,
        "memory_retrieval_backend": "auto",
        "phrase_retrieval_backend": "auto",
        "max_memory_examples": 6,
        "max_phrase_examples": 6,
        "require_kb_suggestion_review": False,
        "missing_translation_retries": 2,
        "missing_translation_retry_batch_size": 5,
        "missing_translation_retry_max_blocks": 200,
        "missing_translation_abort_min_blocks": 200,
        "missing_translation_abort_missing_pct": 50,
        "qa_auto_repair": True,
        "qa_auto_repair_rounds": 3,
        "semantic_qa": True,
        "semantic_qa_batch_size": 40,
    },
    "providers": {
        "claude_cli": {
            "enabled": True,
            "timeout_sec": 180,
        },
        "codex_cli": {
            "enabled": True,
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


def _migrate_legacy_cli_models(config: dict) -> None:
    """Move the former provider-wide CLI model into each selected stage."""
    if not isinstance(config, dict):
        return
    providers = config.get("providers")
    translation = config.get("translation")
    if not isinstance(providers, dict):
        return

    for provider_name in ("claude_cli", "codex_cli"):
        provider_cfg = providers.get(provider_name)
        if not isinstance(provider_cfg, dict):
            continue
        legacy_model = provider_cfg.pop("model", None)
        if not isinstance(translation, dict) or not isinstance(legacy_model, str):
            continue
        legacy_model = legacy_model.strip()
        if not legacy_model:
            continue
        if translation.get("primary_provider") == provider_name:
            translation["primary_model"] = legacy_model
        if translation.get("polish_provider") == provider_name:
            translation["polish_model"] = legacy_model


def _migrate_legacy_review_stage(config: dict) -> None:
    """Persist the former primary-model review choice once, never at QA time."""
    translation = config.get("translation") if isinstance(config, dict) else None
    if not isinstance(translation, dict) or any(
        f"review_{field}" in translation for field in ("provider", "model", "effort")
    ):
        return
    for field in ("provider", "model", "effort"):
        translation[f"review_{field}"] = copy.deepcopy(
            translation.get(f"primary_{field}", DEFAULT_CONFIG["translation"][f"primary_{field}"])
        )


def _seal_legacy_review_deliveries() -> None:
    """Freeze valid completed library results before changing configuration identity."""
    from app.library.settings import seal_completed_delivery
    from app.utils.project_store import load_project
    for path in PROJECTS_DIR.glob("*/project.json"):
        if path.is_symlink() or path.parent.is_symlink():
            continue
        try:
            project = load_project(path.parent.name)
        except (FileNotFoundError, ValueError):
            continue
        if project.get("library_status") != "done" or not project.get("library_source_path"):
            continue
        if not seal_completed_delivery(path.parent.name):
            raise RuntimeError("已完成字幕正在读取或保存，质量复核配置迁移已推迟")


def _drop_legacy_cli_models(config: dict) -> None:
    providers = config.get("providers") if isinstance(config, dict) else None
    if not isinstance(providers, dict):
        return
    for provider_name in ("claude_cli", "codex_cli"):
        provider_cfg = providers.get(provider_name)
        if isinstance(provider_cfg, dict):
            provider_cfg.pop("model", None)


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


def credential_store():
    return SystemCredentialStore(CONFIG_FILE)


def _secret_fields(data):
    keys = data.get("api_keys", {})
    if isinstance(keys, dict):
        for key in keys:
            yield "api_keys", key
    yield "tmdb", "api_key"


class Config:
    _lock = threading.RLock()
    _data: dict = {}

    @classmethod
    def load(cls) -> dict:
        legacy_review = False
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f, parse_constant=_reject_json_constant)
                _migrate_legacy_cli_models(saved)
                translation = saved.get("translation", {}) if isinstance(saved, dict) else None
                legacy_review = isinstance(translation, dict) and not any(
                    f"review_{field}" in translation for field in ("provider", "model", "effort")
                )
                defaults = copy.deepcopy(DEFAULT_CONFIG)
                if legacy_review:
                    for field in ("provider", "model", "effort"):
                        defaults["translation"].pop(f"review_{field}")
                cls._data = _deep_merge(defaults, saved)
            except Exception:
                _backup_invalid_config()
                cls._data = copy.deepcopy(DEFAULT_CONFIG)
        else:
            cls._data = copy.deepcopy(DEFAULT_CONFIG)
        # Credential failures must never be interpreted as corrupt JSON.
        refs = saved.get("_credential_refs", {}) if CONFIG_FILE.exists() and 'saved' in locals() and isinstance(saved, dict) else {}
        cls._data.pop("_credential_refs", None)
        store = credential_store()
        for section, key in _secret_fields(cls._data):
            ref = refs.get(section + "." + key)
            if ref:
                value = store.get(ref)
                if value is None:
                    raise CredentialError("已保存的系统凭证无法读取；原配置已保留")
                cls._data.setdefault(section, {})[key] = value
        if legacy_review:
            _seal_legacy_review_deliveries()
            _migrate_legacy_review_stage(cls._data)
        cls.save()
        return cls._data

    @classmethod
    def _persist(cls, data):
        from app.utils.project_store import atomic_write_json
        store = credential_store()
        disk = copy.deepcopy(data)
        disk.pop("_credential_refs", None)
        old_refs = {}
        if CONFIG_FILE.exists():
            try:
                old_refs = json.loads(CONFIG_FILE.read_text()).get("_credential_refs", {})
            except (ValueError, AttributeError):
                pass
        refs, created = {}, []
        publishing = False
        try:
            for section, key in _secret_fields(disk):
                field = section + "." + key
                value = disk.get(section, {}).get(key, "")
                old = old_refs.get(field)
                if value:
                    if old and store.get(old) == value:
                        refs[field] = old
                    else:
                        ref = uuid.uuid4().hex
                        created.append(ref)
                        store.set(ref, value)
                        if store.get(ref) != value:
                            raise CredentialError("系统凭证写入验证失败，原配置已保留")
                        refs[field] = ref
                disk.setdefault(section, {})[key] = ""
            if refs:
                disk["_credential_refs"] = refs
            publishing = True
            atomic_write_json(CONFIG_FILE, disk)
        except Exception:
            # A rename may commit before the filesystem reports a sync error.
            # Never delete credentials that the visible config now references.
            if publishing:
                try:
                    if json.loads(CONFIG_FILE.read_text()) == disk:
                        logging.getLogger(__name__).warning("Configuration committed; durability confirmation failed, old credential retained")
                        return
                except (OSError, ValueError):
                    pass
            for ref in created:
                try:
                    store.delete(ref)
                except CredentialError:
                    pass
            raise
        for ref in set(old_refs.values()) - set(refs.values()):
            try:
                store.delete(ref)
            except CredentialError:
                logging.getLogger(__name__).warning("Obsolete credential cleanup deferred")

    @classmethod
    def save(cls):
        with cls._lock:
            cls._persist(cls._data)

    @classmethod
    def public_dict(cls):
        data = cls.to_dict()
        configured = {}
        for section, key in _secret_fields(data):
            configured[key if section == "api_keys" else "tmdb"] = bool(data.get(section, {}).get(key))
            data.setdefault(section, {})[key] = ""
        data.pop("_credential_refs", None)
        data["credentials_configured"] = configured
        return data

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
        with cls._lock:
            data = copy.deepcopy(cls._data)
            d = data
            for key in keys[:-1]:
                d = d.setdefault(key, {})
            d[keys[-1]] = value
            cls._persist(data)
            cls._data = data

    @classmethod
    def update(cls, data: dict):
        with cls._lock:
            sanitized = copy.deepcopy(data)
            sanitized.pop("_credential_refs", None)
            _drop_legacy_cli_models(sanitized)
            updated = _deep_merge(cls._data, sanitized)
            _drop_legacy_cli_models(updated)
            cls._persist(updated)
            cls._data = updated

    @classmethod
    def to_dict(cls) -> dict:
        return copy.deepcopy(cls._data)
