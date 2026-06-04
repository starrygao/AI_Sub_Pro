from unittest.mock import patch
import json
from datetime import timedelta


def test_emit_progress_routes_through_scheduler():
    """_emit_progress must delegate to scheduler.update_progress (single source of truth).

    Patch the local alias bound at import time, not the source symbol — translate.py does
    ``from app.engines.scheduler import update_progress as _scheduler_update_progress``
    so patching the origin doesn't rebind already-imported callers.
    """
    from app.api import translate as api_translate
    with patch.object(api_translate, "_scheduler_update_progress") as mock_update:
        api_translate._emit_progress("pidx", stage="asr", local_pct=10, msg="m")
    mock_update.assert_called_once_with("pidx", stage="asr", local_pct=10, msg="m")


def test_translate_module_reexports_scheduler_progress_store():
    """Compatibility import must still expose scheduler's progress_store."""
    from app.api.translate import progress_store as from_translate
    from app.engines.scheduler import progress_store as from_scheduler
    assert from_translate is from_scheduler


def test_translate_pipeline_ignores_malformed_filter_entries_per_block(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trans001"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "tmdb_id": 123,
        "tmdb_type": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
    }), encoding="utf-8")
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )
    (pdir / "filter_state.json").write_text(json.dumps({
        "1": "bad-entry",
        "2": {"filtered": True, "reason": "music"},
    }), encoding="utf-8")

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    seen = {}

    class FakeTranslator:
        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            seen["meta_info"] = meta_info
            for block in blocks:
                if not block.filtered:
                    block.translation = f"zh-{block.index}"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"
    assert seen["meta_info"]["name"] == "movie"
    assert seen["meta_info"]["tmdb_id"] == 123
    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    assert "zh-1" in translated
    assert "zh-2" not in translated


def test_translate_pipeline_does_not_apply_stale_filter_state_to_filtered_srt(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trans004"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )
    (pdir / "filter_state.json").write_text(json.dumps({
        "2": {"filtered": True, "reason": "old raw index"},
    }), encoding="utf-8")

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            for block in blocks:
                if not block.filtered:
                    block.translation = f"zh-{block.index}"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    assert "zh-1" in translated
    assert "zh-2" in translated


def test_translate_pipeline_tolerates_malformed_progress_callback_values(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trans002"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            if callback:
                callback(float("inf"), {"bad": "shape"})
            blocks[0].translation = "你好"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"


def test_translate_pipeline_writes_quality_report(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transqa"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nAre you okay?\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "你好"
            blocks[1].translation = "Are you okay?"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "needs_review"
    assert report["summary"]["by_type"]["english_residue"] == 1
    assert (pdir / "translation_qa_report.md").exists()


def test_translate_pipeline_can_auto_repair_quality_issues(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transrepair"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nAre you okay?\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": True},
    })

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            assert items == [{"id": 1, "original": "Are you okay?", "draft": "Are you okay?"}]
            assert "Are you okay?" in system_prompt
            return [{"id": 1, "translation": "你还好吗？"}]

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "Are you okay?"
            return blocks

        def _apply_results(self, blocks, results):
            for block in blocks:
                for result in results:
                    if str(result.get("id")) == str(block.index):
                        block.translation = result.get("translation", "")

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert "你还好吗？" in translated
    assert report["status"] == "ok"
    assert report["repaired_blocks"] == [{"id": 1, "translation": "你还好吗？"}]


def test_translate_pipeline_redacts_exception_details_in_project_error(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trans003"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        def __init__(self, cfg):
            pass

        def translate(self, *args, **kwargs):
            raise RuntimeError("provider failed api_key=secret123 sk-live-secret-token")

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "error"
    assert "secret123" not in project["error"]
    assert "sk-live-secret-token" not in project["error"]
    assert "api_key=<redacted>" in project["error"]
    assert "sk-<redacted>" in project["error"]


def test_asr_pipeline_writes_filter_state_with_atomic_json(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store
    from app.utils.srt import SubtitleBlock

    pid = "asr001"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "created",
        "selected_audio_track": 0,
    }), encoding="utf-8")

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "asr": {"language": "auto", "model_size": "tiny", "vad_filter": False, "beam_size": 1},
        "translation": {},
    })
    monkeypatch.setattr(api_translate, "_emit_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_translate, "_check_cancel", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_translate, "_try_bypass_asr_with_embedded_subtitle", lambda *args, **kwargs: False)
    monkeypatch.setattr("app.engines.audio.preprocess_audio", lambda *args, **kwargs: str(pdir / "audio.wav"))

    def fake_transcribe(*args, **kwargs):
        return [SubtitleBlock(
            index=1,
            start=timedelta(seconds=0),
            end=timedelta(seconds=1),
            text="noise",
        )]

    def fake_filter(blocks, **kwargs):
        blocks[0].filtered = True
        blocks[0].filter_reason = "ASR噪音"
        return blocks

    writes = []

    def fake_atomic_write_json(path, data):
        writes.append((path, data))

    monkeypatch.setattr("app.engines.asr.transcribe", fake_transcribe)
    monkeypatch.setattr("app.engines.filter.filter_subtitles", fake_filter)
    monkeypatch.setattr("app.engines.filter.get_filter_stats", lambda blocks: {"active": 0, "filtered": 1})
    monkeypatch.setattr(api_translate, "atomic_write_json", fake_atomic_write_json)

    api_translate._run_asr_pipeline(pid, audio_track=0, language="auto", owns_registration=False)

    assert writes == [
        (pdir / "filter_state.json", {"1": {"filtered": True, "reason": "ASR噪音"}})
    ]
