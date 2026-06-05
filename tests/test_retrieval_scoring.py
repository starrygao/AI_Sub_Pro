import math


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


def test_clamp_allows_positional_bounds():
    from app.engines.retrieval_scoring import clamp

    assert clamp(2, 0, 1) == 1
    assert clamp(-1, 0, 1) == 0


def test_clamp_treats_non_finite_values_as_low_bound():
    from app.engines.retrieval_scoring import clamp

    assert clamp(float("nan")) == 0
    assert clamp(math.inf) == 0
    assert clamp(-math.inf, -1, 1) == -1


def test_bounded_score_safely_defaults_malformed_numeric_inputs():
    from app.engines.retrieval_scoring import bounded_retrieval_score

    score = bounded_retrieval_score(
        lexical_score=None,
        quality="not-a-score",
        tag_matches="many",
        priority={"invalid": True},
        recency_boost="recent",
        usage_boost=None,
    )

    assert score == 0.08
    assert 0.0 <= score <= 1.0


def test_bounded_score_caps_tag_matches_and_boosts():
    from app.engines.retrieval_scoring import bounded_retrieval_score

    tag_cap = bounded_retrieval_score(lexical_score=0, quality=0, tag_matches=999)
    boost_cap = bounded_retrieval_score(
        lexical_score=0,
        quality=0,
        recency_boost=999,
        usage_boost=999,
    )

    assert tag_cap == 0.10
    assert boost_cap == 0.08
    assert bounded_retrieval_score(lexical_score=0, quality=0, tag_matches=-5) == 0.0


def test_sqlite_fts5_capability_returns_bool(tmp_path):
    from app.engines.retrieval_scoring import sqlite_supports_fts5

    assert isinstance(sqlite_supports_fts5(tmp_path / "fts.sqlite3"), bool)


def test_sqlite_fts5_probe_does_not_create_requested_path(tmp_path):
    from app.engines.retrieval_scoring import sqlite_supports_fts5

    db_path = tmp_path / "missing-parent" / "fts.sqlite3"

    assert isinstance(sqlite_supports_fts5(db_path), bool)
    assert not db_path.exists()
    assert not db_path.parent.exists()
