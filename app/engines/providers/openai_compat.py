"""OpenAI-compatible provider for openai/deepseek/gemini via the openai SDK.

Extracted from app/engines/translator.py during Phase 2 / Task 2 of the
translator refactor. The legacy `TranslationProvider` name remains importable
from app.engines.translator as an alias to OpenAICompatProvider.
"""
import json
import logging
import re
import time
from typing import List, Dict, Optional

from openai import OpenAI

from .base import BaseProvider
from app.engines.model_catalog import capabilities, context_window
from .result_contract import reconcile_translation_results, redact_error_message

log = logging.getLogger(__name__)

# Provider -> base_url mapping
PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}



def _clean_str(value, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _try_parse_json(text: str):
    """Robustly parse JSON from AI response (handles markdown, trailing commas, etc.)."""
    if not isinstance(text, str) or not text:
        return None
    # Strip markdown code blocks
    text = re.sub(r"```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    # Fix trailing commas
    try:
        fixed = re.sub(r",\s*([\]}])", r"\1", text)
        return json.loads(fixed)
    except (TypeError, ValueError):
        pass
    # Try to extract JSON array from text
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (TypeError, ValueError):
            pass
    log.warning("Failed to parse JSON: %s...", text[:100])
    return None


def _reconcile_results(parsed_list: List[Dict], items: List[Dict]) -> List[Dict]:
    """Align a model's result list against the input items by id.

    Guarantees exactly one output entry per input item, in input order:
      * id present, non-empty translation -> {id, translation, error: ""}
      * id present, empty translation     -> {id, translation: "", error: ""}
        (intentional — e.g. the sound-marker rule — NOT a failure)
      * id absent from the response       -> {id, translation: "", error: "missing in model response"}

    Without this, any id the model omits is silently dropped and the block is
    left untranslated with no error recorded.
    """
    return reconcile_translation_results(parsed_list, items)


class OpenAICompatProvider(BaseProvider):
    """One class for openai / deepseek / gemini via the openai SDK.

    Accepts EITHER:
      - new shape: ``OpenAICompatProvider({"provider": ..., "api_key": ..., "model": ..., "base_url"?: ...})``
      - legacy shape (positional or kwargs): ``OpenAICompatProvider(provider, api_key, model)``

    The legacy shape is preserved so the back-compat ``TranslationProvider``
    alias keeps working for existing callers (api/settings.py, tests).
    """

    def __init__(
        self,
        config=None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        *,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        # Dual-mode: accept either config dict (new) or legacy (provider, api_key, model)
        if isinstance(config, dict):
            cfg = config
        elif config is None and provider is None:
            # All-keyword legacy form: provider=..., api_key=..., model=...
            cfg = {
                "provider": None,
                "api_key": api_key,
                "model": model,
                "base_url": base_url,
            }
        elif isinstance(config, str) or config is None:
            # Positional legacy form: (provider, api_key, model)
            cfg = {
                "provider": config if config is not None else provider,
                "api_key": api_key,
                "model": model,
                "base_url": base_url,
            }
        else:
            raise TypeError(
                f"OpenAICompatProvider expects a config dict or legacy "
                f"(provider, api_key, model); got {type(config).__name__}"
            )

        # Honor explicit kwargs even when a dict was supplied (rare, but safe).
        self.provider_name = _clean_str(cfg.get("provider") or provider, "openai") or "openai"
        self.model = _clean_str(cfg.get("model") or model)
        if not self.model:
            raise ValueError("OpenAICompatProvider requires a 'model'")
        requested_effort = _clean_str(cfg.get("effort"), "auto").lower()
        supported_efforts = capabilities(self.provider_name, self.model)["reasoning_efforts"]
        self.effort = requested_effort if requested_effort in supported_efforts else "auto"
        resolved_key = _clean_str(cfg.get("api_key") or api_key)
        resolved_base = (
            _clean_str(cfg.get("base_url"))
            or _clean_str(base_url)
            or PROVIDER_URLS.get(self.provider_name, PROVIDER_URLS["openai"])
        )
        self.client = OpenAI(api_key=resolved_key, base_url=resolved_base)
        self.is_deepseek = self.provider_name == "deepseek"

    # -- legacy attribute alias ------------------------------------------------
    @property
    def provider(self) -> str:
        """Legacy attribute alias — old code reads `.provider` for the name."""
        return self.provider_name

    # -- core API --------------------------------------------------------------
    def translate_batch(self, items: List[Dict], system_prompt: str, retries: int = 3) -> List[Dict]:
        """
        Send a batch translation request.
        items: [{"id": 1, "original": "text"}, ...]
        Returns on success: [{"id": 1, "translation": "..."}, ...]
        Returns on retry exhaustion: equal-length list with each entry
          {"id": ..., "translation": "", "error": "<reason>"} so callers can
          surface the failure instead of silently dropping blocks.
        """
        user_content = json.dumps(items, ensure_ascii=False)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        last_exc: Optional[Exception] = None
        last_parse_error: str = ""

        for attempt in range(retries):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                }
                # New OpenAI reasoning models reject custom sampling parameters.
                if capabilities(self.provider_name, self.model)["temperature"] is True:
                    kwargs["temperature"] = 0.3
                if self.provider_name == "openai" and self.effort != "auto":
                    kwargs["reasoning_effort"] = self.effort
                # DeepSeek supports json response format
                if self.is_deepseek:
                    kwargs["response_format"] = {"type": "json_object"}

                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content

                parsed = _try_parse_json(content)
                if parsed is None:
                    log.warning("Attempt %d: JSON parse failed", attempt + 1)
                    if isinstance(content, str) and content:
                        last_parse_error = content[:200]
                    elif content:
                        last_parse_error = f"non-string response content: {type(content).__name__}"
                    else:
                        last_parse_error = "empty response"
                    if attempt < retries - 1:
                        time.sleep(1 * (attempt + 1))
                    continue

                # Normalize response to a list, then reconcile against `items`
                # so every input id gets exactly one entry (missing -> error).
                result_list = None
                if isinstance(parsed, list):
                    result_list = parsed
                elif isinstance(parsed, dict):
                    for key in ["translations", "items", "results", "data"]:
                        if key in parsed and isinstance(parsed[key], list):
                            result_list = parsed[key]
                            break
                    # Single translation wrapped in dict
                    if result_list is None and "id" in parsed and "translation" in parsed:
                        result_list = [parsed]
                if result_list is not None:
                    return _reconcile_results(result_list, items)
                # Parsed JSON but not a recognized shape — treat as parse error
                # so we retry or surface the issue.
                last_parse_error = f"unrecognized JSON shape: {type(parsed).__name__}"
                log.warning(
                    "Attempt %d: unrecognized JSON shape %s",
                    attempt + 1,
                    type(parsed).__name__,
                )
                if attempt < retries - 1:
                    time.sleep(1 * (attempt + 1))
                continue

            except Exception as e:
                last_exc = e
                log.warning("Attempt %d failed: %s", attempt + 1, redact_error_message(e, 100))
                if attempt < retries - 1:
                    time.sleep(1 * (attempt + 1))

        err_bits = []
        if last_exc is not None:
            err_bits.append(f"{type(last_exc).__name__}: {redact_error_message(last_exc, 120)}")
        if last_parse_error:
            err_bits.append(f"parse: {last_parse_error[:120]}")
        err_msg = " | ".join(err_bits) if err_bits else "unknown failure after retries"
        log.error("translate_batch exhausted %d retries: %s", retries, err_msg)
        return [{"id": it.get("id"), "translation": "", "error": err_msg} for it in items]

    def _connection_token_limit(self) -> dict:
        parameter = capabilities(self.provider_name, self.model)["token_limit_parameter"]
        return {parameter: 32 if parameter == "max_completion_tokens" else 5} if parameter else {}

    def test_connection(self) -> bool:
        """Test if the provider is reachable."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hi"}],
                **self._connection_token_limit(),
            )
            return bool(response.choices)
        except Exception as e:
            log.error("Connection test failed: %s", redact_error_message(e))
            return False

    # -- BaseProvider properties ----------------------------------------------
    @property
    def supports_full_document_mode(self) -> bool:
        return True

    @property
    def context_window_tokens(self) -> int:
        return context_window(self.provider_name, self.model)
