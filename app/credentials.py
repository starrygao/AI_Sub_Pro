"""OS credential storage, with no plaintext or null-backend fallback."""
import hashlib
import sys


class CredentialError(RuntimeError):
    """A safe, non-secret-bearing storage error."""


class SystemCredentialStore:
    def __init__(self, config_path):
        self.namespace = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:24]
        self._backend = None

    @property
    def backend(self):
        if self._backend is None:
            try:
                if sys.platform == 'darwin':
                    from keyring.backends.macOS import Keyring
                elif sys.platform == 'win32':
                    from keyring.backends.Windows import WinVaultKeyring as Keyring
                else:
                    from keyring.backends.SecretService import Keyring
                self._backend = Keyring()
                if self._backend.priority <= 0:
                    raise RuntimeError('unavailable')
            except Exception:
                raise CredentialError('系统凭证存储不可用，请检查钥匙串或系统凭证服务') from None
        return self._backend

    def _call(self, method, key, *args):
        try:
            return getattr(self.backend, method)('com.aisubpro.credentials', self.namespace + ':' + key, *args)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('系统凭证操作失败，请检查钥匙串权限或解锁状态') from None

    def get(self, key):
        return self._call('get_password', key)

    def set(self, key, value):
        self._call('set_password', key, value)
        if self.get(key) != value:
            raise CredentialError('系统凭证写入验证失败，原配置已保留')

    def delete(self, key):
        if self.get(key) is not None:
            self._call('delete_password', key)
        if self.get(key) is not None:
            raise CredentialError('系统凭证删除验证失败')
