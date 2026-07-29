from copy import deepcopy
from datetime import timedelta
import json

import pytest


def _block(block_id):
    from app.utils.srt import SubtitleBlock

    return SubtitleBlock(
        index=block_id,
        start=timedelta(seconds=block_id),
        end=timedelta(seconds=block_id + 1),
        text=f"source {block_id}",
        translation=f"original {block_id}",
    )


def _issue(block, issue_type="semantic_mismatch", route=""):
    from app.engines.translation_qa import QualityIssue

    return QualityIssue(
        type=issue_type,
        severity="warning" if issue_type == "semantic_uncertain" else "error",
        block_id=block.index,
        message=f"{issue_type} on {block.index}",
        source_text=block.text,
        translation=block.translation,
        resolution_route=route,
    )


def _report(trace, issues):
    from app.engines.translation_qa import TranslationQaReport

    return TranslationQaReport(
        status="needs_review" if issues else "ok",
        issues=list(issues),
        unresolved_blocks=[
            issue.block_id
            for issue in issues
            if isinstance(issue.block_id, int)
        ],
        summary={},
        trace=trace,
    )


def _setup_persist(monkeypatch, saved_reports):
    from app.api import translate as api_translate
    from app.engines import knowledge, translation_qa

    monkeypatch.setattr(
        knowledge,
        "_get_singleton",
        lambda: type(
            "Knowledge",
            (),
            {"select_for_project": lambda self, project: None},
        )(),
    )
    monkeypatch.setattr(
        api_translate,
        "_run_deterministic_translation_normalizers",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        translation_qa,
        "save_quality_report",
        lambda report, **kwargs: saved_reports.append(
            deepcopy(report.to_dict())
        ),
    )


def _state(run_id):
    return {
        "run_id": run_id,
        "semantic_uncertain_observed_block_ids": [],
        "auto_repair_rounds": [
            {"round": number}
            for number in range(1, 4)
        ],
    }


def _disk_state(api_translate, tmp_path, *, cfg=None, block_count=1):
    return api_translate._hydrate_translation_quality_run_state(
        tmp_path,
        run_id="schema-run",
        source_generation_hash="sha256:schema-source",
        configuration_hash="sha256:schema-config",
        block_count=block_count,
        cfg=cfg or {"translation": {"qa_auto_repair": True}},
    )


def _write_disk_state(tmp_path, state):
    (tmp_path / "translation_quality_run_state.json").write_text(
        json.dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )


def _disk_state_from_fresh_path(api_translate, path):
    path.mkdir(parents=True, exist_ok=True)
    return _disk_state(api_translate, path)


def test_quality_run_state_rejects_symlink_without_following_it(
    tmp_path,
):
    from app.api import translate as api_translate

    state = _disk_state(api_translate, tmp_path)
    state_path = tmp_path / "translation_quality_run_state.json"
    target_path = tmp_path / "attacker-controlled.json"
    target_path.write_text(
        json.dumps(state),
        encoding="utf-8",
    )
    state_path.unlink()
    state_path.symlink_to(target_path)

    with pytest.raises(RuntimeError, match="run state"):
        _disk_state(api_translate, tmp_path)

    assert state_path.is_symlink()
    assert json.loads(target_path.read_text(encoding="utf-8")) == state


def test_quality_run_state_rejects_files_larger_than_16_mib(
    tmp_path,
):
    from app.api import translate as api_translate

    state_path = tmp_path / "translation_quality_run_state.json"
    state_path.write_bytes(b" " * ((16 * 1024 * 1024) + 1))

    with pytest.raises(RuntimeError, match="run state"):
        _disk_state(api_translate, tmp_path)

    assert state_path.stat().st_size == (16 * 1024 * 1024) + 1


def test_quality_run_state_sizes_exact_pretty_json_before_atomic_write(
    tmp_path,
):
    from app.api import translate as api_translate

    state = _disk_state(api_translate, tmp_path)
    state["semantic_qa_history"] = [{
        "payload": [0] * 1_530_000,
    }]
    compact_size = len(json.dumps(
        state,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8"))
    pretty_size = len(json.dumps(
        state,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8"))
    assert compact_size < 16 * 1024 * 1024
    assert pretty_size > 16 * 1024 * 1024

    with pytest.raises(RuntimeError, match="oversized"):
        api_translate._persist_translation_quality_run_state(
            tmp_path,
            state,
            block_count=1,
        )

    assert (
        tmp_path / "translation_quality_run_state.json"
    ).stat().st_size <= 16 * 1024 * 1024


def test_stale_in_memory_run_state_resets_through_complete_schema_before_pass(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    block = _block(1)
    stale_state = {
        "schema_version": 1,
        "block_count": 1,
        "run_id": "old-run",
        "source_generation_hash": "sha256:source",
        "configuration_hash": "sha256:config",
        "semantic_uncertain_observed_block_ids": [1],
        "semantic_issue_ledger": {
            "outstanding": [],
            "resolved": [],
        },
        "semantic_qa_history": [{"enabled": True}],
        "auto_repair_rounds": [],
        "auto_repair_budget": {
            "configured_rounds": 3,
            "used_rounds": 0,
            "remaining_rounds": 3,
        },
        "certification_recovery_used": True,
        "seen_blocking_identities": [],
    }
    saved_reports = []
    _setup_persist(monkeypatch, saved_reports)
    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        lambda *args, **kwargs: _report(args[6], []),
    )

    api_translate._persist_translation_quality_report(
        pid="new-run",
        pdir=str(tmp_path),
        project={},
        blocks=[block],
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": False}},
        quality_run_id="new-run",
        quality_run_state=stale_state,
        strict_quality_gate=False,
    )

    persisted = json.loads(
        (
            tmp_path / "translation_quality_run_state.json"
        ).read_text(encoding="utf-8")
    )
    assert stale_state == persisted
    assert persisted["schema_version"] == 1
    assert persisted["block_count"] == 1
    assert persisted["run_id"] == "new-run"
    assert persisted["source_generation_hash"] == "sha256:source"
    assert persisted["configuration_hash"] == "sha256:config"
    assert persisted["certification_recovery_used"] is False
    assert persisted["semantic_uncertain_observed_block_ids"] == []
    assert persisted["semantic_issue_ledger"] == {
        "outstanding": [],
        "resolved": [],
    }


def test_quality_run_state_allows_5001_block_checkpoint_and_hydration(
    tmp_path,
):
    from app.api import translate as api_translate

    state = _disk_state(
        api_translate,
        tmp_path,
        block_count=5001,
    )
    state["semantic_uncertain_observed_block_ids"] = list(
        range(1, 5002)
    )
    api_translate._persist_translation_quality_run_state(
        tmp_path,
        state,
        block_count=5001,
    )

    hydrated = _disk_state(
        api_translate,
        tmp_path,
        block_count=5001,
    )

    assert hydrated["block_count"] == 5001
    assert hydrated["semantic_uncertain_observed_block_ids"] == list(
        range(1, 5002)
    )


def test_quality_run_state_resets_on_block_count_identity_mismatch(
    tmp_path,
):
    from app.api import translate as api_translate

    stale_state = _disk_state(
        api_translate,
        tmp_path,
        block_count=5001,
    )
    stale_state["certification_recovery_used"] = True
    stale_state["semantic_uncertain_observed_block_ids"] = list(
        range(1, 5002)
    )
    api_translate._persist_translation_quality_run_state(
        tmp_path,
        stale_state,
        block_count=5001,
    )

    reset_state = _disk_state(
        api_translate,
        tmp_path,
        block_count=5000,
    )

    assert reset_state["block_count"] == 5000
    assert reset_state["certification_recovery_used"] is False
    assert reset_state["semantic_uncertain_observed_block_ids"] == []


def test_quality_run_state_rejects_invalid_block_count_fail_safe(
    tmp_path,
):
    from app.api import translate as api_translate

    state = _disk_state(
        api_translate,
        tmp_path,
        block_count=5001,
    )
    state["block_count"] = "5001"
    _write_disk_state(tmp_path, state)

    with pytest.raises(RuntimeError, match="block_count"):
        _disk_state(
            api_translate,
            tmp_path,
            block_count=5001,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.pop("schema_version", None),
        lambda state: state.pop("certification_recovery_used", None),
        lambda state: state.update({
            "certification_recovery_used": 1,
        }),
    ],
    ids=["missing-schema", "missing-recovery-flag", "non-bool-recovery-flag"],
)
def test_matching_quality_run_state_rejects_missing_or_invalid_required_fields(
    tmp_path,
    mutation,
):
    from app.api import translate as api_translate

    state = _disk_state(api_translate, tmp_path)
    mutation(state)
    _write_disk_state(tmp_path, state)

    with pytest.raises(RuntimeError, match="run state"):
        _disk_state(api_translate, tmp_path)


@pytest.mark.parametrize(
    "seen_identity",
    [
        ["1", "semantic_mismatch", "sha256:content", ""],
        [0, "semantic_mismatch", "sha256:content", ""],
        [1, {"not": "hashable"}, "sha256:content", ""],
        [1, "semantic_mismatch", ["not", "hashable"], ""],
        [1, "semantic_mismatch", "sha256:content"],
    ],
)
def test_matching_quality_run_state_rejects_invalid_seen_identity(
    tmp_path,
    seen_identity,
):
    from app.api import translate as api_translate

    state = _disk_state(api_translate, tmp_path)
    state["seen_blocking_identities"] = [seen_identity]
    _write_disk_state(tmp_path, state)

    with pytest.raises(RuntimeError, match="run state"):
        _disk_state(api_translate, tmp_path)


@pytest.mark.parametrize(
    "malformed_ledger",
    [
        {"outstanding": "not-a-list", "resolved": []},
        {"outstanding": [], "resolved": {}},
        {"outstanding": [None], "resolved": []},
        {
            "outstanding": [{
                "block_id": "1",
                "content_hash": "sha256:content",
                "type": "semantic_uncertain",
            }],
            "resolved": [],
        },
    ],
)
def test_matching_quality_run_state_rejects_malformed_ledger(
    tmp_path,
    malformed_ledger,
):
    from app.api import translate as api_translate

    state = _disk_state(api_translate, tmp_path)
    state["semantic_issue_ledger"] = malformed_ledger
    _write_disk_state(tmp_path, state)

    with pytest.raises(RuntimeError, match="run state"):
        _disk_state(api_translate, tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "semantic_uncertain_observed_block_ids",
            list(range(1, 5002)),
        ),
        (
            "semantic_qa_history",
            [{} for _ in range(4097)],
        ),
        (
            "auto_repair_rounds",
            [{"round": number} for number in range(1, 5)],
        ),
        (
            "seen_blocking_identities",
            [
                [
                    block_id,
                    "semantic_mismatch",
                    "sha256:content",
                    "",
                ]
                for block_id in range(1, 50002)
            ],
        ),
    ],
)
def test_matching_quality_run_state_rejects_nested_collection_overflow(
    tmp_path,
    field,
    value,
):
    from app.api import translate as api_translate

    state = _disk_state(api_translate, tmp_path)
    state[field] = value
    _write_disk_state(tmp_path, state)

    with pytest.raises(RuntimeError, match="run state"):
        _disk_state(api_translate, tmp_path)


def test_matching_quality_run_state_rejects_ledger_overflow(
    tmp_path,
):
    from app.api import translate as api_translate

    state = _disk_state(api_translate, tmp_path)
    ledger_item = {
        "block_id": 1,
        "content_hash": "sha256:content",
        "type": "semantic_uncertain",
        "severity": "warning",
        "message": "m",
        "source_text": "source",
        "translation": "译文",
        "expected": "",
    }
    state["semantic_issue_ledger"]["outstanding"] = [
        dict(ledger_item, block_id=block_id)
        for block_id in range(1, 15002)
    ]
    _write_disk_state(tmp_path, state)
    with pytest.raises(RuntimeError, match="run state"):
        _disk_state(api_translate, tmp_path)


def test_matching_quality_run_state_rejects_string_overflow(
    tmp_path,
):
    from app.api import translate as api_translate

    state = _disk_state_from_fresh_path(
        api_translate,
        tmp_path,
    )
    state["semantic_qa_history"] = [{"message": "x" * 4097}]
    _write_disk_state(tmp_path, state)
    with pytest.raises(RuntimeError, match="run state"):
        _disk_state(api_translate, tmp_path)


def test_legacy_uncertain_ledger_route_defaults_human_and_cannot_downgrade(
    tmp_path,
):
    from app.api import translate as api_translate

    block = _block(1)
    content_hash = api_translate._semantic_block_content_hash(block)
    state = _disk_state(api_translate, tmp_path)
    state["semantic_issue_ledger"]["outstanding"] = [{
        "block_id": 1,
        "content_hash": content_hash,
        "type": "semantic_uncertain",
        "severity": "warning",
        "message": "legacy uncertainty",
        "source_text": block.text,
        "translation": block.translation,
        "expected": "",
    }]
    _write_disk_state(tmp_path, state)

    hydrated = _disk_state(api_translate, tmp_path)
    assert hydrated["semantic_issue_ledger"]["outstanding"][0][
        "resolution_route"
    ] == "human_context_required"

    report = _report(
        {},
        [_issue(
            block,
            "semantic_uncertain",
            "auto_resolvable",
        )],
    )
    api_translate._update_and_overlay_semantic_issue_ledger(
        report,
        [block],
        hydrated["semantic_issue_ledger"],
        {},
        strict_quality_gate=True,
    )

    assert hydrated["semantic_issue_ledger"]["outstanding"][0][
        "resolution_route"
    ] == "human_context_required"
    assert report.issues[0].resolution_route == "human_context_required"


def test_strict_certification_unions_both_preflights_then_runs_one_final(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    blocks = [_block(1), _block(2)]
    for block in blocks:
        block.text = f"Complete sentence {block.index}."
    by_id = {block.index: block for block in blocks}
    state = _state("strict-union")
    events = []
    repair_scopes = []
    saved_reports = []
    scan = 0
    _setup_persist(monkeypatch, saved_reports)

    def fake_quality(*args, **kwargs):
        nonlocal scan
        scan += 1
        events.append(f"full:{scan}")
        trace = args[6]
        issues = {
            2: [_issue(by_id[1])],
            3: [_issue(by_id[2])],
        }.get(scan, [])
        return _report(trace, issues)

    def fake_repair(*args, **kwargs):
        report = args[3]
        assert state["certification_recovery_used"] is True
        repair_scopes.append([issue.block_id for issue in report.issues])
        events.append("repair")
        changes = []
        for issue in report.issues:
            block = by_id[issue.block_id]
            block.translation = f"repaired {block.index}"
            changes.append({
                "id": block.index,
                "translation": block.translation,
            })
        return api_translate.AutoRepairOutcome(changes, True, True)

    def fake_deterministic(**kwargs):
        events.append("deterministic_guard")
        return _report(kwargs["trace"], [])

    def fake_targeted(*args, **kwargs):
        events.append("targeted_guard")
        candidate_ids = set(args[4])
        return (
            [],
            candidate_ids,
            {
                block_id: api_translate._semantic_block_content_hash(
                    by_id[block_id]
                )
                for block_id in candidate_ids
            },
            [],
        )

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        fake_quality,
    )
    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        fake_repair,
    )
    monkeypatch.setattr(
        api_translate,
        "_run_deterministic_quality_checks",
        fake_deterministic,
    )
    monkeypatch.setattr(
        api_translate,
        "_run_targeted_semantic_verification",
        fake_targeted,
    )

    api_translate._persist_translation_quality_report(
        pid="strict-union",
        pdir=str(tmp_path),
        project={},
        blocks=blocks,
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": True}},
        quality_run_id="strict-union",
        quality_run_state=state,
        strict_quality_gate=True,
    )

    assert repair_scopes == [[1, 2]]
    assert events == [
        "full:1",
        "full:2",
        "full:3",
        "repair",
        "deterministic_guard",
        "targeted_guard",
        "full:4",
    ]
    assert saved_reports[-1]["trace"]["certification_recovery"][
        "new_issue_block_ids"
    ] == [1, 2]


def test_strict_certification_human_route_prevents_same_block_mutation(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    blocks = [_block(1), _block(2)]
    for block in blocks:
        block.text = f"Complete sentence {block.index}."
    by_id = {block.index: block for block in blocks}
    original = {block.index: block.translation for block in blocks}
    state = _state("strict-human-priority")
    saved_reports = []
    repair_scopes = []
    scan = 0
    _setup_persist(monkeypatch, saved_reports)

    def fake_quality(*args, **kwargs):
        nonlocal scan
        scan += 1
        trace = args[6]
        issues = {
            2: [_issue(by_id[1]), _issue(by_id[2])],
            3: [_issue(
                by_id[1],
                "semantic_uncertain",
                "human_context_required",
            )],
            4: [_issue(
                by_id[1],
                "semantic_uncertain",
                "human_context_required",
            )],
        }.get(scan, [])
        return _report(trace, issues)

    def fake_repair(*args, **kwargs):
        report = args[3]
        repair_scopes.append([issue.block_id for issue in report.issues])
        block = by_id[2]
        block.translation = "repaired 2"
        return api_translate.AutoRepairOutcome(
            [{"id": 2, "translation": block.translation}],
            True,
            True,
        )

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        fake_quality,
    )
    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        fake_repair,
    )
    monkeypatch.setattr(
        api_translate,
        "_run_deterministic_quality_checks",
        lambda **kwargs: _report(kwargs["trace"], []),
    )
    monkeypatch.setattr(
        api_translate,
        "_run_targeted_semantic_verification",
        lambda *args, **kwargs: (
            [],
            {2},
            {2: api_translate._semantic_block_content_hash(by_id[2])},
            [],
        ),
    )

    api_translate._persist_translation_quality_report(
        pid="strict-human-priority",
        pdir=str(tmp_path),
        project={},
        blocks=blocks,
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": True}},
        quality_run_id="strict-human-priority",
        quality_run_state=state,
        strict_quality_gate=True,
    )

    assert repair_scopes == [[2]]
    assert by_id[1].translation == original[1]
    assert by_id[2].translation == "repaired 2"
    assert saved_reports[-1]["summary"]["quality_gate"][
        "requires_human_review"
    ] is True


def test_human_routed_uncertainty_never_enters_standard_repair_rounds(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    block = _block(1)
    original = block.translation
    state = {
        "run_id": "strict-human-standard-round",
        "semantic_uncertain_observed_block_ids": [],
        "auto_repair_rounds": [],
    }
    saved_reports = []
    _setup_persist(monkeypatch, saved_reports)

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        lambda *args, **kwargs: _report(
            args[6],
            [_issue(
                block,
                "semantic_uncertain",
                "human_context_required",
            )],
        ),
    )
    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        lambda *args, **kwargs: pytest.fail(
            "human-routed uncertainty must never enter model repair"
        ),
    )

    api_translate._persist_translation_quality_report(
        pid="strict-human-standard-round",
        pdir=str(tmp_path),
        project={},
        blocks=[block],
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": True}},
        quality_run_id="strict-human-standard-round",
        quality_run_state=state,
        strict_quality_gate=True,
    )

    assert block.translation == original
    assert state["certification_recovery_used"] is False
    assert saved_reports[-1]["summary"]["quality_gate"][
        "requires_human_review"
    ] is True


def test_human_routed_member_blocks_its_entire_semantic_repair_group():
    from app.api import translate as api_translate
    from app.engines.translation_qa import QualityIssue, TranslationQaReport
    from app.utils.srt import SubtitleBlock

    blocks = [
        SubtitleBlock(
            index=1,
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text="that maybe you could undo",
            translation="旧译一",
        ),
        SubtitleBlock(
            index=2,
            start=timedelta(seconds=2),
            end=timedelta(seconds=3),
            text="the damage you've done",
            translation="旧译二",
        ),
    ]
    report = TranslationQaReport(
        status="needs_review",
        issues=[
            QualityIssue(
                type="semantic_uncertain",
                severity="warning",
                block_id=1,
                message="scene context required",
                resolution_route="human_context_required",
            ),
            QualityIssue(
                type="semantic_mismatch",
                severity="error",
                block_id=2,
                message="repairable companion",
            ),
        ],
    )

    class Primary:
        def translate_batch(self, items, prompt):
            pytest.fail("a human-owned semantic group must not reach provider")

    outcome = api_translate._auto_repair_quality_issues(
        {"translation": {"qa_auto_repair": True}},
        type("Translator", (), {"primary": Primary()})(),
        blocks,
        report,
        "简体中文",
        None,
    )

    assert outcome.completed is True
    assert outcome.mutation_occurred is False
    assert outcome.changes == []
    assert [block.translation for block in blocks] == ["旧译一", "旧译二"]


def test_strict_certification_consumes_recovery_before_exception_and_resume(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    block = _block(1)
    state = _state("strict-resume")
    saved_reports = []
    repair_calls = 0
    scan = 0
    _setup_persist(monkeypatch, saved_reports)

    def fake_quality(*args, **kwargs):
        nonlocal scan
        scan += 1
        return _report(
            args[6],
            [] if scan == 1 else [_issue(block)],
        )

    def exploding_repair(*args, **kwargs):
        nonlocal repair_calls
        repair_calls += 1
        assert state["certification_recovery_used"] is True
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        fake_quality,
    )
    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        exploding_repair,
    )

    call = lambda: api_translate._persist_translation_quality_report(
        pid="strict-resume",
        pdir=str(tmp_path),
        project={},
        blocks=[block],
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": True}},
        quality_run_id="strict-resume",
        quality_run_state=state,
        strict_quality_gate=True,
    )

    with pytest.raises(RuntimeError, match="translation QA report failed"):
        call()
    assert state["certification_recovery_used"] is True

    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        lambda *args, **kwargs: pytest.fail(
            "recovery must not run again after resume"
        ),
    )
    call()

    assert repair_calls == 1
    assert saved_reports[-1]["trace"]["certification_recovery"]["result"] == (
        "already_used"
    )


def test_strict_final_discovery_never_recurses_and_fast_scan_cost_is_unchanged(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    strict_block = _block(1)
    strict_state = _state("strict-final-bound")
    strict_saved = []
    strict_scans = 0
    repair_calls = []
    _setup_persist(monkeypatch, strict_saved)

    def strict_quality(*args, **kwargs):
        nonlocal strict_scans
        strict_scans += 1
        issues = [_issue(strict_block)] if strict_scans == 4 else []
        return _report(args[6], issues)

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        strict_quality,
    )
    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        lambda *args, **kwargs: repair_calls.append(True),
    )

    api_translate._persist_translation_quality_report(
        pid="strict-final-bound",
        pdir=str(tmp_path),
        project={},
        blocks=[strict_block],
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": True}},
        quality_run_id="strict-final-bound",
        quality_run_state=strict_state,
        strict_quality_gate=True,
    )

    assert strict_scans == 4
    assert repair_calls == []
    assert strict_state["certification_recovery_used"] is False
    assert strict_saved[-1]["summary"]["quality_gate"]["passed"] is False

    fast_block = _block(2)
    fast_saved = []
    fast_scans = 0
    _setup_persist(monkeypatch, fast_saved)

    def fast_quality(*args, **kwargs):
        nonlocal fast_scans
        fast_scans += 1
        return _report(args[6], [])

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        fast_quality,
    )
    api_translate._persist_translation_quality_report(
        pid="fast-cost",
        pdir=str(tmp_path),
        project={},
        blocks=[fast_block],
        target_language="简体中文",
        translator=object(),
        cfg={
            "translation": {
                "qa_auto_repair": False,
                "semantic_qa": True,
            },
        },
        strict_quality_gate=False,
    )

    assert fast_scans == 2


def test_human_uncertainty_route_is_monotonic_across_preflight_and_final(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    block = _block(1)
    block.text = "Complete sentence."
    state = _state("strict-human-monotonic")
    saved_reports = []
    scan = 0
    _setup_persist(monkeypatch, saved_reports)

    def fake_quality(*args, **kwargs):
        nonlocal scan
        scan += 1
        route_by_scan = {
            2: "human_context_required",
            3: "auto_resolvable",
            4: "auto_resolvable",
        }
        route = route_by_scan.get(scan)
        issues = (
            [_issue(block, "semantic_uncertain", route)]
            if route
            else []
        )
        return _report(args[6], issues)

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        fake_quality,
    )
    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        lambda *args, **kwargs: pytest.fail(
            "human-owned identity must never be repaired"
        ),
    )

    api_translate._persist_translation_quality_report(
        pid="strict-human-monotonic",
        pdir=str(tmp_path),
        project={},
        blocks=[block],
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": True}},
        quality_run_id="strict-human-monotonic",
        quality_run_state=state,
        strict_quality_gate=True,
    )

    final_report = saved_reports[-1]
    assert final_report["status"] == "needs_review"
    assert final_report["unresolved_blocks"] == [1]
    assert final_report["summary"]["quality_gate"][
        "requires_human_review"
    ] is True
    assert {
        issue.get("resolution_route")
        for issue in final_report["issues"]
        if issue["type"] == "semantic_uncertain"
    } == {"human_context_required"}


def test_recovery_crash_resumes_from_atomic_disk_state_not_shared_memory(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    block = _block(1)
    block.text = "Complete sentence."
    saved_reports = []
    scan = 0
    repair_calls = 0
    _setup_persist(monkeypatch, saved_reports)

    state_a = api_translate._hydrate_translation_quality_run_state(
        tmp_path,
        run_id="disk-resume",
        source_generation_hash="sha256:source",
        configuration_hash="sha256:config",
        block_count=1,
        cfg={"translation": {"qa_auto_repair": True}},
    )
    state_a["auto_repair_rounds"] = [
        {"round": number}
        for number in range(1, 4)
    ]

    def fake_quality(*args, **kwargs):
        nonlocal scan
        scan += 1
        args[6].setdefault("semantic_qa_history", []).append({
            "enabled": True,
            "coverage_complete": True,
        })
        return _report(
            args[6],
            [] if scan in {1, 4} else [_issue(block)],
        )

    def exploding_repair(*args, **kwargs):
        nonlocal repair_calls
        repair_calls += 1
        disk_state = api_translate._hydrate_translation_quality_run_state(
            tmp_path,
            run_id="disk-resume",
            source_generation_hash="sha256:source",
            configuration_hash="sha256:config",
            block_count=1,
            cfg={"translation": {"qa_auto_repair": True}},
        )
        assert disk_state["certification_recovery_used"] is True
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        fake_quality,
    )
    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        exploding_repair,
    )

    with pytest.raises(RuntimeError, match="translation QA report failed"):
        api_translate._persist_translation_quality_report(
            pid="disk-resume",
            pdir=str(tmp_path),
            project={},
            blocks=[block],
            target_language="简体中文",
            translator=object(),
            cfg={"translation": {"qa_auto_repair": True}},
            quality_run_id="disk-resume",
            quality_run_state=state_a,
            strict_quality_gate=True,
        )

    state_b = api_translate._hydrate_translation_quality_run_state(
        tmp_path,
        run_id="disk-resume",
        source_generation_hash="sha256:source",
        configuration_hash="sha256:config",
        block_count=1,
        cfg={"translation": {"qa_auto_repair": True}},
    )
    assert state_b is not state_a
    assert state_b["certification_recovery_used"] is True
    assert state_b["semantic_issue_ledger"]["outstanding"]
    assert state_b["seen_blocking_identities"]
    assert state_b["semantic_qa_history"]
    assert state_b["auto_repair_budget"]["used_rounds"] == 3

    scan = 0
    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        lambda *args, **kwargs: pytest.fail(
            "disk-hydrated recovery allowance must not run twice"
        ),
    )
    api_translate._persist_translation_quality_report(
        pid="disk-resume",
        pdir=str(tmp_path),
        project={},
        blocks=[block],
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": True}},
        quality_run_id="disk-resume",
        quality_run_state=state_b,
        strict_quality_gate=True,
    )

    assert repair_calls == 1
    assert saved_reports[-1]["trace"]["certification_recovery"][
        "result"
    ] == "already_used"


def test_standard_repair_round_is_consumed_on_disk_before_provider_call(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate

    block = _block(1)
    block.text = "Complete sentence."
    saved_reports = []
    _setup_persist(monkeypatch, saved_reports)
    state_a = api_translate._hydrate_translation_quality_run_state(
        tmp_path,
        run_id="disk-standard-round",
        source_generation_hash="sha256:source",
        configuration_hash="sha256:config",
        block_count=1,
        cfg={"translation": {"qa_auto_repair": True}},
    )

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        lambda *args, **kwargs: _report(
            args[6],
            [_issue(block)],
        ),
    )

    def exploding_repair(*args, **kwargs):
        disk_state = api_translate._hydrate_translation_quality_run_state(
            tmp_path,
            run_id="disk-standard-round",
            source_generation_hash="sha256:source",
            configuration_hash="sha256:config",
            block_count=1,
            cfg={"translation": {"qa_auto_repair": True}},
        )
        assert disk_state["auto_repair_budget"]["used_rounds"] == 1
        assert [
            item["round"]
            for item in disk_state["auto_repair_rounds"]
        ] == [1]
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        exploding_repair,
    )
    call = lambda state: api_translate._persist_translation_quality_report(
        pid="disk-standard-round",
        pdir=str(tmp_path),
        project={},
        blocks=[block],
        target_language="简体中文",
        translator=object(),
        cfg={"translation": {"qa_auto_repair": True}},
        quality_run_id="disk-standard-round",
        quality_run_state=state,
        strict_quality_gate=False,
    )

    with pytest.raises(RuntimeError, match="translation QA report failed"):
        call(state_a)

    state_b = api_translate._hydrate_translation_quality_run_state(
        tmp_path,
        run_id="disk-standard-round",
        source_generation_hash="sha256:source",
        configuration_hash="sha256:config",
        block_count=1,
        cfg={"translation": {"qa_auto_repair": True}},
    )
    assert state_b is not state_a
    assert state_b["auto_repair_budget"]["used_rounds"] == 1

    observed_rounds = []

    def no_op_repair(*args, **kwargs):
        observed_rounds.append(kwargs["repair_trace"]["round"])
        return api_translate.AutoRepairOutcome([], False, True)

    monkeypatch.setattr(
        api_translate,
        "_auto_repair_quality_issues",
        no_op_repair,
    )
    call(state_b)

    assert observed_rounds == [2]
    assert [
        item["round"]
        for item in state_b["auto_repair_rounds"]
    ] == [1, 2]


@pytest.mark.parametrize(
    ("identity_field", "replacement"),
    [
        ("run_id", "other-run"),
        ("source_generation_hash", "sha256:other-source"),
        ("configuration_hash", "sha256:other-config"),
    ],
)
def test_disk_quality_state_resets_on_any_identity_mismatch(
    tmp_path,
    identity_field,
    replacement,
):
    from app.api import translate as api_translate

    expected_identity = {
        "run_id": "identity-run",
        "source_generation_hash": "sha256:source",
        "configuration_hash": "sha256:config",
    }
    stale_state = api_translate._hydrate_translation_quality_run_state(
        tmp_path,
        **expected_identity,
        block_count=1,
        cfg={"translation": {"qa_auto_repair": True}},
    )
    stale_state["certification_recovery_used"] = True
    stale_state["semantic_uncertain_observed_block_ids"] = [9]
    api_translate._persist_translation_quality_run_state(
        tmp_path,
        stale_state,
        block_count=1,
    )

    requested_identity = dict(expected_identity)
    requested_identity[identity_field] = replacement
    reset_state = api_translate._hydrate_translation_quality_run_state(
        tmp_path,
        **requested_identity,
        block_count=1,
        cfg={"translation": {"qa_auto_repair": True}},
    )

    assert reset_state[identity_field] == replacement
    assert reset_state["certification_recovery_used"] is False
    assert reset_state["semantic_uncertain_observed_block_ids"] == []
    assert reset_state["semantic_issue_ledger"] == {
        "outstanding": [],
        "resolved": [],
    }


def test_fast_uncertainty_is_report_only_and_persisted_certificate_is_valid(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate
    from app.utils.translation_quality_gate import validate_quality_report

    block = _block(1)
    block.text = "Complete sentence."
    saved_reports = []
    _setup_persist(monkeypatch, saved_reports)

    def fake_quality(*args, **kwargs):
        trace = args[6]
        trace["semantic_qa"] = {
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
        }
        return _report(
            trace,
            [_issue(
                block,
                "semantic_uncertain",
                "human_context_required",
            )],
        )

    monkeypatch.setattr(
        api_translate,
        "_run_quality_checks_with_semantics",
        fake_quality,
    )

    api_translate._persist_translation_quality_report(
        pid="fast-report-only",
        pdir=str(tmp_path),
        project={},
        blocks=[block],
        target_language="简体中文",
        translator=object(),
        cfg={
            "translation": {
                "qa_auto_repair": False,
                "semantic_qa": True,
            },
        },
        quality_run_id="fast-report-only",
        strict_quality_gate=False,
    )

    final_report = saved_reports[-1]
    decision = validate_quality_report(final_report)
    assert final_report["status"] == "ok"
    assert final_report["unresolved_blocks"] == []
    assert final_report["summary"]["quality_gate"]["passed"] is True
    assert decision.valid is True
    assert decision.passed is True
    assert decision.requires_human_review is False
