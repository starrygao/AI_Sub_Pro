"""Conservative cleanup of owned, reproducible intermediates; never whole projects."""
import hashlib
import logging
import os
import re
import stat
import time
from pathlib import Path
from .guard import fingerprint

GIB=1024**3
MIN_LIMIT_GB=5
MIN_AGE_SECONDS=86400
log=logging.getLogger(__name__)
PROJECT_FILES=('raw_audio.wav','demucs_out/htdemucs/raw_audio/vocals.wav',
               'demucs_out/htdemucs/raw_audio/no_vocals.wav')


def file_identity(path,root):
    """Reject links at every level, including links swapped in after inventory."""
    try:
        relative=path.relative_to(root)
        current=root
        for part in relative.parts:
            current=current/part
            if current.is_symlink():return None
        value=path.lstat()
        if not stat.S_ISREG(value.st_mode) or value.st_nlink!=1:return None
        return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
    except (OSError,ValueError):return None


def unlink_unchanged(candidate):
    """Keep directory handles pinned so a replaced parent cannot redirect deletion."""
    parts=candidate['path'].relative_to(candidate['root']).parts
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    fd=os.open(candidate['root'],flags)
    try:
        for part in parts[:-1]:
            child=os.open(part,flags,dir_fd=fd);os.close(fd);fd=child
        value=os.stat(parts[-1],dir_fd=fd,follow_symlinks=False)
        identity=(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if not stat.S_ISREG(value.st_mode) or value.st_nlink!=1 or identity!=candidate['identity']:return False
        os.unlink(parts[-1],dir_fd=fd)
        return True
    finally:os.close(fd)


class ProcessCleanup:
    def __init__(self,worker):
        self.worker=worker
        self.store=worker.store

    def policy(self):
        return {'enabled':False,'limit_gb':20,**self.store.setting('cleanup_policy',{})}

    def configure(self,enabled,limit_gb):
        if type(enabled) is not bool or type(limit_gb) is not int or not MIN_LIMIT_GB<=limit_gb<=100000:
            raise ValueError(f'过程文件占用上限必须是 {MIN_LIMIT_GB}–100000 GB 的整数')
        self.store.set_settings({'cleanup_policy':{'enabled':enabled,'limit_gb':limit_gb},'cleanup_next_check':0})
        self.worker.wake.set()
        return self.snapshot()

    def inventory(self,now=None):
        now=time.time() if now is None else now
        data=Path(self.store.path).parent.resolve()
        temporary=(self.worker.storage.local(self.worker.storage.load()['active']['temporary'])
                   if self.worker.storage else data/'temporary')
        rows={r['project_id']:r for r in self.store.rows(['done'],limit=10000) if r.get('project_id')}
        candidates=[];total=0
        def add(path,root,allowed):
            nonlocal total
            identity=file_identity(path,root)
            if not identity:return
            size=identity[2];total+=size
            if allowed and now-max(identity[3],identity[4])/1e9>=MIN_AGE_SECONDS:
                candidates.append({'path':path,'root':root,'identity':identity,'size':size,'mtime':identity[3]})
        projects=data/'projects'
        if not projects.is_symlink() and projects.is_dir():
            for folder in projects.iterdir():
                if not re.fullmatch(r'[0-9a-f]{8}',folder.name) or folder.is_symlink() or not folder.is_dir():continue
                row=rows.get(folder.name,{})
                allowed=False
                if row and now-row.get('completed_at',now)>=MIN_AGE_SECONDS:
                    output=Path(row.get('output_path',''))
                    try:
                        allowed=(fingerprint(row['path'])==row.get('fingerprint')
                                 and bool(row.get('output_hash')) and output.is_file() and not output.is_symlink()
                                 and hashlib.sha256(output.read_bytes()).hexdigest()==row['output_hash'])
                    except OSError:pass
                for name in PROJECT_FILES:add(folder/name,projects,allowed)
        if not temporary.is_symlink() and temporary.is_dir():
            for path in temporary.glob('aisubpro-codex-*.txt'):add(path,temporary,True)
            for folder in temporary.glob('aisubpro-subtitles-*'):
                if folder.is_symlink() or not folder.is_dir():continue
                for path in folder.iterdir():
                    if re.fullmatch(r'track_\d+\.(srt|ass|ssa|vtt)',path.name):add(path,temporary,True)
        return total,sorted(candidates,key=lambda c:c['mtime'])

    def snapshot(self):
        total,candidates=self.inventory()
        eligible=sum(c['size'] for c in candidates)
        return {**self.policy(),'minimum_gb':MIN_LIMIT_GB,'minimum_age_hours':24,
                'managed_bytes':total,'eligible_bytes':eligible,'protected_bytes':total-eligible,
                'eligible_files':len(candidates),'last_run':self.store.setting('cleanup_last_run',{})}

    def tick(self,now=None):
        now=time.time() if now is None else now
        policy=self.policy()
        if not policy['enabled'] or now<self.store.setting('cleanup_next_check',0):return
        self.store.set_setting('cleanup_next_check',now+600)
        try:
            if (self.worker.store.rows(['translating','publishing'],limit=1)
                    or (self.worker.storage and self.worker.storage.state()['pending'])):
                self.record(now,'busy',0,0);return
            from app.services.translation_tasks import run_when_tasks_idle
            result=run_when_tasks_idle(lambda:self.clean(now,policy['limit_gb']))
            if result is False:self.record(now,'busy',0,0)
        except Exception as exc:
            log.warning('Process cleanup deferred: %s',type(exc).__name__)
            self.record(now,'error',0,0,1)

    def record(self,now,status,files,freed,errors=0):
        result={'checked_at':now,'status':status,'removed_files':files,'freed_bytes':freed,'errors':errors}
        self.store.set_setting('cleanup_last_run',result)
        return result

    def clean(self,now,limit_gb):
        total,candidates=self.inventory(now)
        limit=limit_gb*GIB
        if total<=limit:return self.record(now,'below_limit',0,0)
        removed=freed=errors=0
        for candidate in candidates:
            if total-freed<=limit or self.worker.stop_event.is_set():break
            path,root=candidate['path'],candidate['root']
            if file_identity(path,root)!=candidate['identity']:continue
            try:
                # Unlink only the named file, never recursively remove a directory.
                if unlink_unchanged(candidate):removed+=1;freed+=candidate['size']
            except OSError:errors+=1
        return self.record(now,'protected_remaining' if total-freed>limit else 'cleaned',removed,freed,errors)
