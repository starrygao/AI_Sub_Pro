"""Persist the server's outbound proxy separately from its management-page link."""
import os
import threading
from urllib.parse import urlsplit, urlunsplit


_PROXY_ENV = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')


def _validate_url(value, *, dashboard=False):
    label = '管理页面地址' if dashboard else '代理服务器地址'
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError(f'{label}格式不正确')
    value = value.strip()
    if not value:
        return ''
    if any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
        raise ValueError(f'{label}不能包含空白或反斜杠')
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.port == 0:
            raise ValueError
    except ValueError:
        raise ValueError(f'{label}需要完整的 http:// 或 https:// 地址和有效端口') from None
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('此处不保存账号密码；带认证的代理请通过服务器启动配置管理')
    if not dashboard and (parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ValueError('代理地址只填写协议、主机和端口；/ui/ 等管理页面请填在下方')
    return value if dashboard else urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))


def _environment_proxy():
    return next((os.environ[key] for key in ('https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY', 'all_proxy', 'ALL_PROXY')
                 if os.environ.get(key)), '')


def _public_proxy(value):
    # An inherited authenticated endpoint can be shown without returning its secret.
    try:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc.rsplit('@', 1)[-1], '', '', ''))
    except ValueError:
        return ''


class ProxySettings:
    def __init__(self, worker):
        self.worker = worker
        self.lock = threading.RLock()
        saved = worker.store.setting('proxy_url')
        if saved is not None:
            self._install(_validate_url(saved))

    @staticmethod
    def _install(value):
        for key in _PROXY_ENV:
            os.environ.pop(key, None)
        if value:
            os.environ['HTTP_PROXY'] = value
            os.environ['HTTPS_PROXY'] = value
        # Preserve NO_PROXY: local integrations must retain their bypass rules.

    def read(self):
        with self.lock:
            current_url = _environment_proxy()
            pending = self.worker.store.setting('pending_proxy_url')
            dashboard = self.worker.store.setting('proxy_dashboard_url', '')
            current = {'proxy_url': _public_proxy(current_url), 'dashboard_url': dashboard}
            desired = {**current, 'proxy_url': pending if pending is not None else current['proxy_url']}
            return {'current': current, 'desired': desired, 'pending': pending is not None,
                    'source': 'environment' if self.worker.store.setting('proxy_url') is None else 'saved',
                    'credentials_configured': '@' in current_url,
                    'error': self.worker.store.setting('proxy_settings_error', '')}

    def queue(self, data):
        if not isinstance(data, dict) or set(data) - {'proxy_url', 'dashboard_url'}:
            raise ValueError('只能修改代理服务器地址和管理页面地址')
        normalized = {key: _validate_url(value, dashboard=key == 'dashboard_url') for key, value in data.items()}
        with self.lock:
            changes = {'proxy_settings_error': ''}
            if 'proxy_url' in normalized:
                value = normalized['proxy_url']
                changes['pending_proxy_url'] = value if value != _environment_proxy() else None
            if 'dashboard_url' in normalized:
                changes['proxy_dashboard_url'] = normalized['dashboard_url']
            self.worker.store.set_settings(changes)
            self.worker.wake.set()
            return self.read()

    def apply(self):
        from app.services.translation_tasks import run_when_tasks_idle

        def commit():
            with self.lock:
                value = self.worker.store.setting('pending_proxy_url')
                if value is None or self.worker.store.rows(['translating', 'publishing', 'pausing', 'cancelling'], limit=1):
                    return False
                value = _validate_url(value)
                self.worker.store.set_settings({'proxy_url': value, 'pending_proxy_url': None, 'proxy_settings_error': ''})
                self._install(value)
                return True

        return run_when_tasks_idle(commit)
