"""_translation_failed_completely — detect total translation failure so the
pipeline reports an error instead of a false 'completed'."""
from datetime import timedelta

from app.utils.srt import SubtitleBlock
from app.api.translate import _translation_failed_completely


def _blk(text, translation="", filtered=False, error=""):
    return SubtitleBlock(
        index=1, start=timedelta(0), end=timedelta(seconds=1),
        text=text, translation=translation, filtered=filtered, translation_error=error,
    )


def test_returns_error_when_every_block_failed():
    blocks = [_blk("a", error="auth failed"), _blk("b", error="auth failed")]
    assert _translation_failed_completely(blocks) == "auth failed"


def test_returns_none_when_some_blocks_translated():
    blocks = [_blk("a", translation="甲"), _blk("b", error="x")]
    assert _translation_failed_completely(blocks) is None


def test_returns_none_when_no_translatable_blocks():
    blocks = [_blk("a", filtered=True), _blk("   ")]
    assert _translation_failed_completely(blocks) is None


def test_returns_none_when_empty_without_errors():
    """All-music clip: nothing translated but no error recorded — not a failure."""
    blocks = [_blk("[music]"), _blk("[music]")]
    assert _translation_failed_completely(blocks) is None
