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

from .guard import (VIDEO_EXTENSIONS, fingerprint, ready_file, chinese_track, chinese_sidecar,
                    subtitle_files, chinese_audio_only, has_foreign_audio, CHINESE_LANGUAGES, map_path,
                    complete_subtitle_stream, complete_sidecar, select_audio_track, language_code,
                    chinese_subtitle_attachment)
from .publish import publish_sidecar, archive_stale_sidecar, bilingual_sidecar_path
from .sources import Sources
from .store import Store
from .settings import LibrarySettings
from .directories import DirectorySettings
from .storage import StoragePaths
from .extraction import extract_subtitles

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

    def observe(self,path,metadata,*,manual=False):
        path=Path(path)
        if path.suffix.lower() not in VIDEO_EXTENSIONS or not self.allowed(path):return
        try:current=fingerprint(path)
        except OSError:return
        if not manual and not self.eligible_new_path(path,current):return
        now=time.time();old=self.store.get(path)
        try:
            created=datetime.fromisoformat(metadata.get('date_created','').replace('Z','+00:00')).timestamp()
            priority=int(now-created<7*86400)
        except (ValueError,TypeError):priority=0
        if not old or old.get('fingerprint')!=current:
            row={'path':str(path),'state':'waiting','reason':'检测排队中','fingerprint':current,
                 'stable_since':now,'updated':now,'priority':priority,'metadata':metadata,'output_path':str(bilingual_sidecar_path(path))}
            if manual:
                row.update(manual_requested=True,manual_requested_at=(old or {}).get('manual_requested_at',now))
            if old and (old.get('output_hash') or old.get('stale_output_hash')):
                # A replacement can change across many scans before becoming stable.
                row['stale_output_hash']=old.get('output_hash') or old['stale_output_hash']
                row['stale_output_path']=(old.get('output_path') if old.get('output_hash') else old.get('stale_output_path')) or str(path.with_suffix('.srt'))
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
        selected=self.store.get(path)
        if (selected and selected.get('manual_requested') and selected.get('fingerprint')==current
                and self.allowed(path)):
            return True
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
        # A newly detected job may be outside the oldest discovery page.
        candidates=(self.store.rows(['ready'],limit=1,oldest=True)+self.store.waiting_ready(time.time())
                    +self.store.rows(['translating','publishing'],limit=5))
        self.set_blockers(self.sources.readiness(candidates=[row['path'] for row in candidates]));self.health=dict(self.sources.health)
        self.last_error=''

    def finish(self):
        from app.services import translation_tasks as tasks
        from app.api.projects import export_srt
        from app.utils.translation_delivery import translation_delivery_lock
        from app.utils.project_store import mutate_project
        for row in self.store.rows(['translating','publishing'],limit=5):
            # prepare runs synchronously in this worker. A persisted preparation here
            # therefore survived an interrupted process, not an active extraction.
            if row.get('preparation_progress'):
                self.save(row,state='error',reason='字幕提取被中断，请重新检查',retry_stage=None)
                continue
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
            delivery_ready=False
            try:
                with translation_delivery_lock(pid,blocking=False) as acquired:
                    if not acquired:
                        self.save(row,state='publishing',reason='等待字幕交付完成');continue
                    # Existing export gate validates source generation, report and delivery hashes.
                    export_srt(pid,format='bilingual',container='srt')
                    delivery_ready=True
                    source=tasks.PROJECTS_DIR/pid/'bilingual.srt'
                    other=[p for p in subtitle_files(path) if p!=bilingual_sidecar_path(path) and chinese_sidecar(p,path)]
                    if other:
                        self.save(row,state='skipped',reason='翻译期间出现中文字幕，保留现有文件',
                                  existing_subtitles=[{'path':str(p),'fingerprint':fingerprint(p)} for p in other]);continue
                    output=publish_sidecar(path,source,row['fingerprint'])
                mutate_project(pid,lambda p:p.update(library_output_path=str(output),library_status='done'))
                self.save(row,state='done',reason='翻译完成，带中文语言标记的双语字幕已保存',output_path=str(output),completed_at=time.time(),output_hash=hashlib.sha256(output.read_bytes()).hexdigest(),retry_stage=None)
                try:self.sources.refresh_subtitles(row.get('metadata',{}).get('emby_id',''))
                except Exception:self.save(row,reason='字幕已保存，Emby 刷新待重试',refresh_pending=True)
            except Exception as exc:
                self.save(row,state='error',reason='字幕未发布：'+self.safe_error(exc),retry_stage='publish' if delivery_ready else None)

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
        row['output_path']=str(bilingual_sidecar_path(path))
        metadata={**self.sources.metadata(path),**row.get('metadata',{})}
        streams=info['streams'];audio=[s for s in streams if s.get('codec_type')=='audio']
        subs=[s for s in streams if s.get('codec_type')=='subtitle']
        selected_audio=select_audio_track(streams)
        project=_apply_safe_defaults({'id':pid,'name':path.name,'video_path':str(path),
            'created_at':datetime.now(timezone.utc).isoformat(),'status':'created','progress':0,
            'duration':float(info['format']['duration']),'target_language':'简体中文','asr_language':'auto',
            'audio_tracks':[{'index':s['index'],'codec':s.get('codec_name',''),'lang':s.get('tags',{}).get('language','und')} for s in audio],
            'subtitle_tracks':[],'prefer_embedded_subtitle':False,'selected_audio_track':selected_audio if selected_audio is not None else 0,
            'library_source_path':str(path),'library_output_path':row['output_path'],'library_status':'translating',
            'library_fingerprint':row['fingerprint'],'workflow_mode':'translate_only',
            **{k:v for k,v in metadata.items() if k not in {'name','overview','emby_id'}},
            'content_notes':metadata.get('overview',''),'auto_run':True})
        # Prefer full foreign subtitles; forced/commentary tracks cannot cover all dialogue.
        usable=[s for s in subs if s.get('codec_name') in TEXT_CODECS and complete_subtitle_stream(s,path)]
        usable.sort(key=lambda s:language_code(s) not in {'eng','en'})
        sidecars=[p for p in sidecars if p.suffix.lower() in {'.srt','.ass','.ssa','.vtt'} and complete_sidecar(p,path)]
        source_label='语音识别'
        if sidecars or usable:
            source=sidecars[0] if sidecars else path
            source_label=str(source) if sidecars else '内嵌字幕 #'+str(usable[0]['index'])
            self.save(row,state='translating',reason='正在提取字幕',project_id=None,
                      subtitle_source=source_label,metadata=metadata,retry_stage=None,
                      preparation_progress={'stage':'subtitle_extract','progress':None,
                                            'message':'正在提取字幕，准备读取源文件'})
            def report(position,total,elapsed):
                percent=min(99,int(position*100/total)) if position is not None and total>0 else None
                reading=(f'读取位置 {position/1024**2:.1f} / {total/1024**2:.1f} MiB · ' if position is not None else '')
                self.save(row,preparation_progress={'stage':'subtitle_extract','progress':percent,
                    'message':f'正在提取字幕 · {reading}已用 {elapsed} 秒',
                    'updated_at':datetime.now(timezone.utc).isoformat()})
            cmd=[get_ffmpeg_path(),'-nostdin','-v','error','-threads','1','-i',str(source)]
            if not sidecars:cmd+=['-map','0:'+str(usable[0]['index'])]
            cmd+=['-vn','-an','-c:s','srt','-y',str(pdir/'raw.srt')]
            extract_subtitles(cmd,source,report,self.stop_event)
            if not parse_srt_file(str(pdir/'raw.srt')):raise RuntimeError('源字幕为空')
            (pdir/'filtered.srt').write_bytes((pdir/'raw.srt').read_bytes())
            project['status']='asr_done'
        elif selected_audio is None:
            raise RuntimeError('未找到可用于完整对白识别的音轨')
        if fingerprint(path)!=row['fingerprint'] or self.block_reason(path):raise RuntimeError('提取期间视频状态变化')
        project['library_subtitle_source']=source_label
        atomic_write_json(pdir/'project.json',project)
        self.save(row,state='translating',reason='正在翻译',project_id=pid,subtitle_source=source_label,metadata=metadata,
                  preparation_progress=None,retry_stage=None,next_attempt_at=0,retry_attempts=0)
        if project['status']=='asr_done':tasks.start_translate(pid,tasks.TranslateRequest(target_language='简体中文'))
        else:tasks.start_transcribe_translate(pid,tasks.FullPipelineRequest(workflow_mode='translate_only'))

    def arrival_status(self,row):
        """An old Emby item is not a new episode just because its directory moved."""
        if not self.config.get('new_only',False) or row.get('manual_requested'):return ''
        baseline=self.store.setting('baseline',{}).get('started_at')
        if not baseline:return '等待完成现有媒体登记'
        metadata=row.get('metadata',{})
        if metadata.get('emby_id'):
            try:
                created=datetime.fromisoformat(metadata.get('date_created','').replace('Z','+00:00'))
                if created.tzinfo is not None:
                    timestamp=created.timestamp()
                    if 0<timestamp<=baseline:return 'historical'
                    if baseline<timestamp<=time.time()+300:return ''
            except (ValueError,TypeError,AttributeError):pass
        # Old mtime alone is never evidence: downloads often preserve release timestamps.
        if Path(row['path']).stat().st_ctime<=baseline:
            return '文件早于监控启用，等待入库记录确认；可从 Emby 手动添加'
        return ''

    def subtitle_snapshot(self,path):
        return [{'path':str(p),'fingerprint':fingerprint(p)} for p in sorted(subtitle_files(path))]

    def inspect_candidate(self,row):
        """No model work here. Reuse probe results only for the exact unchanged input."""
        path=Path(row['path'])
        if not path.exists():self.save(row,state='missing',reason='视频已移动或删除');return
        if not self.allowed(path):self.save(row,state='missing',reason='视频不在允许的媒体目录内');return
        current=fingerprint(path)
        if current!=row['fingerprint']:
            self.observe(path,row.get('metadata',{}),manual=bool(row.get('manual_requested')));return
        if not self.eligible_new_path(path,current):
            self.save(row,state='historical',reason='现有媒体或已离开监控范围，不自动补翻译',detection=None);return
        arrival=self.arrival_status(row)
        if arrival=='historical':
            self.save(row,state='historical',reason='Emby 入库早于监控启用，不自动补翻译',detection=None);return
        if arrival:
            self.save(row,state='waiting',reason=arrival,detection=None,next_attempt_at=time.time()+60);return
        reason=self.block_reason(path)
        ok,message=ready_file(path,row,now=time.time(),quiet_seconds=int(self.config.get('quiet_seconds',300)))
        if reason or not ok:
            self.save(row,state='waiting',reason=reason or message,detection=None);return
        if row.get('stale_output_hash'):
            backup=archive_stale_sidecar(row.get('stale_output_path') or path.with_suffix('.srt'),row['stale_output_hash'])
            self.save(row,previous_subtitle_backup=str(backup) if backup else '',stale_output_hash=None,stale_output_path=None)
        subtitles=self.subtitle_snapshot(path)
        sidecars=[Path(item['path']) for item in subtitles]
        chinese=[p for p in sidecars if chinese_sidecar(p,path)]
        if chinese:
            self.save(row,state='skipped',reason='已有同目录中文字幕',detection=None,
                      existing_subtitles=[{'path':str(p),'fingerprint':fingerprint(p)} for p in chinese]);return
        policy=bool(self.config.get('skip_chinese_audio',True))
        previous=row.get('detection') or {}
        cached=(previous.get('fingerprint')==current and previous.get('subtitles')==subtitles
                and previous.get('skip_chinese_audio')==policy and isinstance(previous.get('info'),dict))
        if cached:info=previous['info']
        else:
            self.save(row,state='waiting',reason='正在检查字幕和音轨',detection=None)
            self._detection_probes=getattr(self,'_detection_probes',0)+1
            info=self.probe(path)
        if fingerprint(path)!=current or self.subtitle_snapshot(path)!=subtitles:
            self.observe(path,row.get('metadata',{}),manual=bool(row.get('manual_requested')))
            self.save(self.store.get(path),state='waiting',reason='检测期间文件或字幕发生变化，等待重新检查',detection=None);return
        if any(chinese_track(s,path) for s in info['streams']):
            self.save(row,state='skipped',reason='已有内嵌中文字幕',detection=None);return
        if any(chinese_subtitle_attachment(s,path) for s in info['streams']):
            self.save(row,state='skipped',reason='已有中文字幕附件',detection=None);return
        if bilingual_sidecar_path(path).exists():
            self.save(row,state='error',reason='双语字幕目标文件已存在，保留原文件；请先检查该文件后重试',detection=None);return
        if policy and chinese_audio_only(info['streams']):
            self.save(row,state='native_language',reason='中文原声，无需翻译',detection=None);return
        if policy and not has_foreign_audio(info['streams']):
            metadata={**self.sources.metadata(path),**row.get('metadata',{})}
            try:language=self.sources.original_language(metadata)
            except Exception:
                attempts=min(int(row.get('retry_attempts',0))+1,7)
                self.save(row,state='waiting',reason='音轨语言未知，等待 TMDB 原始语言确认',detection=None,
                          retry_attempts=attempts,next_attempt_at=time.time()+min(3600,60*2**(attempts-1)));return
            if language in CHINESE_LANGUAGES:
                self.save(row,state='native_language',reason='TMDB 确认为中文原声，无需翻译',metadata=metadata,detection=None);return
        if fingerprint(path)!=current or self.subtitle_snapshot(path)!=subtitles:
            self.save(row,state='waiting',reason='检测期间文件或字幕发生变化，等待重新检查',detection=None);return
        self.save(row,state='ready',reason='检测通过，等待翻译名额',next_attempt_at=0,
                  detection={'fingerprint':current,'subtitles':subtitles,'skip_chinese_audio':policy,'info':info})
        return info,sidecars

    def process_one(self,start=True):
        # Detection is independent of model availability and the active translation.
        busy=(self.health.get('emby',{}).get('transcoding',0)>int(self.config.get('max_emby_transcodes',0)))
        busy_reason='Emby 正在转码，等待空闲后检测' if busy else ''
        if os.getloadavg()[0]>float(self.config.get('max_load',16)):busy_reason='服务器负载较高，等待空闲后检测'
        deadline=time.monotonic()+10
        self._detection_probes=0
        for row in self.store.waiting_ready(time.time()):
            if self.stop_event.is_set():break
            if busy_reason:
                self.save(row,reason=busy_reason);continue
            if self._detection_probes>=10 or time.monotonic()>=deadline:break
            try:self.inspect_candidate(row)
            except Exception as exc:
                self.save(row,state='error',reason=self.safe_error(exc),detection=None)
                log.warning('Library candidate deferred: %s',type(exc).__name__)
        from app.engines.providers.codex_cli import CodexCliProvider
        self.authenticated=CodexCliProvider.check_logged_in()
        queued_reason=('自动翻译已暂停或设置待生效，检测结果已保留' if not start else
                       'Codex 尚未登录，等待登录后翻译' if not self.authenticated else
                       busy_reason.replace('后检测','后翻译') or '检测通过，等待翻译名额')
        for row in self.store.rows(['ready'],limit=100):
            if row.get('reason')!=queued_reason:self.save(row,reason=queued_reason)
        if not start or not self.authenticated or busy_reason:return
        if self.store.rows(['translating','publishing'],limit=1):return
        for row in self.store.rows(['ready'],limit=1,oldest=True):
            try:
                # Refresh download/write blockers, then revalidate file and sidecars.
                try:self.refresh_readiness()
                except Exception as exc:
                    self.save(row,state='waiting',reason='等待上游就绪状态恢复：'+self.safe_error(exc),detection=None);return
                result=self.inspect_candidate(row)
                if result:self.prepare(row,*result)
            except Exception as exc:
                self.save(row,state='error',reason=self.safe_error(exc))
                log.warning('Library start deferred: %s',type(exc).__name__)

    def tick(self):
        if self.apply_storage_settings():return
        self.directories.apply()
        from app.engines.providers.codex_cli import CodexCliProvider
        self.authenticated=CodexCliProvider.check_logged_in()
        self.establish_baseline()
        self.refresh_readiness()
        self.finish()
        self.apply_pending_settings()
        for row in self.store.pending_refresh():
            try:
                self.sources.refresh_subtitles(row.get('metadata',{}).get('emby_id',''))
                self.save(row,refresh_pending=False,reason='翻译完成，Emby 已刷新')
            except Exception:
                # Rotate failed attempts so an unavailable batch cannot hide older work.
                self.save(row,refresh_pending=True)
        self.discover()
        if not self.directories.read()['pending'] and not (self.storage and self.storage.state()['pending']):
            self.process_one(start=bool(self.store.setting('enabled',self.config.get('enabled',False)))
                             and not self.model_settings.state()['pending'])

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
