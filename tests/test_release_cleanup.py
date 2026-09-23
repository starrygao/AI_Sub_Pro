import plistlib

from tools.release.cleanup_project import release_copies
from tools.release.prune_docker_versions import plan


def bundle(root,name,bundle_id='com.aisubpro.app'):
    path=root/name;contents=path/'Contents';contents.mkdir(parents=True)
    (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':bundle_id}))
    return path


def test_local_release_inventory_excludes_current_data_other_apps_and_active_bundles(tmp_path):
    backups=tmp_path/'.runtime/handoff-backups'
    old=bundle(backups,'old.app');active=bundle(backups,'active.app')
    bundle(backups,'unrelated.app','other.app')
    bundle(tmp_path/'dist','AI Sub Pro.app')
    bundle(tmp_path/'.runtime/AI_Sub_Pro_Data','data.app')
    link=backups/'linked.app';link.symlink_to(old,target_is_directory=True)
    rows=release_copies(tmp_path,[str(active/'Contents/MacOS/AI Sub Pro')])
    assert [r['path'] for r in rows]==[str(old)]


def test_docker_retirement_keeps_current_refs_and_explicit_verified_rollback():
    images=[{'id':'current','created':'2026-03','tags':['ai-sub-pro:server','ai-sub-pro:candidate']},
            {'id':'verified','created':'2026-01','tags':['ai-sub-pro:rollback','ai-sub-pro:old-good']},
            {'id':'failed','created':'2026-02','tags':['ai-sub-pro:failed']},
            {'id':'other','created':'2026-01','tags':['other:keep']}]
    result=plan(images,[{'image':'current','ref':'ai-sub-pro:server'}],'current')
    assert result['rollback']=='verified'
    assert set(result['remove_tags'])=={'ai-sub-pro:candidate','ai-sub-pro:old-good','ai-sub-pro:failed'}


def test_docker_retirement_protects_refs_of_stopped_containers_too():
    images=[{'id':'old','created':'2026','tags':['ai-sub-pro:stopped']}]
    result=plan(images,[{'image':'old','ref':'ai-sub-pro:stopped'}],'current')
    assert not result['remove_tags'] and result['rollback'] is None


def test_old_installers_are_identified_but_mounted_and_unrelated_images_are_preserved(tmp_path):
    folder=tmp_path/'.runtime/verification/old-build';folder.mkdir(parents=True)
    old=folder/'AI_Sub_Pro_v1.2.3.dmg';old.write_bytes(b'old')
    mounted=folder/'AI_Sub_Pro_v1.2.4.dmg';mounted.write_bytes(b'mounted')
    other=folder/'other.dmg';other.write_bytes(b'keep')
    rows=release_copies(tmp_path,[str(mounted)])
    assert [r['path'] for r in rows]==[str(old)]
    assert rows[0]['kind']=='installer'


def test_docker_retirement_keeps_an_image_referenced_by_id():
    images=[{'id':'old','created':'2026','tags':['ai-sub-pro:old']}]
    result=plan(images,[{'image':'old','ref':'old'}],'current')
    assert not result['remove_tags']
