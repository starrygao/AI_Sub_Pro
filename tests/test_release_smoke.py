from app.main import _uvicorn_run_kwargs


def test_headless_smoke_can_use_an_isolated_port(monkeypatch):
    monkeypatch.setenv('AISUBPRO_PORT', '18099')
    assert _uvicorn_run_kwargs('127.0.0.1')['port'] == 18099
