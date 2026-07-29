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
