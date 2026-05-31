def test_cors_rejects_non_local_web_origins_by_default(monkeypatch):
    monkeypatch.delenv("AISUBPRO_CORS_ORIGINS", raising=False)

    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.options(
        "/api/projects",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_localhost_origins_by_default(monkeypatch):
    monkeypatch.delenv("AISUBPRO_CORS_ORIGINS", raising=False)

    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.options(
        "/api/projects",
        headers={
            "Origin": "http://127.0.0.1:18090",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:18090"


def test_cors_origins_can_be_explicitly_extended(monkeypatch):
    monkeypatch.setenv("AISUBPRO_CORS_ORIGINS", "https://trusted.example, http://app.local")

    import app.main as main

    assert "https://trusted.example" in main._cors_origins()
    assert "http://app.local" in main._cors_origins()
