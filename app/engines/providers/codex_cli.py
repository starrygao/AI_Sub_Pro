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

from .base import BaseProvider, ProviderUnavailableError
from app.engines.model_catalog import model_ids, model_efforts, context_window, capabilities
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
    return normalized if normalized in capabilities('codex_cli', model)['reasoning_efforts'] else "auto"


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
            raise ProviderUnavailableError("Codex CLI 未安装或不在 PATH 中，请安装后重试")
        if not self.check_logged_in():
            raise ProviderUnavailableError("Codex CLI 未登录或无法读取登录状态，请运行 codex login 后重试")

        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            try:
                text = self._invoke(items, system_prompt)
                return self._parse(text, items)
            except ProviderUnavailableError:
                raise
            except Exception as e:
                last_exc = e
                log.warning("Codex CLI attempt %d failed: %s", attempt + 1, self._failure_message(e, len(items)))
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        err = self._failure_message(last_exc, len(items)) if last_exc else "Codex CLI failure"
        # Retrying smaller subtitle batches cannot repair an unavailable service.
        # Do not expose the unredacted exception as a chained traceback either.
        raise ProviderUnavailableError(f"Codex CLI 调用失败（尝试 {retries} 次）：{err}") from None

    def _failure_message(self, error: Exception, item_count: int) -> str:
        if isinstance(error, subprocess.TimeoutExpired):
            # TimeoutExpired starts with the entire command; truncation used to
            # hide the duration and leave the task page with unusable diagnostics.
            return (
                f"请求超时：{self.timeout_sec} 秒内未完成（本批 {item_count} 条）；"
                "请检查代理连接或服务响应后重试"
            )
        return f"{type(error).__name__}: {redact_error_message(error, 300)}"

    @staticmethod
    def _exit_diagnostic(stderr: str) -> str:
        """Select the terminal failure, not the CLI banner or echoed prompt."""
        clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", stderr)
        lines = [line.strip() for line in clean.splitlines() if line.strip()]
        # Startup can emit non-fatal ERROR logs (e.g. refreshing the model list).
        # The final CLI error takes priority, even if warnings follow it.
        terminal = [line for line in lines if re.match(r"^(?:error|fatal)\s*:", line, re.I)]
        logged = [line for line in lines if re.match(
            r"^(?:\d{4}-\d{2}-\d{2}T\S+\s+)?(?:ERROR|FATAL)\b", line,
        )]
        candidates = terminal or logged
        if not candidates:
            return "未返回可识别的错误详情，请检查 Codex 服务日志后重试"
        return redact_error_message(candidates[-1], 400)

    @staticmethod
    def _authentication_failure(stderr: str) -> str:
        """Classify full CLI diagnostics before log snippets truncate the cause."""
        diagnostic = stderr.lower()
        reused = (
            "refresh_token_reused" in diagnostic
            or "refresh token was already used" in diagnostic
            or "refresh token has already been used" in diagnostic
        )
        if reused:
            return (
                "Codex CLI 登录已失效：刷新凭证已被使用（refresh_token_reused）。"
                "请重新运行 codex login 完成登录后重试"
            )
        if any(marker in diagnostic for marker in (
            "401 unauthorized", "refresh_token_expired", "refresh_token_invalidated",
            "refresh_token_revoked", "token_expired", "invalid_grant",
            "your access token could not be refreshed",
        )):
            return "Codex CLI 登录已失效：认证凭证无效或已过期，请重新运行 codex login 完成登录后重试"
        return ""

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
                auth_error = self._authentication_failure(stderr or "")
                if auth_error:
                    raise ProviderUnavailableError(auth_error)
                diagnostic = self._exit_diagnostic(stderr or "")
                raise RuntimeError(f"Codex CLI 退出码 {proc.returncode}：{diagnostic}")

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
