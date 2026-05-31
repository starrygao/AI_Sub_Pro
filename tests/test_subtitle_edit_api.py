import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.utils import project_store

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    from app.main import app
    return TestClient(app)


def _seed_project(tmp_project_dir, pid="subedit"):
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "translated",
    }), encoding="utf-8")
    return pid


def test_save_subtitles_requires_existing_project(client):
    r = client.put("/api/projects/missing/subtitles", json={"blocks": []})

    assert r.status_code == 404


def test_save_subtitles_rejects_invalid_time(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 1,
            "start": "not-a-time",
            "end": "00:00:01,000",
            "text": "Hello",
            "translation": "你好",
        }]
    })

    assert r.status_code == 400
    assert "time" in r.json()["detail"]


@pytest.mark.parametrize("field,value", [
    ("start", "00:60:00,000"),
    ("start", "00:00:60,000"),
    ("start", "999999999999999999999999999999:00:00,000"),
    ("end", "00:99:00,000"),
    ("end", "00:00:99,000"),
    ("end", "999999999999999999999999999999:00:00,000"),
])
def test_save_subtitles_rejects_out_of_range_time_parts(client, tmp_project_dir, field, value):
    pid = _seed_project(tmp_project_dir)
    block = {
        "index": 1,
        "start": "00:00:00,000",
        "end": "00:00:01,000",
        "text": "Hello",
        "translation": "你好",
    }
    block[field] = value

    r = client.put(f"/api/projects/{pid}/subtitles", json={"blocks": [block]})

    assert r.status_code == 400
    assert f"invalid {field} time" == r.json()["detail"]


def test_save_subtitles_accepts_long_hour_time(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 1,
            "start": "119:59:59,000",
            "end": "120:00:00,000",
            "text": "Hello",
            "translation": "你好",
        }]
    })

    assert r.status_code == 200


def test_save_subtitles_persists_raw_source_timeline_for_reload(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n",
        encoding="utf-8",
    )

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [
            {
                "index": 1,
                "start": "00:00:00,000",
                "end": "00:00:01,000",
                "text": "Hello",
                "translation": "你好",
            },
            {
                "index": 2,
                "start": "00:00:01,000",
                "end": "00:00:02,000",
                "text": "world",
                "translation": "世界",
            },
        ]
    })
    assert r.status_code == 200

    reload = client.get(f"/api/projects/{pid}/subtitles")

    assert reload.status_code == 200
    body = reload.json()
    assert body["source"] == "raw.srt"
    assert [block["text"] for block in body["blocks"]] == ["Hello", "world"]
    assert [block["translation"] for block in body["blocks"]] == ["你好", "世界"]
    assert "world" in (pdir / "raw.srt").read_text(encoding="utf-8")


def test_save_subtitles_persists_filtered_source_timeline_when_present(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nRaw original\n\n",
        encoding="utf-8",
    )
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nFiltered original\n\n",
        encoding="utf-8",
    )

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [
            {
                "index": 1,
                "start": "00:00:00,000",
                "end": "00:00:01,000",
                "text": "Filtered",
                "translation": "已过滤",
            },
            {
                "index": 2,
                "start": "00:00:01,000",
                "end": "00:00:02,000",
                "text": "timeline",
                "translation": "时间轴",
            },
        ]
    })
    assert r.status_code == 200

    reload = client.get(f"/api/projects/{pid}/subtitles")

    assert reload.status_code == 200
    body = reload.json()
    assert body["source"] == "filtered.srt"
    assert [block["text"] for block in body["blocks"]] == ["Filtered", "timeline"]
    assert [block["translation"] for block in body["blocks"]] == ["已过滤", "时间轴"]
    assert "timeline" in (pdir / "filtered.srt").read_text(encoding="utf-8")


def test_save_subtitles_keeps_translation_only_inserted_rows_reloadable(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [
            {
                "index": 1,
                "start": "00:00:00,000",
                "end": "00:00:01,000",
                "text": "Hello",
                "translation": "你好",
            },
            {
                "index": 2,
                "start": "00:00:01,000",
                "end": "00:00:02,000",
                "text": "",
                "translation": "新增译文行",
            },
        ]
    })
    assert r.status_code == 200

    reload = client.get(f"/api/projects/{pid}/subtitles")

    assert reload.status_code == 200
    blocks = reload.json()["blocks"]
    assert len(blocks) == 2
    assert blocks[1]["translation"] == "新增译文行"


def test_save_subtitles_preserves_raw_filtered_rows_and_filter_state(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nNoise\n\n",
        encoding="utf-8",
    )
    (pdir / "filter_state.json").write_text(json.dumps({
        "2": {"filtered": True, "reason": "ASR噪音"},
    }), encoding="utf-8")

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [
            {
                "index": 1,
                "start": "00:00:00,000",
                "end": "00:00:01,000",
                "text": "Hello edited",
                "translation": "你好",
            },
            {
                "index": 2,
                "start": "00:00:01,000",
                "end": "00:00:02,000",
                "text": "Noise",
                "translation": "",
                "filtered": True,
                "filter_reason": "ASR噪音",
            },
        ]
    })
    assert r.status_code == 200

    reload = client.get(f"/api/projects/{pid}/subtitles")

    assert reload.status_code == 200
    blocks = reload.json()["blocks"]
    assert [block["text"] for block in blocks] == ["Hello edited", "Noise"]
    assert blocks[1]["filtered"] is True
    assert blocks[1]["filter_reason"] == "ASR噪音"
    assert json.loads((pdir / "filter_state.json").read_text(encoding="utf-8")) == {
        "2": {"filtered": True, "reason": "ASR噪音"}
    }


def test_save_subtitles_rejects_non_positive_duration(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 1,
            "start": "00:00:02,000",
            "end": "00:00:01,000",
            "text": "Hello",
            "translation": "你好",
        }]
    })

    assert r.status_code == 400
    assert "end" in r.json()["detail"]


def test_get_subtitles_reports_actual_source_file(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    r = client.get(f"/api/projects/{pid}/subtitles")

    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "raw.srt"
    assert data["blocks"][0]["text"] == "Hello"


def test_get_subtitles_skips_unreadable_source_and_bad_translation(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "filtered.srt").mkdir()
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )
    (pdir / "translated.srt").mkdir()

    r = client.get(f"/api/projects/{pid}/subtitles")

    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "raw.srt"
    assert data["blocks"][0]["text"] == "Hello"
    assert data["blocks"][0]["translation"] == ""


def test_get_subtitles_ignores_malformed_filter_entries_per_block(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )
    (pdir / "filter_state.json").write_text(json.dumps({
        "1": "bad-entry",
        "2": {"filtered": True, "reason": "music"},
    }), encoding="utf-8")

    r = client.get(f"/api/projects/{pid}/subtitles")

    assert r.status_code == 200
    blocks = r.json()["blocks"]
    assert blocks[0]["filtered"] is False
    assert blocks[1]["filtered"] is True
    assert blocks[1]["filter_reason"] == "music"


def test_get_subtitles_does_not_apply_stale_filter_state_to_filtered_srt(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )
    (pdir / "filter_state.json").write_text(json.dumps({
        "2": {"filtered": True, "reason": "old raw index"},
    }), encoding="utf-8")

    r = client.get(f"/api/projects/{pid}/subtitles")

    assert r.status_code == 200
    blocks = r.json()["blocks"]
    assert r.json()["source"] == "filtered.srt"
    assert [block["text"] for block in blocks] == ["Hello", "World"]
    assert all(block["filtered"] is False for block in blocks)


def test_save_subtitles_rejects_non_string_text_fields(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 1,
            "start": "00:00:00,000",
            "end": "00:00:01,000",
            "text": {"bad": "value"},
            "translation": "你好",
        }]
    })

    assert r.status_code == 400
    assert "text" in r.json()["detail"]


def test_save_subtitles_rejects_invalid_index_and_filtered_type(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 0,
            "start": "00:00:00,000",
            "end": "00:00:01,000",
            "text": "Hello",
            "translation": "你好",
        }]
    })
    assert r.status_code == 400
    assert "index" in r.json()["detail"]

    r = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 1,
            "start": "00:00:00,000",
            "end": "00:00:01,000",
            "text": "Hello",
            "translation": "你好",
            "filtered": "false",
        }]
    })
    assert r.status_code == 400
    assert "filtered" in r.json()["detail"]
