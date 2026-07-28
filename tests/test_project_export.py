import json
import threading

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


def _seed_project(tmp_project_dir, pid="exp123"):
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好\n",
        encoding="utf-8",
    )
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "translated",
    }), encoding="utf-8")
    return pid


def _strict_quality_report(verdict="passed", *, warning=False):
    requires_review = verdict == "needs_review"
    failed = verdict == "failed"
    issues = []
    unresolved = []
    observed = []
    if requires_review:
        issues = [{
            "type": "semantic_uncertain",
            "severity": "warning",
            "block_id": 1,
            "message": "meaning is uncertain",
            "source_text": "Maybe.",
            "translation": "也许。",
            "expected": "",
        }]
        unresolved = [1]
        observed = [1]
    elif failed:
        issues = [{
            "type": "semantic_mismatch",
            "severity": "error",
            "block_id": 1,
            "message": "meaning does not match",
            "source_text": "Hello.",
            "translation": "再见。",
            "expected": "",
        }]
        unresolved = [1]
    elif warning:
        issues = [{
            "type": "punctuation_style",
            "severity": "warning",
            "block_id": 1,
            "message": "prefer Chinese punctuation",
            "source_text": "Hello.",
            "translation": "你好.",
            "expected": "Chinese punctuation",
        }]

    passed = verdict == "passed"
    return {
        "run_id": "run-current",
        "content_hash": "sha256:current",
        "status": "ok" if passed else verdict,
        "issues": issues,
        "unresolved_blocks": unresolved,
        "summary": {
            "issue_count": len(issues),
            "error_count": sum(
                issue["severity"] in {"error", "severe"} for issue in issues
            ),
            "warning_count": sum(issue["severity"] == "warning" for issue in issues),
            "unresolved_blocks": len(unresolved),
            "conclusion": (
                "达标：自动检查通过，保留 1 个非阻塞提醒。"
                if warning
                else (
                    "达标：自动检查通过。"
                    if passed
                    else (
                        "需要人工复核。"
                        if requires_review
                        else "自动交付未通过。"
                    )
                )
            ),
            "quality_gate": {
                "policy": "strict",
                "verdict": verdict,
                "passed": passed,
                "delivery_mode": "human_review" if requires_review else "unattended",
                "requires_human_review": requires_review,
                "unresolved_blocks": len(unresolved),
                "next_action": (
                    "deliver"
                    if passed
                    else ("human_review" if requires_review else "auto_retry_or_stop")
                ),
            },
        },
        "trace": {
            "semantic_qa": {
                "enabled": True,
                "requested_blocks": 1,
                "checked_blocks": 1,
                "failed_blocks": 0,
                "skipped_blocks": 0,
                "requested_block_ids": [1],
                "checked_block_ids": [1],
                "failed_block_ids": [],
                "skipped_block_ids": [],
                "coverage_complete": True,
            },
            "semantic_uncertain_observed_block_ids": observed,
        },
    }


def _seed_strict_certification(tmp_project_dir, pid, verdict, *, warning=False):
    _seed_project(tmp_project_dir, pid)
    pdir = tmp_project_dir / pid
    project_path = pdir / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update({
        "translation_quality_policy": "strict",
        "translation_quality_status": (
            "passed" if verdict == "passed" else verdict
        ),
        "translation_quality_run_id": "run-current",
        "translation_quality_content_hash": "sha256:current",
    })
    project_path.write_text(json.dumps(project), encoding="utf-8")
    (pdir / "translation_qa_report.json").write_text(
        json.dumps(_strict_quality_report(verdict, warning=warning)),
        encoding="utf-8",
    )
    return pid


def test_export_rejects_unknown_format(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.post(f"/api/projects/{pid}/export?format=zip")

    assert r.status_code == 400
    assert "format" in r.json()["detail"]


def test_export_rejects_unknown_container(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.post(f"/api/projects/{pid}/export?format=translated&container=ass")

    assert r.status_code == 400
    assert "container" in r.json()["detail"]


def test_export_uses_project_id_when_name_is_missing(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    project.pop("name")
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/export?format=translated")

    assert r.status_code == 200
    assert r.json()["filename"] == f"{pid}.translated.srt"


def test_export_sanitizes_project_name_for_filename(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    project["name"] = "../bad\nmovie"
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/export?format=translated")

    assert r.status_code == 200
    filename = r.json()["filename"]
    assert filename == "bad_movie.translated.srt"
    assert "/" not in filename
    assert "\\" not in filename
    assert "\n" not in filename


def test_export_treats_srt_directories_as_unavailable(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "translated.srt").unlink()
    (pdir / "translated.srt").mkdir()

    r = client.post(f"/api/projects/{pid}/export?format=translated")

    assert r.status_code == 404
    assert "subtitle" in r.json()["detail"].lower()


def test_export_replaces_invalid_utf8_bytes(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "translated.srt").write_bytes(
        b"1\n00:00:00,000 --> 00:00:01,000\nhello \xff\n"
    )

    r = client.post(f"/api/projects/{pid}/export?format=translated")

    assert r.status_code == 200
    assert "hello" in r.json()["content"]
    assert "\ufffd" in r.json()["content"]


def test_export_original_prefers_filtered_editable_timeline(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nRaw original\n\n",
        encoding="utf-8",
    )
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nFiltered editable\n\n",
        encoding="utf-8",
    )

    r = client.post(f"/api/projects/{pid}/export?format=original")

    assert r.status_code == 200
    assert "Filtered editable" in r.json()["content"]
    assert "Raw original" not in r.json()["content"]


def test_export_translated_as_webvtt(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.post(f"/api/projects/{pid}/export?format=translated&container=vtt")

    assert r.status_code == 200
    data = r.json()
    assert data["filename"] == "movie.translated.vtt"
    assert data["content"].startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:01.000" in data["content"]
    assert "你好" in data["content"]
    assert "00:00:00,000" not in data["content"]


def test_export_original_as_webvtt_prefers_filtered_timeline(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "filtered.srt").write_text(
        "1\n00:00:02,000 --> 00:00:03,000\nFiltered original\n\n",
        encoding="utf-8",
    )

    r = client.post(f"/api/projects/{pid}/export?format=original&container=vtt")

    assert r.status_code == 200
    data = r.json()
    assert data["filename"] == "movie.vtt"
    assert "WEBVTT" in data["content"]
    assert "00:00:02.000 --> 00:00:03.000" in data["content"]
    assert "Filtered original" in data["content"]


@pytest.mark.parametrize("format", ["translated", "bilingual"])
def test_export_rejects_translation_delivery_while_sentinel_exists(
    client,
    tmp_project_dir,
    format,
):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "bilingual.srt").write_text("old bilingual", encoding="utf-8")
    (pdir / ".translation_delivery_in_progress").write_text(
        '{"status":"invalid"}',
        encoding="utf-8",
    )

    response = client.post(f"/api/projects/{pid}/export?format={format}")

    assert response.status_code == 409
    assert "delivery" in response.json()["detail"].lower()


def test_export_original_remains_available_while_delivery_sentinel_exists(
    client,
    tmp_project_dir,
):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nSource\n\n",
        encoding="utf-8",
    )
    (pdir / ".translation_delivery_in_progress").write_text(
        '{"status":"invalid"}',
        encoding="utf-8",
    )

    response = client.post(f"/api/projects/{pid}/export?format=original")

    assert response.status_code == 200
    assert "Source" in response.json()["content"]


@pytest.mark.parametrize("verdict", ["failed", "needs_review"])
@pytest.mark.parametrize("format", ["translated", "bilingual"])
def test_export_rejects_strict_failed_or_review_certification(
    client,
    tmp_project_dir,
    verdict,
    format,
):
    pid = _seed_strict_certification(tmp_project_dir, f"strict-{verdict}-{format}", verdict)
    pdir = tmp_project_dir / pid
    (pdir / "bilingual.srt").write_text("source\ntranslation", encoding="utf-8")

    response = client.post(f"/api/projects/{pid}/export?format={format}")

    assert response.status_code == 409
    assert "quality" in response.json()["detail"].lower()


def test_export_original_ignores_failed_strict_translation_certification(
    client,
    tmp_project_dir,
):
    pid = _seed_strict_certification(tmp_project_dir, "strict-original", "failed")
    pdir = tmp_project_dir / pid
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOriginal\n\n",
        encoding="utf-8",
    )

    response = client.post(f"/api/projects/{pid}/export?format=original")

    assert response.status_code == 200
    assert "Original" in response.json()["content"]


def test_export_allows_explicit_fast_policy_without_report(
    client,
    tmp_project_dir,
):
    pid = _seed_project(tmp_project_dir, "fast-no-report")
    project_path = tmp_project_dir / pid / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update({
        "translation_quality_policy": "fast",
        "translation_quality_status": None,
    })
    project_path.write_text(json.dumps(project), encoding="utf-8")

    response = client.post(f"/api/projects/{pid}/export?format=translated")

    assert response.status_code == 200


def test_export_allows_valid_strict_warning_certification_without_server_ack(
    client,
    tmp_project_dir,
):
    pid = _seed_strict_certification(
        tmp_project_dir,
        "strict-warning",
        "passed",
        warning=True,
    )

    response = client.post(f"/api/projects/{pid}/export?format=translated")

    assert response.status_code == 200


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report.update({"status": "failed"}),
        lambda report: report["summary"].pop("quality_gate"),
        lambda report: report.update({"issues": "invalid"}),
    ],
)
def test_export_rejects_malformed_strict_certification(
    client,
    tmp_project_dir,
    mutate,
):
    pid = _seed_strict_certification(tmp_project_dir, "strict-malformed", "passed")
    report_path = tmp_project_dir / pid / "translation_qa_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    mutate(report)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    response = client.post(f"/api/projects/{pid}/export?format=translated")

    assert response.status_code == 409
    assert "quality" in response.json()["detail"].lower()


def test_export_rejects_stale_strict_run_identity(
    client,
    tmp_project_dir,
):
    pid = _seed_strict_certification(tmp_project_dir, "strict-stale", "passed")
    report_path = tmp_project_dir / pid / "translation_qa_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["run_id"] = "run-old"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    response = client.post(f"/api/projects/{pid}/export?format=translated")

    assert response.status_code == 409
    assert "quality" in response.json()["detail"].lower()


@pytest.mark.parametrize("format", ["translated", "bilingual"])
def test_export_rejects_missing_report_while_new_strict_run_is_loading(
    client,
    tmp_project_dir,
    format,
):
    pid = _seed_project(tmp_project_dir, f"strict-loading-{format}")
    pdir = tmp_project_dir / pid
    (pdir / "bilingual.srt").write_text("old bilingual", encoding="utf-8")
    project_path = pdir / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update({
        "status": "processing",
        "pipeline_stage": "translate",
        "translation_quality_policy": "strict",
        "translation_quality_run_id": "run-new",
    })
    project.pop("translation_quality_status", None)
    project_path.write_text(json.dumps(project), encoding="utf-8")

    response = client.post(f"/api/projects/{pid}/export?format={format}")

    assert response.status_code == 409
    assert "quality" in response.json()["detail"].lower()


def test_export_rejects_report_from_substituted_fast_policy(
    client,
    tmp_project_dir,
):
    pid = _seed_strict_certification(
        tmp_project_dir,
        "strict-policy-substitution",
        "passed",
    )
    report_path = tmp_project_dir / pid / "translation_qa_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["summary"]["quality_gate"]["policy"] = "fast"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    response = client.post(f"/api/projects/{pid}/export?format=translated")

    assert response.status_code == 409
    assert "quality" in response.json()["detail"].lower()


@pytest.mark.parametrize("quality_status", ["failed", "needs_review", "stale"])
def test_export_rejects_explicit_non_exportable_project_quality_status(
    client,
    tmp_project_dir,
    quality_status,
):
    pid = _seed_strict_certification(
        tmp_project_dir,
        f"strict-explicit-{quality_status}",
        "passed",
    )
    project_path = tmp_project_dir / pid / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["translation_quality_status"] = quality_status
    project_path.write_text(json.dumps(project), encoding="utf-8")

    response = client.post(f"/api/projects/{pid}/export?format=translated")

    assert response.status_code == 409
    assert "quality" in response.json()["detail"].lower()


def test_put_subtitles_invalidates_strict_certification_before_export(
    client,
    tmp_project_dir,
):
    pid = _seed_strict_certification(tmp_project_dir, "strict-edit-bypass", "passed")
    pdir = tmp_project_dir / pid
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )
    put_response = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 1,
            "start": "00:00:00,000",
            "end": "00:00:01,000",
            "text": "Hello",
            "translation": "编辑后的译文",
        }],
    })
    assert put_response.status_code == 200
    assert put_response.json()["translation_quality_policy"] == "strict"
    assert put_response.json()["translation_quality_status"] == "stale"
    assert "重新运行" in put_response.json()["translation_quality_message"]

    response = client.post(f"/api/projects/{pid}/export?format=translated")

    assert response.status_code == 409
    assert "quality" in response.json()["detail"].lower()


def test_export_cannot_race_strict_subtitle_edit_before_certification_is_stale(
    client,
    tmp_project_dir,
    monkeypatch,
):
    from app.api import projects as projects_api

    pid = _seed_strict_certification(
        tmp_project_dir,
        "strict-edit-export-race",
        "passed",
    )
    pdir = tmp_project_dir / pid
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOld source\n\n",
        encoding="utf-8",
    )
    (pdir / "bilingual.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOld source\n旧译文\n\n",
        encoding="utf-8",
    )

    artifacts_written = threading.Event()
    release_put = threading.Event()
    real_mutate_project = projects_api.mutate_project

    def pause_before_quality_status_update(*args, **kwargs):
        artifacts_written.set()
        if not release_put.wait(timeout=5):
            raise RuntimeError("test timed out waiting to invalidate certification")
        return real_mutate_project(*args, **kwargs)

    monkeypatch.setattr(
        projects_api,
        "mutate_project",
        pause_before_quality_status_update,
    )
    put_result = {}

    def save_edited_subtitles():
        try:
            put_result["response"] = client.put(
                f"/api/projects/{pid}/subtitles",
                json={"blocks": [{
                    "index": 1,
                    "start": "00:00:00,000",
                    "end": "00:00:01,000",
                    "text": "Edited source",
                    "translation": "未经认证的新译文",
                }]},
            )
        except Exception as exc:
            put_result["error"] = exc

    put_thread = threading.Thread(target=save_edited_subtitles)
    put_thread.start()
    try:
        assert artifacts_written.wait(timeout=5)
        assert "未经认证的新译文" in (
            pdir / "translated.srt"
        ).read_text(encoding="utf-8")

        translated = client.post(
            f"/api/projects/{pid}/export?format=translated"
        )
        bilingual = client.post(
            f"/api/projects/{pid}/export?format=bilingual"
        )
        original = client.post(
            f"/api/projects/{pid}/export?format=original"
        )
    finally:
        release_put.set()
        put_thread.join(timeout=5)

    assert not put_thread.is_alive()
    assert "error" not in put_result
    assert translated.status_code == 409
    assert bilingual.status_code == 409
    assert original.status_code == 200
    assert put_result["response"].status_code == 200
    assert (
        put_result["response"].json()["translation_quality_status"]
        == "stale"
    )

    after_put = client.post(
        f"/api/projects/{pid}/export?format=translated"
    )
    assert after_put.status_code == 409
    assert "quality" in after_put.json()["detail"].lower()


def test_quality_report_rejects_stale_mapping_while_delivery_sentinel_exists(
    client,
    tmp_project_dir,
):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "translation_qa_report.json").write_text(
        json.dumps({
            "status": "ok",
            "subtitle_id_mapping": {
                "translated_srt": [{"source_block_id": 7, "output_id": 1}],
            },
        }),
        encoding="utf-8",
    )
    (pdir / ".translation_delivery_in_progress").write_text(
        '{"status":"invalid"}',
        encoding="utf-8",
    )

    response = client.get(f"/api/projects/{pid}/quality-report")

    assert response.status_code == 409
    assert "delivery" in response.json()["detail"].lower()
