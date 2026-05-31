"""Codex CLI provider using subprocess (no API key; uses user's local auth)."""
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import BaseProvider
from .result_contract import reconcile_translation_results, redact_error_message

log = logging.getLogger(__name__)

CODEX_CLI_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
]
DEFAULT_CODEX_CLI_MODEL = CODEX_CLI_MODELS[0]


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


def _coerce_model(value) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_CODEX_CLI_MODEL


class CodexCliProvider(BaseProvider):
    """Translation via local `codex` CLI; uses the user's Codex login."""

    def __init__(self, config: dict):
        config = config if isinstance(config, dict) else {}
        self.model = _coerce_model(config.get("model"))
        self.timeout_sec = _coerce_timeout(config.get("timeout_sec", 180))

    @staticmethod
    def check_cli_available() -> bool:
        try:
            r = subprocess.run(["codex", "--version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def check_logged_in() -> bool:
        try:
            r = subprocess.run(["codex", "login", "status"], capture_output=True, text=True, timeout=5)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False
        if r.returncode != 0:
            return False
        out = (r.stdout + r.stderr).lower()
        negative_markers = (
            "not logged",
            "not authenticated",
            "not signed",
            "login required",
            "unauthenticated",
            "unauthorized",
        )
        return not any(marker in out for marker in negative_markers)

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
            return [self._err(it, "Codex CLI not installed / not in PATH (未安装)") for it in items]
        if not self.check_logged_in():
            return [self._err(it, "Codex CLI not logged in: run `codex login` to authenticate (未登录)") for it in items]

        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            try:
                text = self._invoke(items, system_prompt)
                return self._parse(text, items)
            except Exception as e:
                last_exc = e
                log.warning("Codex CLI attempt %d failed: %s", attempt + 1, redact_error_message(e, 120))
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        err = f"{type(last_exc).__name__}: {redact_error_message(last_exc, 120)}" if last_exc else "Codex CLI failure"
        return [self._err(it, err) for it in items]

    def _invoke(self, items, system_prompt) -> str:
        """Invoke codex CLI and return the final assistant message text."""
        prompt = (
            f"{system_prompt}\n\n"
            f"Input JSON (translate each item; reply with ONLY a JSON array of "
            f'{{\"id\": N, \"translation\": \"...\"}} objects, no prose). '
            f"Each output id MUST be copied verbatim from the matching input "
            f"item — do not renumber — and every input item must appear exactly "
            f"once in the output:\n"
            f"{json.dumps(items, ensure_ascii=False)}"
        )
        fd, output_path = tempfile.mkstemp(prefix="aisubpro-codex-", suffix=".txt")
        os.close(fd)
        path = Path(output_path)
        cmd = [
            "codex",
            "exec",
            "--model",
            self.model,
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "--output-last-message",
            output_path,
            "-",
        ]
        try:
            r = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
            if r.returncode != 0:
                raise RuntimeError(f"codex CLI exit {r.returncode}: {r.stderr[:200]}")

            text = path.read_text(encoding="utf-8", errors="replace").strip()
            return text or r.stdout
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _err(item, msg: str) -> dict:
        return {"id": item.get("id"), "translation": "", "error": msg}

    @staticmethod
    def _parse(text: str, items: List[Dict]) -> List[Dict]:
        if not text:
            return [CodexCliProvider._err(it, "empty response from Codex CLI") for it in items]
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
            return [CodexCliProvider._err(it, f"unparseable response: {cleaned[:120]}") for it in items]

        return reconcile_translation_results(parsed, items)
