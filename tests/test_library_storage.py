import json
from pathlib import Path

import pytest

from app.library.storage import StoragePaths


def storage(tmp_path):
    root = tmp_path / 'storage'; root.mkdir()
    result = StoragePaths(root, '/vol2/aisub', tmp_path / 'links')
    result.initialize()
    return result


def test_migration_copies_all_data_and_keeps_original_and_stable_links(tmp_path):
    manager = storage(tmp_path)
    (manager.root / 'data' / 'knowledge.json').write_text('{"preserved":true}')
    manager.configure_links()
    desired = dict(manager.state()['current'], data='/vol2/aisub/new-data', temporary='/vol2/aisub/new-tmp')
    manager.queue(desired)
    assert manager.state()['pending']
    assert (manager.links / 'data' / 'knowledge.json').is_file()
    assert manager.apply_pending()
    manager.configure_links()
    assert manager.state()['current']['data'] == '/vol2/aisub/new-data'
    assert (manager.links / 'data' / 'knowledge.json').read_text() == '{"preserved":true}'
    assert (manager.root / 'data' / 'knowledge.json').read_text() == '{"preserved":true}'
    assert not manager.state()['pending']


def test_migration_failure_keeps_active_data_and_is_visible(tmp_path, monkeypatch):
    manager = storage(tmp_path)
    (manager.root / 'data' / 'knowledge.json').write_text('original')
    desired = dict(manager.state()['current'], data='/vol2/aisub/new-data')
    manager.queue(desired)
    import app.library.storage as module
    monkeypatch.setattr(module.shutil, 'copytree', lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    assert not manager.apply_pending()
    assert manager.state()['current']['data'] == '/vol2/aisub/data'
    assert 'disk full' in manager.state()['error']
    assert (manager.root / 'data' / 'knowledge.json').read_text() == 'original'


def test_storage_rejects_escape_overlap_and_nonempty_destination(tmp_path):
    manager = storage(tmp_path)
    occupied = manager.root / 'occupied'; occupied.mkdir(); (occupied / 'existing').write_text('keep')
    outside = tmp_path / 'private'; outside.mkdir(); (manager.root / 'escape').symlink_to(outside)
    for path in ['/vol1/data', '/vol2/aisub/../private', '/vol2/aisub/escape/new',
                 '/vol2/aisub/data/child', '/vol2/aisub/models', '/vol2/aisub/occupied']:
        with pytest.raises(ValueError): manager.queue(dict(manager.state()['current'], data=path))
    assert not manager.state()['pending']
    assert (occupied / 'existing').read_text() == 'keep'


def test_project_artifacts_work_through_stable_storage_alias_without_allowing_escape(tmp_path, monkeypatch):
    from app.utils import project_store
    from app.services import translation_tasks as tasks
    physical = tmp_path / 'physical'; physical.mkdir()
    alias = tmp_path / 'projects'; alias.symlink_to(physical, target_is_directory=True)
    monkeypatch.setattr(project_store, 'PROJECTS_DIR', alias)
    pdir = alias / 'deadbeef'; pdir.mkdir(); (pdir / 'raw.srt').write_text('original')
    assert project_store.project_dir('deadbeef') == pdir
    assert tasks._safe_project_artifact_path('deadbeef', 'raw.srt') == pdir / 'raw.srt'
    assert tasks._safe_generated_project_output_path('deadbeef', 'new.srt') == pdir / 'new.srt'
    assert tasks._write_generated_project_artifact('deadbeef', 'new.srt', b'new', pdir).read_bytes() == b'new'
    (pdir / 'escape.srt').symlink_to(tmp_path / 'outside.srt')
    assert tasks._safe_generated_project_output_path('deadbeef', 'escape.srt') is None
