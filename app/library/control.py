"""Durable per-media stop requests; cancellation is acknowledged only after work exits."""
import hashlib
import json
import threading
import time

from .guard import fingerprint

STOPPING={'pausing','cancelling'}
STOPPED={'paused','cancelled'}


class MediaStopped(RuntimeError):
    pass


class TaskControls:
    def __init__(self,worker):
        self.worker=worker
        self.lock=threading.RLock()
        self.preparing=set()

    @staticmethod
    def revision(row):
        return hashlib.sha256(json.dumps(row.get('fingerprint')).encode()).hexdigest()

    @staticmethod
    def actions(row):
        state=row['state']
        if state=='deleted' or row.get('control_action')=='delete':return []
        if state in {'waiting','ready','translating','publishing'}:return ['pause','cancel','delete']
        if state=='paused':return ['resume','cancel','delete']
        return ['delete']

    def request(self,path,action,expected,cleanup_files=False):
        from app.services import translation_tasks as tasks
        if not self.lock.acquire(timeout=2):raise ValueError('正在提交任务状态或保存字幕，请稍后重试')
        try:
            if type(cleanup_files) is not bool or (cleanup_files and action!='delete'):raise ValueError('只有删除任务时可以清理缓存')
            row=self.worker.store.get(path)
            if not row:raise ValueError('记录不存在')
            if self.revision(row)!=expected:raise ValueError('文件记录已变化，请刷新后重试')
            if action not in self.actions(row):raise ValueError('当前状态不支持此操作，请刷新列表')
            pid=row.get('project_id')
            if action=='resume':
                if path in self.preparing or (pid and tasks.is_task_registered(pid)):raise ValueError('任务尚未完全停止，请稍后继续')
                if not self.worker.allowed(path) or fingerprint(path)!=row.get('fingerprint'):raise ValueError('原视频已变化或不可读，不能继续旧任务')
                row.update(state='waiting',reason='已恢复排队，重新检查视频、下载和字幕状态',control_action=None,
                           resume_pending=bool(pid),detection=None,next_attempt_at=0)
            else:
                running=path in self.preparing or bool(pid and tasks.is_task_registered(pid))
                if running and pid:tasks.cancel_task(pid)
                state=('pausing' if action=='pause' else 'cancelling') if running else {'pause':'paused','cancel':'cancelled','delete':'cancelling'}[action]
                reason={'pausing':'正在暂停，等待当前步骤安全退出','cancelling':'正在取消，等待当前步骤安全退出',
                        'paused':'已暂停，保留进度；点击继续后重新检查并排队','cancelled':'已取消，不再自动处理；视频与已有字幕保留',
                        'deleted':'任务已从列表删除；视频与已有字幕保留'}[state]
                if action=='delete' and running:reason='正在删除，等待当前步骤安全退出后移除记录'
                row.update(state=state,reason=reason,control_action=action)
                if action=='delete':
                    row.update(cleanup_files=cleanup_files,delete_error=None)
                    if cleanup_files:row['reason']='正在删除，等待任务安全停止并清理缓存和中间文件'
            row['updated']=time.time();self.worker.store.put(row);self.worker.wake.set()
            if action=='delete' and not running:self._settle_delete(row)
            result={'path':path,'ok':not bool(row.get('delete_error')),'state':row['state']}
            if row.get('delete_error'):result['error']=row['reason']
            return result
        finally:self.lock.release()

    def save(self,row,values):
        with self.lock:
            current=self.worker.store.get(row['path'])
            row.update(values,updated=time.time())
            # Slow probe/progress callbacks must never undo a concurrent user action.
            if current and current.get('fingerprint')==row.get('fingerprint') and current.get('control_action'):
                for key in ('state','reason','control_action','cleanup_files','delete_error'):row[key]=current.get(key)
            self.worker.store.put(row)

    def _settle_delete(self,row):
        from app.services import translation_tasks as tasks
        from .cleanup import clean_task_intermediates
        try:
            # Registration and cleanup share the task registry lock. Never remove
            # audio while a pipeline may still be using it or starting to use it.
            if row.get('cleanup_files') and not tasks.run_when_tasks_idle(lambda:clean_task_intermediates(self.worker.store,row.get('project_id'))):return
            row.update(state='deleted',reason='任务已从列表删除；'+('已清理缓存和中间文件，原视频与已有字幕保留' if row.get('cleanup_files') else '文件全部保留'))
        except (ValueError,OSError) as exc:
            row.update(state='error',control_action='cancel',delete_error=self.worker.safe_error(exc),
                       reason='删除未完成：缓存清理失败，请重新点击删除重试。'+self.worker.safe_error(exc))
        row['updated']=time.time();self.worker.store.put(row)

    def stopped(self,path):
        return bool((self.worker.store.get(path) or {}).get('control_action'))

    def check(self,path):
        if self.stopped(path):raise MediaStopped('任务已请求停止')

    def settle(self):
        from app.services import translation_tasks as tasks
        with self.lock:
            for row in self.worker.store.rows(list(STOPPING),limit=10000):
                pid=row.get('project_id')
                if row['path'] in self.preparing or (pid and tasks.is_task_registered(pid)):continue
                paused=row.get('control_action')=='pause'
                deleted=row.get('control_action')=='delete'
                if deleted:
                    self._settle_delete(row);continue
                row.update(state='paused' if paused else 'cancelled',updated=time.time(),
                           reason='已暂停，保留进度；点击继续后重新检查并排队' if paused else '已取消，不再自动处理；视频与已有字幕保留')
                self.worker.store.put(row)
