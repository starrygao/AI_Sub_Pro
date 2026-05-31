from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_headless_server_binds_localhost_by_default(monkeypatch):
    from app import main

    monkeypatch.delenv("AISUBPRO_HOST", raising=False)

    assert main._headless_host() == "127.0.0.1"


def test_headless_server_host_requires_explicit_override(monkeypatch):
    from app import main

    monkeypatch.setenv("AISUBPRO_HOST", "0.0.0.0")

    assert main._headless_host() == "0.0.0.0"


def test_uvicorn_run_kwargs_include_graceful_shutdown_timeout(monkeypatch):
    from app import main

    monkeypatch.delenv("AISUBPRO_GRACEFUL_SHUTDOWN_TIMEOUT", raising=False)

    kwargs = main._uvicorn_run_kwargs("127.0.0.1")

    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 18090
    assert kwargs["ws"] == "websockets-sansio"
    assert kwargs["timeout_graceful_shutdown"] == 3


def test_uvicorn_graceful_shutdown_timeout_can_be_overridden(monkeypatch):
    from app import main

    monkeypatch.setenv("AISUBPRO_GRACEFUL_SHUTDOWN_TIMEOUT", "8")

    assert main._uvicorn_run_kwargs("127.0.0.1")["timeout_graceful_shutdown"] == 8


def test_log_dir_defaults_to_user_data_dir(tmp_path, monkeypatch):
    from app import main

    monkeypatch.delenv("AI_SUB_PRO_DATA_DIR", raising=False)
    monkeypatch.setattr(main.Path, "home", lambda: tmp_path)

    assert main._log_dir_for_env() == tmp_path / "AI_Sub_Pro_Data"


def test_log_dir_honors_runtime_data_dir_env(tmp_path, monkeypatch):
    from app import main

    runtime_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("AI_SUB_PRO_DATA_DIR", str(runtime_dir))

    assert main._log_dir_for_env() == runtime_dir


def test_local_server_ready_uses_loopback_health_check(monkeypatch):
    from app import main

    calls = []

    class Response:
        status = 200

        def close(self):
            pass

    def fake_urlopen(url, timeout):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert main._local_server_ready(timeout=0.25) is True
    assert calls == [("http://127.0.0.1:18090/", 0.25)]


def test_local_server_ready_returns_false_on_probe_error(monkeypatch):
    from app import main

    def fake_urlopen(url, timeout):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert main._local_server_ready(timeout=0.25) is False


def test_app_startup_uses_lifespan_instead_of_deprecated_on_event():
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")

    assert "lifespan=lifespan" in source
    assert "@app.on_event(\"startup\")" not in source


def test_desktop_entrypoint_does_not_open_window_before_server_is_ready():
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")

    assert "server_thread = None" in source
    assert "server_ready = _local_server_ready()" in source
    assert "if not server_ready:" in source
    assert "sys.exit(1)" in source
    assert source.index("if not server_ready:") < source.index("webview.create_window")
