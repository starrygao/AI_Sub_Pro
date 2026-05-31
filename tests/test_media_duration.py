import pytest


@pytest.mark.parametrize("raw", ["12.5", 12.5])
def test_get_duration_returns_positive_finite_value(monkeypatch, raw):
    from app.utils import media

    monkeypatch.setattr(media, "get_media_info", lambda _path: {"format": {"duration": raw}})

    assert media.get_duration("/tmp/video.mp4") == 12.5


@pytest.mark.parametrize("raw", [
    "N/A",
    -1,
    float("inf"),
    float("-inf"),
    float("nan"),
    pytest.param(10**10000, id="huge-int"),
])
def test_get_duration_rejects_invalid_non_positive_or_non_finite_values(monkeypatch, raw):
    from app.utils import media

    monkeypatch.setattr(media, "get_media_info", lambda _path: {"format": {"duration": raw}})

    assert media.get_duration("/tmp/video.mp4") == 0


@pytest.mark.parametrize("info", [{}, {"format": []}, {"format": None}])
def test_get_duration_rejects_malformed_media_info(monkeypatch, info):
    from app.utils import media

    monkeypatch.setattr(media, "get_media_info", lambda _path: info)

    assert media.get_duration("/tmp/video.mp4") == 0
