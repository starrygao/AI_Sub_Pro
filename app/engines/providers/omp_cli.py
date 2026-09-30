"""Subtitle translation through OMP's isolated, ephemeral JSON event CLI."""
import json
import logging
import re
import subprocess
import time

from app.engines import omp_models
from app.engines.model_catalog import capabilities, context_window
from app.engines.omp_models import DEFAULT_OMP_CLI_MODEL
from .base import BaseProvider, ProviderUnavailableError
from .result_contract import provider_response_instruction, reconcile_translation_results, redact_error_message

log = logging.getLogger(__name__)


class OmpCliProvider(BaseProvider):
    full_document_max_items = 400

    def __init__(self, config: dict):
        config = config if isinstance(config, dict) else {}
        model = config.get('model')
        self.model = model.strip() if isinstance(model, str) and model.strip() else DEFAULT_OMP_CLI_MODEL
        effort = config.get('effort', 'medium')
        self.effort = effort.strip().lower() if isinstance(effort, str) else 'medium'
        if self.effort not in {'auto', 'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}:
            self.effort = 'medium'
        try:
            timeout = config.get('timeout_sec', 180)
            self.timeout_sec = int(timeout) if not isinstance(timeout, bool) else 180
        except (TypeError, ValueError, OverflowError):
            self.timeout_sec = 180
        if not 5 <= self.timeout_sec <= 3600:
            self.timeout_sec = 180

    @staticmethod
    def check_cli_available() -> bool:
        try:
            result = subprocess.run(['omp', '--version'], capture_output=True, timeout=5)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def check_logged_in(model=DEFAULT_OMP_CLI_MODEL) -> bool:
        try:
            return omp_models.available_model(model)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            return False

    def test_connection(self) -> bool:
        return self.check_cli_available() and self.check_logged_in(self.model)

    @property
    def supports_full_document_mode(self) -> bool:
        return True

    @property
    def context_window_tokens(self) -> int:
        return context_window('omp_cli', self.model)

    def translate_batch(self, items, system_prompt, retries: int = 3):
        if not items:
            return []
        if not self.check_cli_available():
            raise ProviderUnavailableError('OMP CLI 未安装或不在 PATH 中，请安装后重试')
        if not self.check_logged_in(self.model):
            raise ProviderUnavailableError('OMP CLI 所选模型不可用或无法读取认证状态，请在 omp 中 /login 后检查模型 selector')
        last_error = 'OMP CLI failure'
        for attempt in range(max(1, retries)):
            try:
                return self._parse(self._invoke(items, system_prompt), items)
            except ProviderUnavailableError:
                raise
            except subprocess.TimeoutExpired:
                last_error = f'请求超时：{self.timeout_sec} 秒内未完成（本批 {len(items)} 条）'
            except (OSError, ValueError, RuntimeError) as error:
                last_error = redact_error_message(error, 300)
            log.warning('OMP CLI attempt %d failed: %s', attempt + 1, last_error)
            if attempt + 1 < retries:
                time.sleep(2 * (attempt + 1))
        # Service/protocol failures must not become per-subtitle blank translations.
        raise ProviderUnavailableError(f'OMP CLI 调用失败：{last_error}') from None

    @staticmethod
    def _authentication_failure(diagnostic):
        if any(marker in diagnostic.lower() for marker in (
            'unauthorized', 'unauthenticated', 'authentication', 'not logged',
            'no api key', 'api key not found', 'invalid api key', 'invalid_api_key',
            'refresh_token_', 'refresh token', 'invalid_grant', 'token_expired',
        )):
            raise ProviderUnavailableError('OMP CLI 认证失败或登录已失效，请在 omp 中重新 /login 后重试')

    @staticmethod
    def _exit_diagnostic(stderr):
        clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', stderr)
        lines = [line.strip() for line in clean.splitlines() if re.match(
            r'^\s*(?:(?:\d{4}-\d{2}-\d{2}T\S+)\s+)?(?:error|fatal)\b', line, re.I)]
        return redact_error_message(lines[-1], 300) if lines else '未返回可识别的错误详情，请检查 OMP 服务状态'

    def _invoke(self, items, system_prompt):
        prompt = (
            f'Input JSON. {provider_response_instruction(system_prompt)}'
            'Each output id MUST be copied verbatim from the matching input item; '
            'do not renumber. Every input item must appear exactly once.\n'
            + json.dumps(items, ensure_ascii=False)
        )
        with omp_models.isolated_cli() as (cwd, overlay, env):
            cmd = ['omp', '-p', '--mode', 'json', '--no-session', '--no-tools',
                   '--no-lsp', '--no-extensions', '--no-skills', '--no-rules',
                   '--no-title', '--no-prewalk', '--cwd', cwd, '--config', overlay,
                   '--model', self.model, '--system-prompt', str(system_prompt) + '\n',
                   '--append-system-prompt', '']
            # Do not send unsupported effort values to non-reasoning models.
            efforts = capabilities('omp_cli', self.model)['reasoning_efforts']
            effort = self.effort
            if effort not in ('auto', 'off') and efforts and effort not in efforts:
                effort = 'medium' if 'medium' in efforts else efforts[0]
            if effort != 'auto' and (efforts or effort == 'off'):
                cmd.extend(['--thinking', effort])
            result = omp_models.run_cli(cmd, cwd=cwd, env=env, timeout=self.timeout_sec, prompt=prompt)
        if result.returncode:
            self._authentication_failure(result.stderr or '')
            # JSON may contain the authoritative provider error, even on nonzero exit.
            try:
                self._extract_answer(result.stdout)
            except ProviderUnavailableError:
                raise
            except (RuntimeError, ValueError):
                pass
            raise RuntimeError(f'OMP CLI 退出码 {result.returncode}：{self._exit_diagnostic(result.stderr or "")}')
        return self._extract_answer(result.stdout)

    @staticmethod
    def _extract_answer(stdout):
        terminal = None
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                raise ValueError('OMP CLI 返回了无效的 JSON 事件流') from None
            if not isinstance(event, dict):
                raise ValueError('OMP CLI 返回了无效的 JSON 事件')
            if event.get('type') in ('error', 'aborted'):
                diagnostic = event.get('error', event.get('message', ''))
                OmpCliProvider._authentication_failure(str(diagnostic))
                raise RuntimeError('OMP CLI 调用已中止或失败：' + redact_error_message(str(diagnostic), 300))
            if event.get('type') == 'agent_end':
                terminal = event if event.get('isTerminal') is not False and event.get('yielded') is not False else None
        if terminal is None:
            raise RuntimeError('OMP CLI 未返回完整的终止事件')
        messages = terminal.get('messages')
        assistants = [message for message in messages if isinstance(message, dict) and message.get('role') == 'assistant'] if isinstance(messages, list) else []
        if not assistants:
            raise RuntimeError('OMP CLI 未返回最终 assistant 消息')
        message = assistants[-1]
        reason = message.get('stopReason')
        if reason != 'stop':
            diagnostic = str(message.get('errorMessage') or '')
            OmpCliProvider._authentication_failure(diagnostic)
            if reason in ('error', 'aborted'):
                raise RuntimeError(f'OMP CLI 调用失败（{reason}）：{redact_error_message(diagnostic, 300)}')
            raise RuntimeError('OMP CLI 最终响应未正常完成')
        content = message.get('content')
        if not isinstance(content, list):
            raise RuntimeError('OMP CLI 最终消息格式无效')
        if any(isinstance(block, dict) and block.get('type') == 'toolCall' for block in content):
            raise RuntimeError('OMP CLI 在禁用工具时返回了工具调用')
        answer = ''.join(block['text'] for block in content if isinstance(block, dict)
                         and block.get('type') == 'text' and isinstance(block.get('text'), str)).strip()
        if not answer:
            raise RuntimeError('OMP CLI 返回了空的最终响应')
        return answer

    @staticmethod
    def _parse(text, items):
        cleaned = text.strip()
        if cleaned.startswith('```') and cleaned.endswith('```'):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.I)[:-3].strip()
        try:
            parsed = json.loads(cleaned)
        except ValueError:
            raise ValueError('OMP CLI 最终响应不是有效的 JSON 数组') from None
        if not isinstance(parsed, list) or not parsed:
            raise ValueError('OMP CLI 最终响应不是非空的 JSON 数组')
        return reconcile_translation_results(parsed, items)
