import copy

import pytest


def _base_project():
    return {
        "id": "cfg-hash",
        "name": "Dead City S03E01",
        "target_language": "简体中文",
        "manual_terms": "tank=储罐\nMira=听着",
        "content_type": "tv_drama",
        "academic_field": "",
        "content_notes": "post-apocalyptic drama",
        "metadata_source": "manual",
        "show_title": "Dead City",
        "tmdb_id": 123,
        "original_language": "en",
    }


def _base_config():
    return {
        "translation": {
            "quality_mode": "professional",
            "primary_provider": "codex_cli",
            "primary_model": "gpt-5.6-sol",
            "primary_effort": "high",
            "review_provider": "omp_cli",
            "review_model": "review-model",
            "review_effort": "xhigh",
            "qa_auto_repair": True,
            "semantic_qa": True,
        },
    }


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("project", "target_language", "English"),
        ("project", "manual_terms", "tank=坦克"),
        ("project", "content_type", "documentary"),
        ("project", "academic_field", "chemistry"),
        ("project", "content_notes", "different editorial context"),
        ("config", "quality_mode", "fast"),
        ("config", "primary_model", "different-model"),
        ("config", "review_provider", "openai"),
        ("config", "review_model", "another-review-model"),
        ("config", "review_effort", "medium"),
    ],
)
def test_translation_configuration_hash_binds_semantic_inputs(
    section,
    field,
    value,
):
    """Catches certifying output after a translation-affecting input changed."""
    from app.utils.translation_configuration import (
        translation_configuration_hash,
    )

    project = _base_project()
    config = _base_config()
    before = translation_configuration_hash(
        project,
        config=config,
        effective_kb={"version": 2, "characters": []},
        candidate_terms=[{"source": "Mira", "target": "听着"}],
    )
    changed_project = copy.deepcopy(project)
    changed_config = copy.deepcopy(config)
    if section == "project":
        changed_project[field] = value
    else:
        changed_config["translation"][field] = value

    after = translation_configuration_hash(
        changed_project,
        config=changed_config,
        effective_kb={"version": 2, "characters": []},
        candidate_terms=[{"source": "Mira", "target": "听着"}],
    )

    assert before.startswith("sha256:")
    assert after.startswith("sha256:")
    assert before != after


def test_translation_configuration_hash_binds_effective_kb_and_version():
    """Catches reusing certification after the selected terminology changed."""
    from app.utils.translation_configuration import (
        translation_configuration_hash,
    )

    project = _base_project()
    config = _base_config()
    first = translation_configuration_hash(
        project,
        config=config,
        effective_kb={
            "schema_version": 2,
            "characters": [{"source": "Hershel", "target": "赫歇尔"}],
        },
        candidate_terms=[],
    )
    changed_term = translation_configuration_hash(
        project,
        config=config,
        effective_kb={
            "schema_version": 2,
            "characters": [{"source": "Hershel", "target": "赫谢尔"}],
        },
        candidate_terms=[],
    )
    changed_version = translation_configuration_hash(
        project,
        config=config,
        effective_kb={
            "schema_version": 3,
            "characters": [{"source": "Hershel", "target": "赫歇尔"}],
        },
        candidate_terms=[],
    )

    assert len({first, changed_term, changed_version}) == 3

