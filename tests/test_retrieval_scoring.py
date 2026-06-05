def test_ngram_similarity_matches_subtitle_like_variants():
    from app.engines.retrieval_scoring import ngram_similarity

    assert ngram_similarity("I need to go to Hudson Oaks.", "Hudson Oaks is quiet.") > 0.2
    assert ngram_similarity("你还好吗", "你还好吧") > 0.2
    assert ngram_similarity("", "anything") == 0.0


def test_bounded_score_includes_quality_tags_and_priority():
    from app.engines.retrieval_scoring import bounded_retrieval_score

    base = bounded_retrieval_score(
        lexical_score=0.4,
        quality=0.7,
        tag_matches=0,
        priority=0.0,
    )
    boosted = bounded_retrieval_score(
        lexical_score=0.4,
        quality=0.7,
        tag_matches=2,
        priority=0.1,
    )

    assert 0.0 <= base <= 1.0
    assert 0.0 <= boosted <= 1.0
    assert boosted > base


def test_sqlite_fts5_capability_returns_bool(tmp_path):
    from app.engines.retrieval_scoring import sqlite_supports_fts5

    assert isinstance(sqlite_supports_fts5(tmp_path / "fts.sqlite3"), bool)
