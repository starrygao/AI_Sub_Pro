def test_shared_result_contract_preserves_discourse_link_hashes():
    from app.engines.providers.result_contract import (
        reconcile_translation_results,
    )

    link_hash = "sha256:" + ("a" * 64)
    results = reconcile_translation_results(
        [{
            "id": 86,
            "translation": "OK",
            "verdict": "OK",
            "taxonomy": "none",
            "source_evidence": "My boy?",
            "target_evidence": "我儿子？",
            "discourse_link_hashes": [link_hash],
        }],
        [{"id": 86, "original": "My boy?", "draft": "我儿子？"}],
    )

    assert results[0]["discourse_link_hashes"] == [link_hash]


def test_shared_result_contract_preserves_semantic_resolution_route():
    from app.engines.providers.result_contract import (
        reconcile_translation_results,
    )

    results = reconcile_translation_results(
        [{
            "id": 9,
            "translation": "UNCERTAIN: pronoun needs context",
            "verdict": "UNCERTAIN: pronoun needs context",
            "taxonomy": "entity",
            "source_evidence": "his",
            "target_evidence": "他的",
            "resolution_route": "human_context_required",
        }],
        [{"id": 9, "original": "his", "draft": "他的"}],
    )

    assert results[0]["resolution_route"] == "human_context_required"


def test_provider_instruction_preserves_full_semantic_route_contract():
    from app.engines.providers.result_contract import (
        provider_response_instruction,
    )

    instruction = provider_response_instruction(
        "Return translation verdicts with resolution_route exactly as declared."
    )

    assert "Follow the response contract declared above exactly" in instruction
