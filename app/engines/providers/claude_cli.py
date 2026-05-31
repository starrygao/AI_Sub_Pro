"""Claude Code CLI provider using subprocess (no API key; uses user's subscription auth)."""
import json
import logging
import re
import subprocess
import time
from typing import List, Dict, Optional

from .base import BaseProvider
from .result_contract import reconcile_translation_results, redact_error_message

log = logging.getLogger(__name__)

CLAUDE_CLI_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]
ALLOWED_CLAUDE_CLI_MODELS = set(CLAUDE_CLI_MODELS)


def _coerce_timeout(value) -> int:
    if isinstance(value, bool):
        return 180
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 180
    if parsed < 5 or parsed > 3600:
        return 180
    return parsed


class ClaudeCliProvider(BaseProvider):
    """Translation via local `claude` CLI; uses user's subscription auth."""

    def __init__(self, config: dict):
        config = config if isinstance(config, dict) else {}
        model = config.get("model", "claude-opus-4-7")
        self.model = model if isinstance(model, str) else "claude-opus-4-7"
        if self.model not in ALLOWED_CLAUDE_CLI_MODELS:
            raise ValueError(f"Unsupported Claude CLI model: {self.model}")
        self.timeout_sec = _coerce_timeout(config.get("timeout_sec", 180))

    @staticmethod
    def check_cli_available() -> bool:
        try:
            r = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def check_logged_in() -> bool:
        """Best-effort login probe. Falls back to optimistic True if probe commands don't exist."""
        for cmd in (["claude", "auth", "status"], ["claude", "auth", "whoami"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    out = (r.stdout + r.stderr).lower()
                    if any(s in out for s in ("logged in", "authenticated", "@")):
                        return True
            except Exception:
                continue
        # Probe commands may not exist; surface real errors later during translate
        return True

    def test_connection(self) -> bool:
        return self.check_cli_available() and self.check_logged_in()

    @property
    def supports_full_document_mode(self) -> bool:
        return True

    @property
    def context_window_tokens(self) -> int:
        return 1_000_000

    def translate_batch(self, items, system_prompt, retries: int = 3):
        if not self.check_cli_available():
            return [self._err(it, "Claude Code CLI not installed / not in PATH (未安装)") for it in items]
        if not self.check_logged_in():
            return [self._err(it, "Claude Code not logged in: run `claude` to authenticate (未登录)") for it in items]

        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            try:
                text = self._invoke(items, system_prompt)
                return self._parse(text, items)
            except Exception as e:
                last_exc = e
                log.warning("Claude CLI attempt %d failed: %s", attempt + 1, redact_error_message(e, 120))
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        err = f"{type(last_exc).__name__}: {redact_error_message(last_exc, 120)}" if last_exc else "Claude CLI failure"
        return [self._err(it, err) for it in items]

    def _invoke(self, items, system_prompt) -> str:
        """Invoke claude CLI and return the assistant text / final result."""
        # Build prompt: system + user payload.
        # CLI doesn't expose separate system_prompt; inline it at the top of the prompt.
        prompt = (
            f"{system_prompt}\n\n"
            f"Input JSON (translate each item; reply with ONLY a JSON array of "
            f'{{\"id\": N, \"translation\": \"...\"}} objects, no prose). '
            f"Each output id MUST be copied verbatim from the matching input "
            f"item — do not renumber — and every input item must appear exactly "
            f"once in the output:\n"
            f"{json.dumps(items, ensure_ascii=False)}"
        )
        # Pass the prompt via stdin, not argv: a batch of 30+ subtitle items
        # easily exceeds ARG_MAX (~256KB on macOS) and would E2BIG on exec.
        # The bare `-p` flag tells the CLI to read the prompt from stdin.
        cmd = [
            "claude", "-p",
            "--model", self.model,
            "--output-format", "json",
            "--max-turns", "1",
        ]
        r = subprocess.run(cmd, input=prompt, capture_output=True,
                           text=True, timeout=self.timeout_sec)
        if r.returncode != 0:
            raise RuntimeError(f"claude CLI exit {r.returncode}: {r.stderr[:200]}")

        # --output-format json produces a single JSON envelope with .result containing the model's text.
        try:
            env = json.loads(r.stdout)
            if isinstance(env, dict):
                for key in ("result", "text", "content", "message"):
                    v = env.get(key)
                    if isinstance(v, str):
                        return v
        except (TypeError, ValueError):
            pass
        # Fallback: stdout is plain text
        return r.stdout

    @staticmethod
    def _err(item, msg: str) -> dict:
        return {"id": item.get("id"), "translation": "", "error": msg}

    @staticmethod
    def _parse(text: str, items: List[Dict]) -> List[Dict]:
        if not text:
            return [ClaudeCliProvider._err(it, "empty response from Claude CLI") for it in items]
        cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"```", "", cleaned).strip()
        parsed = None
        try:
            parsed = json.loads(re.sub(r",\s*([\]}])", r"\1", cleaned))
        except Exception:
            m = re.search(r"\[.*\]", cleaned, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except Exception:
                    parsed = None

        if not isinstance(parsed, list):
            return [ClaudeCliProvider._err(it, f"unparseable response: {cleaned[:120]}") for it in items]

        return reconcile_translation_results(parsed, items)
