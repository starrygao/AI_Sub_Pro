"""Shared configuration/domain rules, independent of HTTP routing."""
from app.config import DEFAULT_CONFIG


_PROVIDER_LABELS = {
    "omp_cli": "OMP CLI",
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

    if provider == "omp_cli":
        from app.engines.providers.omp_cli import OmpCliProvider, DEFAULT_OMP_CLI_MODEL

        translation = _dict_section(cfg, "translation")
        primary_provider = _configured_translation_providers(translation)[0][1]
        primary_value = translation.get("primary_model")
        primary_model = (
            primary_value.strip() if isinstance(primary_value, str) and primary_value.strip()
            else DEFAULT_OMP_CLI_MODEL if primary_provider == "omp_cli" else "gpt-4o"
        )
        models = [primary_model] if primary_provider == "omp_cli" else []
        polish_provider = translation.get("polish_provider")
        if isinstance(polish_provider, str) and polish_provider.strip() == "omp_cli":
            polish_value = translation.get("polish_model")
            polish_model = (
                polish_value.strip() if isinstance(polish_value, str) and polish_value.strip()
                else primary_model
            )
            if polish_model not in models:
                models.append(polish_model)
        review_provider = translation.get("review_provider", DEFAULT_CONFIG["translation"]["review_provider"])
        if _review_enabled(translation) and isinstance(review_provider, str) and review_provider.strip() == "omp_cli":
            review_value = translation.get("review_model")
            review_model = (
                review_value.strip() if isinstance(review_value, str) and review_value.strip()
                else DEFAULT_CONFIG["translation"]["review_model"]
            )
            if review_model not in models:
                models.append(review_model)
        try:
            installed = OmpCliProvider.check_cli_available()
        except Exception:
            installed = False
        try:
            logged_in = installed and all([OmpCliProvider.check_logged_in(model) for model in models])
        except Exception:
            logged_in = False
        if logged_in:
            hint = f"{role_label}OMP CLI 已就绪"
        elif installed:
            hint = f"{role_label}所选 OMP 模型不可用，请运行 omp login 登录对应服务，并检查模型选择"
        else:
            hint = f"{role_label}未检测到 omp 命令，请先安装 OMP CLI"
        return {
            "translation_provider": provider,
            "translation_label": label,
            "translation_ready": bool(logged_in),
            "translation_hint": hint,
            "omp_cli_installed": installed,
            "omp_cli_logged_in": bool(logged_in),
            "claude_cli_installed": None,
            "claude_cli_logged_in": None,
            "codex_cli_installed": None,
            "codex_cli_logged_in": None,
        }

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

def _review_enabled(translation: dict, *, strict_quality_gate: bool = False) -> bool:
    mode = translation.get("quality_mode")
    return (
        strict_quality_gate
        or isinstance(mode, str) and mode.strip().lower() == "professional"
        or translation.get("semantic_qa") is True
    )

def _configured_translation_providers(translation: dict) -> list[tuple[str, str]]:
    raw_primary = translation.get("primary_provider")
    primary_value = raw_primary.strip() if isinstance(raw_primary, str) else ""
    primary = primary_value if primary_value in _PROVIDER_LABELS else "omp_cli"

    raw_polish = translation.get("polish_provider")
    polish_value = raw_polish.strip() if isinstance(raw_polish, str) else ""
    polish = polish_value if polish_value in _PROVIDER_LABELS else ""

    providers = [("主翻译引擎：", primary)]
    if polish and polish != primary:
        providers.append(("润色引擎：", polish))
    if _review_enabled(translation):
        raw_review = translation.get("review_provider", DEFAULT_CONFIG["translation"]["review_provider"])
        review_value = raw_review.strip() if isinstance(raw_review, str) else ""
        review = review_value if review_value in _PROVIDER_LABELS else "omp_cli"
        if review not in {provider for _, provider in providers}:
            providers.append(("质量复核引擎：", review))
    return providers

def _translation_readiness(cfg: dict, *, strict_quality_gate: bool = False) -> dict:
    """Return readiness for all configured translation workflow providers."""
    translation = _dict_section(cfg, "translation")
    if strict_quality_gate:
        translation = {**translation, "semantic_qa": True}
        cfg = {**cfg, "translation": translation}
    provider_checks = [
        _provider_readiness(provider, role_label=role_label, cfg=cfg)
        for role_label, provider in _configured_translation_providers(translation)
    ]
    blocking = [check for check in provider_checks if not check.get("translation_ready")]
    ready = not blocking

    primary_check = provider_checks[0] if provider_checks else _provider_readiness(
        "omp_cli", role_label="主翻译引擎：", cfg=cfg
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
    omp_checks = [check for check in provider_checks if check["translation_provider"] == "omp_cli"]
    omp_installed = omp_checks[0]["omp_cli_installed"] if omp_checks else None
    omp_logged_in = omp_checks[0]["omp_cli_logged_in"] if omp_checks else None

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
        "omp_cli_installed": omp_installed,
        "omp_cli_logged_in": omp_logged_in,
    }


def require_translation_ready(*, strict_quality_gate: bool = False):
    from app.config import Config
    from fastapi import HTTPException
    readiness = _translation_readiness(Config.to_dict(), strict_quality_gate=strict_quality_gate)
    if not readiness.get("translation_ready"):
        raise HTTPException(status_code=400, detail=readiness.get("translation_hint") or "请先配置翻译服务")
    return readiness
