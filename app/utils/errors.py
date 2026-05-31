"""Shared error-message redaction helpers."""
import re


def redact_error_message(value, limit: int = 200) -> str:
    """Return a user/log safe single-line error snippet."""
    text = str(value)
    text = re.sub(r"(api_key=)[^&\s'\"<>]+", r"\1<redacted>", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "sk-<redacted>", text)
    text = re.sub(r"\bAIza[A-Za-z0-9_-]{20,}\b", "AIza<redacted>", text)
    text = re.sub(
        r"((?:authorization|api-key|x-api-key)\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+",
        r"\1<redacted>",
        text,
        flags=re.IGNORECASE,
    )
    return text.replace("\n", " ")[:limit]
