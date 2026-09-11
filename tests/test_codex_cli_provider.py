import json
import subprocess
import signal
from unittest.mock import patch

import pytest


def test_codex_cli_models_include_gpt_5_6_family():
    from app.engines.providers.codex_cli import CODEX_CLI_MODELS

    assert CODEX_CLI_MODELS[:4] == [
        "gpt-6-astra",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert "gpt-5.6" not in CODEX_CLI_MODELS


def test_codex_cli_provider_cli_not_installed():
    from app.engines.providers.codex_cli import CodexCliProvider

    with patch.object(CodexCliProvider, "check_cli_available", return_value=False):
        p = CodexCliProvider({"model": "gpt-5.5"})
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys")

    assert result[0]["translation"] == ""
    assert "未安装" in result[0]["error"] or "not installed" in result[0]["error"].lower()


def test_codex_cli_provider_not_logged_in():
    from app.engines.providers.codex_cli import CodexCliProvider

    with patch.object(CodexCliProvider, "check_cli_available", return_value=True), \
         patch.object(CodexCliProvider, "check_logged_in", return_value=False):
        p = CodexCliProvider({"model": "gpt-5.5"})
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys")

    assert result[0]["translation"] == ""
    assert "登录" in result[0]["error"] or "login" in result[0]["error"].lower() or "auth" in result[0]["error"].lower()


def test_codex_cli_available_probe_treats_oserror_as_unavailable():
    import subprocess
    from app.engines.providers.codex_cli import CodexCliProvider

    with patch.object(subprocess, "run", side_effect=PermissionError("not executable")):
        assert CodexCliProvider.check_cli_available() is False


def test_codex_cli_provider_supports_full_document():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})

    assert p.supports_full_document_mode is True
    assert p.context_window_tokens >= 200_000
    assert p.full_document_max_items == 400


def test_codex_cli_provider_normalizes_bad_timeout():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5", "timeout_sec": "bad"})

    assert p.timeout_sec == 180


def test_codex_cli_provider_normalizes_non_object_and_non_string_model():
    from app.engines.providers.codex_cli import CodexCliProvider

    assert CodexCliProvider(["bad"]).model == "gpt-5.5"
    assert CodexCliProvider({"model": ["bad"]}).model == "gpt-5.5"


def test_codex_cli_provider_passes_explicit_effort_as_isolated_config(monkeypatch):
    from app.engines.providers import codex_cli as codex_mod
    from app.engines.providers.codex_cli import CodexCliProvider

    captured = {}

    class FakeProcess:
        pid = 12345
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return ('[{"id":1,"translation":"ok"}]', "")

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr(codex_mod.subprocess, "Popen", fake_popen)
    provider = CodexCliProvider({"model": "gpt-5.6-sol", "effort": "ultra"})

    provider._invoke([{"id": 1, "original": "hi"}], "system")

    command = captured["cmd"]
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="ultra"'


def test_codex_cli_provider_preserves_caller_declared_semantic_schema(monkeypatch):
    """The CLI wrapper must not narrow a targeted QA schema to two fields."""
    from app.engines.providers import codex_cli as codex_mod
    from app.engines.providers.codex_cli import CodexCliProvider

    captured = {}

    class FakeProcess:
        pid = 12345
        returncode = 0

        def communicate(self, input=None, timeout=None):
            captured["prompt"] = input
            return ("[]", "")

    monkeypatch.setattr(
        codex_mod.subprocess,
        "Popen",
        lambda cmd, **kwargs: FakeProcess(),
    )
    semantic_prompt = (
        "Each result must contain id, translation, verdict, taxonomy, "
        "source_evidence, and target_evidence."
    )

    CodexCliProvider({"model": "gpt-5.6-sol"})._invoke(
        [{"id": 1, "original": "No.", "draft": "不。"}],
        semantic_prompt,
    )

    final_prompt = captured["prompt"]
    assert "source_evidence" in final_prompt
    assert "target_evidence" in final_prompt
    assert "follow the response contract declared above" in final_prompt.lower()
    assert "reply with ONLY a JSON array of {\"id\": N, \"translation\"" not in final_prompt


def test_codex_cli_provider_omits_automatic_or_invalid_effort():
    from app.engines.providers.codex_cli import CodexCliProvider

    assert CodexCliProvider({"model": "gpt-5.6-sol", "effort": "auto"}).effort == "auto"
    assert CodexCliProvider({"model": "gpt-5.6-sol", "effort": "impossible"}).effort == "auto"
    assert CodexCliProvider({"model": "gpt-5.6-luna", "effort": "ultra"}).effort == "auto"
    assert CodexCliProvider({"model": "gpt-5.5", "effort": "max"}).effort == "auto"


def test_codex_cli_provider_parse_response():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]
    text = '[{"id": 1, "translation": "甲"}, {"id": 2, "translation": "乙"}]'

    out = p._parse(text, items)

    assert len(out) == 2
    assert out[0]["translation"] == "甲"
    assert out[1]["translation"] == "乙"


def test_codex_cli_provider_parse_handles_markdown_wrap():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})
    items = [{"id": 1, "original": "a"}]
    text = '```json\n[{"id": 1, "translation": "甲"}]\n```'

    out = p._parse(text, items)

    assert out[0]["translation"] == "甲"


def test_codex_cli_provider_parse_preserves_targeted_semantic_fields():
    from app.engines.providers.codex_cli import CodexCliProvider

    items = [{"id": 1, "original": "No.", "draft": "不。"}]
    text = (
        '[{"id":1,"translation":"OK","verdict":"OK","taxonomy":"none",'
        '"source_evidence":"No.","target_evidence":"不。",'
        '"untrusted_extra":"must not pass through"}]'
    )

    out = CodexCliProvider._parse(text, items)

    assert out == [{
        "id": 1,
        "translation": "OK",
        "error": "",
        "verdict": "OK",
        "taxonomy": "none",
        "source_evidence": "No.",
        "target_evidence": "不。",
    }]


def test_codex_cli_provider_real_parse_preserves_discourse_link_hashes():
    from app.engines.providers.codex_cli import CodexCliProvider

    link_hash = "sha256:" + ("b" * 64)
    text = json.dumps([{
        "id": 86,
        "translation": "OK",
        "verdict": "OK",
        "taxonomy": "none",
        "source_evidence": "My boy?",
        "target_evidence": "我儿子？",
        "discourse_link_hashes": [link_hash],
    }], ensure_ascii=False)

    parsed = CodexCliProvider._parse(
        text,
        [{"id": 86, "original": "My boy?", "draft": "我儿子？"}],
    )

    assert parsed[0]["discourse_link_hashes"] == [link_hash]


def test_codex_cli_provider_parse_preserves_group_semantic_bindings():
    """Provider normalization must not strip group ids or the bound hash."""
    from app.engines.providers.codex_cli import CodexCliProvider

    group_hash = "sha256:" + ("a" * 64)
    items = [{
        "id": 396,
        "group_ids": [396, 397],
        "group_content_hash": group_hash,
    }]
    text = json.dumps([{
        "id": 396,
        "translation": "OK",
        "verdict": "OK",
        "taxonomy": "none",
        "group_ids": [396, 397],
        "group_content_hash": group_hash,
        "source_evidence": [
            {"id": 396, "text": "people stupid enough"},
            {"id": 397, "text": "to have hope"},
        ],
        "target_evidence": [
            {"id": 396, "text": "你难道还没明白"},
            {"id": 397, "text": "心存希望的人"},
        ],
        "untrusted_extra": "must not pass through",
    }])

    out = CodexCliProvider._parse(text, items)

    assert out == [{
        "id": 396,
        "translation": "OK",
        "error": "",
        "verdict": "OK",
        "taxonomy": "none",
        "group_ids": [396, 397],
        "group_content_hash": group_hash,
        "source_evidence": [
            {"id": 396, "text": "people stupid enough"},
            {"id": 397, "text": "to have hope"},
        ],
        "target_evidence": [
            {"id": 396, "text": "你难道还没明白"},
            {"id": 397, "text": "心存希望的人"},
        ],
    }]


def test_codex_cli_provider_parse_preserves_cross_block_group_evidence():
    from app.engines.providers.codex_cli import CodexCliProvider

    group_hash = "sha256:" + ("a" * 64)
    raw = json.dumps([{
        "id": 396,
        "translation": "MISMATCH: clause moved across cues",
        "verdict": "MISMATCH: clause moved across cues",
        "taxonomy": "cross_block_alignment",
        "group_ids": [396, 397],
        "group_content_hash": group_hash,
        "source_evidence": [
            {"id": 396, "text": "what happens"},
            {"id": 397, "text": "to people"},
        ],
        "target_evidence": [
            {"id": 396, "text": "在这个世界上"},
            {"id": 397, "text": "下场吗"},
        ],
        "cross_block_evidence": [{
            "source": {"id": 396, "text": "what happens"},
            "target": {"id": 397, "text": "下场吗"},
        }],
    }], ensure_ascii=False)

    parsed = CodexCliProvider._parse(raw, [{"id": 396}])

    assert parsed[0]["cross_block_evidence"] == [{
        "source": {"id": 396, "text": "what happens"},
        "target": {"id": 397, "text": "下场吗"},
    }]


def test_codex_cli_provider_parse_rejects_targeted_result_without_translation():
    from app.engines.providers.codex_cli import CodexCliProvider

    items = [{"id": 1, "original": "No.", "draft": "不。"}]
    text = (
        '[{"id":1,"verdict":"OK","taxonomy":"none",'
        '"source_evidence":"No.","target_evidence":"不。"}]'
    )

    out = CodexCliProvider._parse(text, items)

    assert out == [{
        "id": 1,
        "translation": "",
        "error": "missing translation in model response",
    }]


@pytest.mark.parametrize(
    ("text", "error_fragment"),
    [
        (
            '[{"id":1,"translation":"first"},'
            '{"id":1,"translation":"second"}]',
            "duplicate",
        ),
        (
            '[{"id":1,"translation":"甲"},'
            '{"id":999,"translation":"额外"}]',
            "unexpected",
        ),
        (
            '[{"id":1,"translation":"甲"},"not an object"]',
            "invalid",
        ),
    ],
)
def test_codex_cli_provider_parse_fails_entire_batch_on_invalid_result_shape(
    text,
    error_fragment,
):
    from app.engines.providers.codex_cli import CodexCliProvider

    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]

    out = CodexCliProvider._parse(text, items)

    assert [item["id"] for item in out] == [1, 2]
    assert all(item["translation"] == "" for item in out)
    assert all(error_fragment in item["error"] for item in out)


def test_codex_cli_provider_redacts_cli_error_secrets():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})
    raw_error = "codex failed api_key=secret123 Authorization: Bearer token123"
    with patch.object(CodexCliProvider, "check_cli_available", return_value=True), \
         patch.object(CodexCliProvider, "check_logged_in", return_value=True), \
         patch.object(p, "_invoke", side_effect=RuntimeError(raw_error)):
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys", retries=1)

    error = result[0]["error"]
    assert "secret123" not in error
    assert "token123" not in error
    assert "api_key=<redacted>" in error
    assert "Authorization: <redacted>" in error


def test_codex_cli_provider_kills_process_group_on_timeout(monkeypatch):
    from app.engines.providers import codex_cli as codex_mod
    from app.engines.providers.codex_cli import CodexCliProvider

    class FakeProcess:
        pid = 12345
        returncode = None

        def communicate(self, input=None, timeout=None):
            raise subprocess.TimeoutExpired(["codex"], timeout)

        def wait(self, timeout=None):
            self.returncode = -signal.SIGTERM

        def kill(self):
            self.returncode = -signal.SIGKILL

    killed = []
    fake_process = FakeProcess()

    def fake_popen(cmd, **kwargs):
        assert "--ignore-user-config" in cmd
        assert kwargs.get("start_new_session") is True
        return fake_process

    monkeypatch.setattr(codex_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        codex_mod.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("use Popen for cancellable invocation")),
    )
    monkeypatch.setattr(codex_mod.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    p = CodexCliProvider({"model": "gpt-5.5", "timeout_sec": 5})

    with pytest.raises(subprocess.TimeoutExpired):
        p._invoke([{"id": 1, "original": "hi"}], "sys")

    assert killed == [(12345, signal.SIGTERM)]
