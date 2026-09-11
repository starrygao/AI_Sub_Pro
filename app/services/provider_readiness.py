"""Shared configuration/domain rules, independent of HTTP routing."""


_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "claude_cli": "Claude CLI",
    "codex_cli": "Codex CLI",
}

def _dict_section(cfg: dict, key: str) -> dict:
    value = cfg.get(key) if isinstance(cfg, dict) else None
    return value if isinstance(value, dict) else {}

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


def require_translation_ready():
    from app.config import Config
    from fastapi import HTTPException
    readiness = _translation_readiness(Config.to_dict())
    if not readiness.get("translation_ready"):
        raise HTTPException(status_code=400, detail=readiness.get("translation_hint") or "请先配置翻译服务")
    return readiness
