"""Retire only identified old AI Sub Pro release copies, preserving one ZIP rollback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import zipfile

BUNDLE_ID='com.aisubpro.app'


def release_copies(root,active=()):
    root=Path(root).resolve();result=[]
    for base in [root/'.runtime/handoff-backups',root/'.runtime/verification']:
        if not base.is_dir() or base.is_symlink():continue
        for folder,dirs,files in os.walk(base,followlinks=False):
            dirs[:]=[name for name in dirs if not (Path(folder)/name).is_symlink()]
            for name in list(dirs):
                path=Path(folder)/name
                bundle=name.endswith('.app')
                standalone=(name=='AI Sub Pro' and (path/'AI Sub Pro').is_file() and (path/'_internal').is_dir())
                if not bundle and not standalone:continue
                dirs.remove(name)
                if any(Path(p).is_relative_to(path) for p in active):continue
                if bundle:
                    try:
                        info=plistlib.loads((path/'Contents/Info.plist').read_bytes())
                        if info.get('CFBundleIdentifier')!=BUNDLE_ID:continue
                    except (OSError,ValueError):continue
                bundle_files=[p for p in path.rglob('*') if p.is_file() and not p.is_symlink()]
                result.append({'path':str(path),'kind':'bundle' if bundle else 'standalone',
                               'bytes':sum(p.stat().st_size for p in bundle_files),'mtime':path.stat().st_mtime})
            for name in files:
                if not isinstance(name,str) or not re.fullmatch(r'AI_Sub_Pro_v\d+\.\d+\.\d+\.dmg',name):continue
                path=Path(folder)/name
                if path.is_symlink() or str(path) in active:continue
                result.append({'path':str(path),'kind':'installer','bytes':path.stat().st_size,'mtime':path.stat().st_mtime})
    return result


def archive_rollback(root,candidate):
    source=Path(candidate['path']);folder=root/'.runtime/rollback';folder.mkdir(parents=True,exist_ok=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(source)],check=True)
    target=folder/'AI_Sub_Pro_previous.zip';stage=folder/'AI_Sub_Pro_previous.new.zip'
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(source),str(stage)],check=True)
    info=plistlib.loads((source/'Contents/Info.plist').read_bytes())
    binary=Path('Contents/MacOS')/info['CFBundleExecutable']
    with zipfile.ZipFile(stage) as archive:
        if archive.testzip():raise RuntimeError('Rollback archive checksum failed')
        expected=hashlib.sha256((source/binary).read_bytes()).digest()
        if hashlib.sha256(archive.read(source.name+'/'+str(binary))).digest()!=expected:
            raise RuntimeError('Rollback executable verification failed')
    os.replace(stage,target)
    return str(target)


def retire(root,candidates,active=()):
    # Rebuild the allow-list just before mutations; never accept caller-supplied paths.
    permitted={r['path']:r for r in release_copies(root,active)}
    selected=[permitted[r['path']] for r in candidates if r['path'] in permitted]
    bundles=[r for r in selected if r['kind']=='bundle']
    rollback=archive_rollback(root,max(bundles,key=lambda r:r['mtime'])) if bundles else ''
    removed=[]
    for item in selected:
        path=Path(item['path'])
        if path.is_symlink() or any(Path(p).is_relative_to(path) for p in active):continue
        if item['kind']=='installer':path.unlink()
        else:shutil.rmtree(path)
        removed.append(item)
    return {'rollback':rollback,'removed':removed,'removed_bytes':sum(r['bytes'] for r in removed)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    active=subprocess.check_output(['ps','-axo','comm='],text=True).splitlines()
    active=[p.strip() for p in active if p.strip().startswith('/')]
    mounted=plistlib.loads(subprocess.check_output(['hdiutil','info','-plist']))
    active.extend(image['image-path'] for image in mounted.get('images',[]) if image.get('image-path'))
    candidates=release_copies(root,active)
    if args.apply:
        # A valid installed release must exist before discarding historical bundles.
        subprocess.run(['codesign','--verify','--deep','--strict','/Applications/AI Sub Pro.app'],check=True)
        result=retire(root,candidates,active)
    else:result={'candidates':candidates,'bytes':sum(r['bytes'] for r in candidates)}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
