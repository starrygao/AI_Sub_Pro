"""Source-bound draft recovery; restored text must pass fresh QA before delivery."""
import copy
import hashlib
import json
import logging
from pathlib import Path

from app.utils.project_store import atomic_write_json
from app.utils.srt import parse_srt_file, _subtitle_text
from app.utils.subtitle_generation import subtitle_source_generation_hash

log = logging.getLogger(__name__)
CHECKPOINT_NAME = 'translation_checkpoint.json'


def _digest(rows):
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _identity(row):
    return tuple(row.get(k) for k in ('index', 'start_ms', 'end_ms', 'text', 'filtered', 'filter_reason'))


def _read_json(path):
    if path.is_symlink() or not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    return value if isinstance(value, dict) else {}


def save_translation_checkpoint(pdir, blocks, source_hash, configuration_hash):
    pdir = Path(pdir)
    if not source_hash or not configuration_hash:
        return
    if subtitle_source_generation_hash(pdir) != source_hash:
        raise RuntimeError('Subtitle source changed while saving translation checkpoint')
    path = pdir / CHECKPOINT_NAME
    if path.is_symlink():
        raise RuntimeError('Refusing a symlink translation checkpoint')
    atomic_write_json(path, translation_checkpoint_payload(blocks, source_hash, configuration_hash))


def translation_checkpoint_payload(blocks, source_hash, configuration_hash):
    """Prepare a draft to join an already locked subtitle publication."""
    rows = [b.to_dict() for b in blocks]
    return {'schema_version': 1, 'source_generation_hash': source_hash,
            'configuration_hash': configuration_hash, 'blocks': rows,
            'blocks_hash': _digest(rows)}


def _legacy_drafts(pdir, blocks, source_hash, configuration_hash):
    """Old SRTs lack a checkpoint. Match both tracks to the exact source.

    Old content hashes predate SRT line wrapping, so cannot certify exported
    text. These are recovered ONLY as drafts, never as a quality verdict.
    """
    report = _read_json(pdir / 'translation_qa_report.json')
    if (report.get('source_generation_hash') != source_hash
            or report.get('configuration_hash') != configuration_hash):
        return []
    mono, bilingual = (pdir / name for name in ('partial_translated.srt', 'partial_bilingual.srt'))
    if any(p.is_symlink() or not p.is_file() for p in (mono, bilingual)):
        return []
    translated = parse_srt_file(str(mono))
    paired = parse_srt_file(str(bilingual))
    def indexed(rows):
        result = {(b.start, b.end): b for b in rows}
        if len(result) != len(rows):
            raise ValueError('Ambiguous subtitle timestamps')
        return result
    sources, targets, pairs = indexed(blocks), indexed(translated), indexed(paired)
    if not targets or set(targets) - set(sources) or set(pairs) - set(sources):
        return []
    drafts = copy.deepcopy(blocks)
    # Sound-only bilingual entries from the old writer may have no target.
    for key, target in targets.items():
        source = sources[key]
        pair = pairs.get(key)
        expected = _subtitle_text(
            target.text, is_translation=True, source_text=source.text, bilingual=True,
        ) + '\n' + _subtitle_text(source.text, bilingual=True)
        if pair is None or pair.text != expected:
            return []
    for block in drafts:
        target = targets.get((block.start, block.end))
        block.translation = target.text if target is not None else ''
    return [b.to_dict() for b in drafts]


def restore_translation_checkpoint(pdir, blocks, source_hash, configuration_hash):
    pdir = Path(pdir)
    if (not source_hash or not configuration_hash
            or subtitle_source_generation_hash(pdir) != source_hash):
        return 0
    try:
        path = pdir / CHECKPOINT_NAME
        if path.exists() or path.is_symlink():
            saved = _read_json(path)
            if (saved.get('schema_version') != 1
                    or saved.get('source_generation_hash') != source_hash
                    or saved.get('configuration_hash') != configuration_hash):
                return 0
            rows = saved.get('blocks')
            if not isinstance(rows, list) or _digest(rows) != saved.get('blocks_hash'):
                return 0
        else:
            rows = _legacy_drafts(pdir, blocks, source_hash, configuration_hash)
        current = [b.to_dict() for b in blocks]
        if (len(rows) != len(current) or any(not isinstance(r, dict) for r in rows)
                or [_identity(r) for r in rows] != [_identity(r) for r in current]
                or len({b.index for b in blocks}) != len(blocks)):
            return 0
        count = 0
        for block, row in zip(blocks, rows):
            text = row.get('translation')
            if not block.filtered and isinstance(text, str) and text.strip():
                block.translation = text
                block.translation_error = ''
                count += 1
        return count
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        log.warning('Draft recovery rejected invalid or incompatible artifacts for %s', pdir.name)
        return 0


def migrate_legacy_translation_checkpoint(pdir):
    """Preserve verified legacy drafts before a new run invalidates its report."""
    pdir = Path(pdir)
    path = pdir / CHECKPOINT_NAME
    if path.exists() or path.is_symlink():
        return
    try:
        source = pdir / 'filtered.srt'
        if source.is_symlink() or not source.is_file():
            return
        report = _read_json(pdir / 'translation_qa_report.json')
        source_hash = report.get('source_generation_hash')
        config_hash = report.get('configuration_hash')
        if not isinstance(source_hash, str) or not isinstance(config_hash, str):
            return
        blocks = parse_srt_file(str(source))
        if restore_translation_checkpoint(pdir, blocks, source_hash, config_hash):
            save_translation_checkpoint(pdir, blocks, source_hash, config_hash)
    except (OSError, ValueError, TypeError, RuntimeError):
        log.warning('Legacy draft migration skipped invalid artifacts for %s', pdir.name)
