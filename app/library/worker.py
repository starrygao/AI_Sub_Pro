"""Single, low-priority library worker. Existing translation service owns model work."""
import itertools
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

from .guard import VIDEO_EXTENSIONS, fingerprint, ready_file, chinese_track, chinese_sidecar, subtitle_files, chinese_audio_only, has_foreign_audio, CHINESE_LANGUAGES, map_path
from .publish import publish_sidecar, archive_stale_sidecar
from .sources import Sources
from .store import Store
from .settings import LibrarySettings
from .directories import DirectorySettings
from .storage import StoragePaths

log=logging.getLogger(__name__)
TEXT_CODECS={'subrip','srt','ass','ssa','mov_text','webvtt','text'}


class LibraryWorker:
    def __init__(self,config,data_dir):
        self.config=config
        data_dir=Path(data_dir);data_dir.mkdir(parents=True,exist_ok=True)
        self.store=Store(data_dir/'library.sqlite3')
        self.model_settings=LibrarySettings(self.store)
        self.sources=Sources(config)
        self.stop_event=threading.Event()
        self.wake=threading.Event()
        self.thread=None
        self.blocked={};self.blocked_inodes={}
        self.health={};self.last_scan=0;self.last_error='';self.authenticated=False
        saved_roots=self.store.setting('watch_roots')
        self.manual_roots=saved_roots is not None
        self.roots=saved_roots if self.manual_roots else config.get('roots',[])
        self.directories=DirectorySettings(self)
        self.storage=StoragePaths.from_env()
        self.restarting=False
        self.walker=None
        self.emby_cursor=0
        self.last_recent=0

    def allowed(self,path):
        try:
            real=Path(path).resolve(strict=True)
            return any(real.is_relative_to(Path(p).resolve()) for p in self.config.get('allowed_roots',self.roots))
        except (OSError,RuntimeError):return False

    def observe(self,path,metadata):
        path=Path(path)
        if path.suffix.lower() not in VIDEO_EXTENSIONS or not self.allowed(path):return
        try:current=fingerprint(path)
        except OSError:return
        if not self.eligible_new_path(path,current):return
        now=time.time();old=self.store.get(path)
        try:
            created=datetime.fromisoformat(metadata.get('date_created','').replace('Z','+00:00')).timestamp()
            priority=int(now-created<7*86400)
        except (ValueError,TypeError):priority=0
        if not old or old.get('fingerprint')!=current:
            row={'path':str(path),'state':'waiting','reason':'等待文件稳定','fingerprint':current,
                 'stable_since':now,'updated':now,'priority':priority,'metadata':metadata,'output_path':str(path.with_suffix('.srt'))}
            if old and old.get('output_hash'):
                row['stale_output_hash']=old['output_hash']
                row['stale_output_path']=old.get('output_path',str(path.with_suffix('.srt')))
            if old and old.get('project_id'):
                row['previous_project_id']=old['project_id']
                if old['state']=='translating':
                    from app.services.translation_tasks import cancel_task
                    cancel_task(old['project_id'])
            self.store.put(row)
        else:
            if metadata:
                old['priority']=max(old.get('priority',0),priority)
                old['metadata']={**old.get('metadata',{}),**{k:v for k,v in metadata.items() if v is not None}}
                self.store.put(old)
            if old['state']=='done' and not Path(old.get('output_path','')).is_file():
                old.update(state='waiting',reason='字幕已被移除，重新检查',updated=now)
                self.store.put(old)
            if old['state']=='skipped' and old.get('existing_subtitles'):
                try:
                    changed=any(fingerprint(s['path'])!=s['fingerprint'] for s in old['existing_subtitles'])
                except OSError:changed=True
                if changed:self.save(old,state='waiting',reason='现有字幕已变化，重新检查')

    def set_blockers(self,blocked):
        self.blocked=blocked;self.blocked_inodes={}
        for path,reason in blocked.items():
            try:
                s=Path(path).stat();self.blocked_inodes[(s.st_dev,s.st_ino)]=reason
            except OSError:pass

    def block_reason(self,path):
        path=Path(path)
        original=self.sources.download_source(path) if self.config.get('moviepilot') else ''
        for blocked,reason in self.blocked.items():
            if original and (original==blocked or Path(original).is_relative_to(blocked)):return reason
            if str(path)==blocked or path.is_relative_to(blocked):return reason
        try:
            s=path.stat();return self.blocked_inodes.get((s.st_dev,s.st_ino),'')
        except OSError:return '视频不存在或不可读'

    def save(self,row,**values):
        row.update(values,updated=time.time());self.store.put(row)

    def start(self):
        self.thread=threading.Thread(target=self.run,name='library-monitor',daemon=True);self.thread.start()

    def stop(self):
        self.stop_event.set();self.wake.set()
        if self.thread:self.thread.join(timeout=5)

    def eligible_new_path(self,path,current=None):
        if self.manual_roots and not any(Path(path).is_relative_to(root) for root in self.roots):return False
        if not self.config.get('new_only',False):return True
        baseline=self.store.setting('baseline',{})
        return (bool(baseline.get('completed_at')) and set(self.roots)<=set(baseline.get('roots',[]))
                and any(Path(path).is_relative_to(root) for root in self.roots)
                and not self.store.baseline_contains(path,current))

    def establish_baseline(self):
        if not self.config.get('new_only',False):return
        if not self.roots and self.manual_roots:return
        if not self.roots:self.roots=self.sources.libraries()
        if not self.roots:raise RuntimeError('尚未读取到监控文件夹，暂不启动任务')
        baseline=self.store.setting('baseline',{})
        new_roots=sorted(set(self.roots)-set(baseline.get('roots',[])))
        if new_roots:
            entries=[]
            for path in self.filesystem(new_roots,strict=True):
                try:entries.append((str(path),fingerprint(path)))
                except FileNotFoundError:entries.append((str(path),None))
            self.store.install_baseline(entries,new_roots)
        from app.services.translation_tasks import cancel_task
        for pid in self.store.exclude_baseline_rows():cancel_task(pid)

    def filesystem(self,roots=None,strict=False):
        def failed(exc):raise exc
        for root in self.roots if roots is None else roots:
            if strict and not Path(root).is_dir():raise FileNotFoundError('监控文件夹不可读：'+str(root))
            for folder,dirs,files in os.walk(root,followlinks=False,onerror=failed if strict else None):
                dirs[:]=[d for d in dirs if not d.startswith('.') and d.lower() not in {'tmp','temp','incomplete','vtrans-staging','@eadir'}]
                for name in files:
                    if Path(name).suffix.lower() in VIDEO_EXTENSIONS:yield Path(folder)/name

    def discover(self):
        now=time.time()
        if not self.roots and self.manual_roots:return
        if not self.roots:self.roots=self.sources.libraries()
        self.establish_baseline()
        # The baseline filters existing videos even when Emby inventories them again.
        for path,meta in self.sources.recent_transfers():self.observe(path,meta)
        rows,total=self.sources.recent(0,100)
        for path,meta in rows:self.observe(path,meta)
        if total>100:
            self.emby_cursor=max(100,self.emby_cursor)
            rows,_=self.sources.recent(self.emby_cursor,100)
            for path,meta in rows:self.observe(path,meta)
            self.emby_cursor+=100
            if self.emby_cursor>=total:self.emby_cursor=100
        if self.walker is None:self.walker=self.filesystem()
        exhausted=True
        for path in itertools.islice(self.walker, int(self.config.get('files_per_scan',200))):
            exhausted=False;self.observe(path,{})
        if exhausted:self.walker=None
        self.last_scan=now

    def probe(self,path):
        from app.utils.media import get_ffprobe_path
        result=subprocess.run([get_ffprobe_path(),'-v','error','-threads','1','-probesize','8000000',
            '-analyzeduration','5000000','-show_streams','-show_format','-of','json',str(path)],
            capture_output=True,text=True,timeout=45)
        if result.returncode:raise RuntimeError('独立 ffprobe 无法读取完整媒体，稍后重试')
        info=json.loads(result.stdout)
        if not any(s.get('codec_type')=='video' for s in info.get('streams',[])):
            raise RuntimeError('未识别到视频流')
        if float(info.get('format',{}).get('duration',0))<=0:raise RuntimeError('媒体时长尚不可读')
        return info

    def refresh_readiness(self):
        self.set_blockers(self.sources.readiness());self.health=dict(self.sources.health)
        self.last_error=''

    def finish(self):
        from app.services import translation_tasks as tasks
        from app.api.projects import export_srt
        from app.utils.translation_delivery import translation_delivery_lock
        from app.utils.project_store import mutate_project
        for row in self.store.rows(['translating','publishing'],limit=5):
            path=Path(row['path']);pid=row['project_id']
            if not path.exists() or fingerprint(path)!=row['fingerprint']:
                if tasks.is_task_registered(pid):tasks.cancel_task(pid)
                self.save(row,state='changed',reason='视频已被替换，旧译文不会写回');continue
            if tasks.is_task_registered(pid):continue
            project=tasks._load_project(pid)
            if project.get('status') in {'error','cancelled'}:
                self.save(row,state='error',reason=project.get('error') or project.get('progress_msg') or '翻译已停止');continue
            reason=self.block_reason(path)
            if reason:self.save(row,state='publishing',reason=reason);continue
            try:
                with translation_delivery_lock(pid,blocking=False) as acquired:
                    if not acquired:
                        self.save(row,state='publishing',reason='等待字幕交付完成');continue
                    # Existing export gate validates source generation, report and delivery hashes.
                    export_srt(pid,format='bilingual',container='srt')
                    source=tasks.PROJECTS_DIR/pid/'bilingual.srt'
                    other=[p for p in subtitle_files(path) if p!=path.with_suffix('.srt') and chinese_sidecar(p)]
                    if other:
                        self.save(row,state='skipped',reason='翻译期间出现中文字幕，保留现有文件',
                                  existing_subtitles=[{'path':str(p),'fingerprint':fingerprint(p)} for p in other]);continue
                    output=publish_sidecar(path,source,row['fingerprint'])
                mutate_project(pid,lambda p:p.update(library_output_path=str(output),library_status='done'))
                self.save(row,state='done',reason='翻译完成，同名双语字幕已保存',output_path=str(output),completed_at=time.time(),output_hash=hashlib.sha256(output.read_bytes()).hexdigest())
                try:self.sources.refresh_subtitles(row.get('metadata',{}).get('emby_id',''))
                except Exception:self.save(row,reason='字幕已保存，Emby 刷新待重试',refresh_pending=True)
            except Exception as exc:
                self.save(row,state='error',reason='字幕未发布：'+self.safe_error(exc))

    @staticmethod
    def safe_error(exc):
        from app.engines.tmdb import public_error_message
        # Do not expose URLs (which may contain service credentials) in the web UI.
        if hasattr(exc,'request'):return type(exc).__name__+'：上游服务请求失败'
        return public_error_message(exc)

    def prepare(self,row,info,sidecars):
        from app.services import translation_tasks as tasks
        from app.services.project_defaults import _apply_safe_defaults
        from app.utils.project_store import atomic_write_json
        from app.utils.media import get_ffmpeg_path
        from app.utils.srt import parse_srt_file
        path=Path(row['path']);pid=uuid.uuid4().hex[:8];pdir=tasks.PROJECTS_DIR/pid;pdir.mkdir()
        row['output_path']=str(path.with_suffix('.srt'))
        metadata={**self.sources.metadata(path),**row.get('metadata',{})}
        streams=info['streams'];audio=[s for s in streams if s.get('codec_type')=='audio']
        subs=[s for s in streams if s.get('codec_type')=='subtitle']
        project=_apply_safe_defaults({'id':pid,'name':path.name,'video_path':str(path),
            'created_at':datetime.now(timezone.utc).isoformat(),'status':'created','progress':0,
            'duration':float(info['format']['duration']),'target_language':'简体中文','asr_language':'auto',
            'audio_tracks':[{'index':s['index'],'codec':s.get('codec_name',''),'lang':s.get('tags',{}).get('language','und')} for s in audio],
            'subtitle_tracks':[],'prefer_embedded_subtitle':False,'selected_audio_track':audio[0]['index'] if audio else 0,
            'library_source_path':str(path),'library_output_path':row['output_path'],'library_status':'translating',
            'library_fingerprint':row['fingerprint'],'workflow_mode':'translate_only',
            **{k:v for k,v in metadata.items() if k not in {'name','overview','emby_id'}},
            'content_notes':metadata.get('overview',''),'auto_run':True})
        # Prefer full foreign subtitles; forced/commentary tracks cannot cover all dialogue.
        usable=[s for s in subs if s.get('codec_name') in TEXT_CODECS and not s.get('disposition',{}).get('forced')
                and not any(w in s.get('tags',{}).get('title','').lower() for w in ['commentary','forced'])]
        usable.sort(key=lambda s:s.get('tags',{}).get('language') not in {'eng','en'})
        sidecars=[p for p in sidecars if p.suffix.lower() in {'.srt','.ass','.ssa','.vtt'} and 'forced' not in p.name.lower()]
        source_label='语音识别'
        if sidecars or usable:
            source=sidecars[0] if sidecars else path
            cmd=[get_ffmpeg_path(),'-nostdin','-v','error','-threads','1','-i',str(source)]
            if not sidecars:cmd+=['-map','0:'+str(usable[0]['index'])]
            cmd+=['-vn','-an','-c:s','srt','-y',str(pdir/'raw.srt')]
            subprocess.run(cmd,check=True,capture_output=True,timeout=900)
            if not parse_srt_file(str(pdir/'raw.srt')):raise RuntimeError('源字幕为空')
            (pdir/'filtered.srt').write_bytes((pdir/'raw.srt').read_bytes())
            project['status']='asr_done'
            source_label=str(source) if sidecars else '内嵌字幕 #'+str(usable[0]['index'])
        if fingerprint(path)!=row['fingerprint'] or self.block_reason(path):raise RuntimeError('提取期间视频状态变化')
        project['library_subtitle_source']=source_label
        atomic_write_json(pdir/'project.json',project)
        self.save(row,state='translating',reason='正在翻译',project_id=pid,subtitle_source=source_label,metadata=metadata)
        if project['status']=='asr_done':tasks.start_translate(pid,tasks.TranslateRequest(target_language='简体中文'))
        else:tasks.start_transcribe_translate(pid,tasks.FullPipelineRequest(workflow_mode='translate_only'))

    def process_one(self):
        from app.engines.providers.codex_cli import CodexCliProvider
        self.authenticated=CodexCliProvider.check_logged_in()
        if not self.authenticated:return
        if self.store.rows(['translating','publishing'],limit=1):return
        if self.health.get('emby',{}).get('transcoding',0)>int(self.config.get('max_emby_transcodes',0)):
            return
        if os.getloadavg()[0]>float(self.config.get('max_load',16)):return
        now=time.time()
        # Oldest waiting first avoids starvation while new arrivals keep coming.
        rows=self.store.rows(['waiting'],limit=100,oldest=True)
        for row in rows:
            path=Path(row['path'])
            if not self.eligible_new_path(path,row.get('fingerprint')):continue
            if not path.exists():self.save(row,state='missing',reason='视频已移动或删除');continue
            current=fingerprint(path)
            if current!=row['fingerprint']:self.observe(path,row.get('metadata',{}));continue
            reason=self.block_reason(path)
            ok,message=ready_file(path,row,now=now,quiet_seconds=int(self.config.get('quiet_seconds',300)))
            if reason or not ok:
                self.save(row,reason=reason or message)
                continue
            try:
                if row.get('stale_output_hash'):
                    backup=archive_stale_sidecar(row.get('stale_output_path') or path.with_suffix('.srt'),row['stale_output_hash'])
                    self.save(row,previous_subtitle_backup=str(backup) if backup else '',stale_output_hash=None,stale_output_path=None)
                sidecars=subtitle_files(path)
                chinese=[p for p in sidecars if chinese_sidecar(p)]
                if chinese:
                    self.save(row,state='skipped',reason='已有同目录中文字幕',
                              existing_subtitles=[{'path':str(p),'fingerprint':fingerprint(p)} for p in chinese]);continue
                if path.with_suffix('.srt').exists():
                    self.save(row,state='error',reason='同名 SRT 已存在，保留原文件；请先另存已有字幕后重新检查');continue
                info=self.probe(path)
                if any(chinese_track(s) for s in info['streams']):
                    self.save(row,state='skipped',reason='已有内嵌中文字幕');return
                if self.config.get('skip_chinese_audio',True) and chinese_audio_only(info['streams']):
                    self.save(row,state='native_language',reason='中文原声，无需翻译');return
                if self.config.get('skip_chinese_audio',True) and not has_foreign_audio(info['streams']):
                    metadata={**self.sources.metadata(path),**row.get('metadata',{})}
                    try:language=self.sources.original_language(metadata)
                    except Exception:
                        self.save(row,reason='音轨语言未知，等待 TMDB 原始语言确认');return
                    if language in CHINESE_LANGUAGES:
                        self.save(row,state='native_language',reason='TMDB 确认为中文原声，无需翻译',metadata=metadata);return
                # Re-read external readiness immediately before extraction / model work.
                self.refresh_readiness()
                if self.block_reason(path):self.save(row,reason=self.block_reason(path));return
                self.prepare(row,info,sidecars)
            except Exception as exc:
                self.save(row,state='error',reason=self.safe_error(exc))
                log.warning('Library candidate deferred: %s',type(exc).__name__)
            return  # At most one media probe/start per cycle.

    def tick(self):
        if self.apply_storage_settings():return
        self.directories.apply()
        from app.engines.providers.codex_cli import CodexCliProvider
        self.authenticated=CodexCliProvider.check_logged_in()
        self.establish_baseline()
        self.refresh_readiness()
        self.finish()
        self.apply_pending_settings()
        for row in self.store.rows(['done'],limit=50):
            if row.get('refresh_pending'):
                try:
                    self.sources.refresh_subtitles(row.get('metadata',{}).get('emby_id',''))
                    self.save(row,refresh_pending=False,reason='翻译完成，Emby 已刷新')
                except Exception:pass
        self.discover()
        if (self.store.setting('enabled',self.config.get('enabled',False)) and not self.model_settings.state()['pending']
                and not self.directories.read()['pending'] and not (self.storage and self.storage.state()['pending'])):
            self.process_one()

    def apply_storage_settings(self):
        if not self.storage or not self.storage.state()['pending']:return False
        from app.services.translation_tasks import run_when_tasks_idle
        def restart():
            if self.store.rows(['translating','publishing'],limit=1):return False
            if not self.restarting and self.storage.mark_restarting():
                import signal
                self.restarting=True
                timer=threading.Timer(1,lambda:os.kill(os.getpid(),signal.SIGTERM))
                timer.daemon=True;timer.start()
            return self.restarting
        return run_when_tasks_idle(restart)

    def apply_pending_settings(self):
        try:return self.model_settings.apply()
        except Exception as exc:
            self.store.set_setting('model_settings_error','设置暂未应用：'+self.safe_error(exc))
            raise  # Do not start the next job after a failed configuration write.

    def run(self):
        while not self.stop_event.is_set():
            try:self.tick()
            except Exception as exc:
                self.last_error='等待上游状态恢复：'+self.safe_error(exc)
                log.warning('Library scan deferred: %s',type(exc).__name__)
            self.wake.wait(max(10,int(self.config.get('scan_interval',60))));self.wake.clear()

    def status(self):
        return {'enabled':self.store.setting('enabled',self.config.get('enabled',False)),
                'last_scan':self.last_scan,'error':self.last_error,'connections':self.health,
                'codex_logged_in':self.authenticated,'counts':self.store.counts(),'roots':self.roots,
                'server_roots':[map_path(p,self.config.get('host_path_maps',{})) for p in self.roots],
                'new_only':self.config.get('new_only',False),'baseline':self.store.setting('baseline',{}),
                'quiet_seconds':self.config.get('quiet_seconds',300),'scan_interval':self.config.get('scan_interval',60),
                'model_settings':self.model_settings.state()}
