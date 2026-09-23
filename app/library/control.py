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
        if state in {'waiting','ready','translating','publishing'}:return ['pause','cancel']
        if state=='paused':return ['resume','cancel']
        return []

    def request(self,path,action,expected):
        from app.services import translation_tasks as tasks
        if not self.lock.acquire(timeout=2):raise ValueError('正在提交任务状态或保存字幕，请稍后重试')
        try:
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
                state=('pausing' if action=='pause' else 'cancelling') if running else ('paused' if action=='pause' else 'cancelled')
                reason={'pausing':'正在暂停，等待当前步骤安全退出','cancelling':'正在取消，等待当前步骤安全退出',
                        'paused':'已暂停，保留进度；点击继续后重新检查并排队','cancelled':'已取消，不再自动处理；视频与已有字幕保留'}[state]
                row.update(state=state,reason=reason,control_action=action)
            row['updated']=time.time();self.worker.store.put(row);self.worker.wake.set()
            return {'path':path,'ok':True,'state':row['state']}
        finally:self.lock.release()

    def save(self,row,values):
        with self.lock:
            current=self.worker.store.get(row['path'])
            row.update(values,updated=time.time())
            # Slow probe/progress callbacks must never undo a concurrent user action.
            if current and current.get('fingerprint')==row.get('fingerprint') and current.get('control_action'):
                for key in ('state','reason','control_action'):row[key]=current[key]
            self.worker.store.put(row)

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
                row.update(state='paused' if paused else 'cancelled',updated=time.time(),
                           reason='已暂停，保留进度；点击继续后重新检查并排队' if paused else '已取消，不再自动处理；视频与已有字幕保留')
                self.worker.store.put(row)
