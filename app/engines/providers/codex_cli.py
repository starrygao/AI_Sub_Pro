"""Codex CLI provider using subprocess (no API key; uses user's local auth)."""
import json
import logging
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import BaseProvider
from app.engines.model_catalog import model_ids, model_efforts, context_window
from .result_contract import (
    provider_response_instruction,
    reconcile_translation_results,
    redact_error_message,
)

log = logging.getLogger(__name__)

CODEX_CLI_MODELS = model_ids("codex_cli")
DEFAULT_CODEX_CLI_MODEL = "gpt-5.5"
ALLOWED_CODEX_CLI_EFFORTS = {"auto", "low", "medium", "high", "xhigh", "max", "ultra"}
CODEX_CLI_MODEL_EFFORTS = model_efforts("codex_cli")


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


def _coerce_effort(value, model: str) -> str:
    if not isinstance(value, str):
        return "auto"
    normalized = value.strip().lower()
    if normalized == "auto":
        return normalized
    return normalized if normalized in CODEX_CLI_MODEL_EFFORTS.get(model, set()) else "auto"


class CodexCliProvider(BaseProvider):
    """Translation via local `codex` CLI; uses the user's Codex login."""

    full_document_max_items = 400

    def __init__(self, config: dict):
        config = config if isinstance(config, dict) else {}
        self.model = _coerce_model(config.get("model"))
        self.effort = _coerce_effort(config.get("effort"), self.model)
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
        return context_window("codex_cli", self.model)

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
            f"Input JSON. {provider_response_instruction(system_prompt)}"
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
            "--ask-for-approval",
            "never",
            "exec",
            "--ignore-user-config",
        ]
        if self.effort != "auto":
            cmd.extend(["--config", f'model_reasoning_effort="{self.effort}"'])
        cmd.extend([
            "--model",
            self.model,
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "--output-last-message",
            output_path,
            "-",
        ])
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(
                    input=prompt,
                    timeout=self.timeout_sec,
                )
            except subprocess.TimeoutExpired:
                self._terminate_process_group(proc)
                raise
            if proc.returncode != 0:
                raise RuntimeError(f"codex CLI exit {proc.returncode}: {(stderr or '')[:200]}")

            text = path.read_text(encoding="utf-8", errors="replace").strip()
            return text or stdout
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _terminate_process_group(proc) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (AttributeError, ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass

        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (AttributeError, ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                return
        try:
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
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
