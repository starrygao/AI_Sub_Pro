import pytest


def test_base_provider_is_abstract():
    from app.engines.providers.base import BaseProvider
    with pytest.raises(TypeError):
        BaseProvider()


def test_factory_register_and_get():
    from app.engines.providers.base import BaseProvider
    from app.engines.providers.factory import register, get_provider, list_providers, _REGISTRY

    class FakeProvider(BaseProvider):
        def __init__(self, config): self.config = config
        def translate_batch(self, items, system_prompt, retries=3): return []
        def test_connection(self): return True
        @property
        def supports_full_document_mode(self): return False
        @property
        def context_window_tokens(self): return 8000

    _REGISTRY.pop("fake", None)
    register("fake", FakeProvider)
    assert "fake" in list_providers()
    p = get_provider("fake", {"model": "x"})
    assert isinstance(p, FakeProvider)
    assert p.config == {"model": "x"}


def test_factory_unknown_raises():
    from app.engines.providers.factory import get_provider
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("never-registered-xxx", {})
