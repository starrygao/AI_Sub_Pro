"""Authenticated Docker entry point; desktop startup remains unchanged."""
import base64
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from app.main import app as desktop_app, lifespan as desktop_lifespan
from starlette.routing import WebSocketRoute
from app.config import DATA_DIR
from app.library.worker import LibraryWorker
from app.library.auth import COOKIE_NAME, SESSION_SECONDS, Sessions, LoginAttempts

CONFIG_PATH=Path(os.environ.get('AISUBPRO_LIBRARY_CONFIG','/config/library.json'))
worker=None
login_attempts=LoginAttempts()
app=FastAPI(title='AI Sub Pro Server',version=desktop_app.version)
# Reuse endpoints without mutating the desktop app's middleware, routes or lifespan.
app.router.routes.extend(route for route in desktop_app.router.routes
                         if not isinstance(route,WebSocketRoute)
                         and getattr(route,'path','') not in {'/openapi.json','/docs','/docs/oauth2-redirect','/redoc'})


def password_matches(account,username,password):
    if account.get('algorithm')!='PBKDF2WithHmacSHA256' or not 600000<=account.get('iterations',0)<=2000000:return False
    if not password or len(password)>256 or len(username)>64:return False
    actual=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.b64decode(account['salt']),account['iterations'],32)
    return hmac.compare_digest(actual,base64.b64decode(account['hash'])) and hmac.compare_digest(username.encode(),account['username'].encode())


@asynccontextmanager
async def lifespan(instance):
    global worker
    config=json.loads(CONFIG_PATH.read_text())
    account_path=Path(config['account_file'])
    if account_path.stat().st_mode & 0o077:raise RuntimeError('账号文件必须设置为 600 权限')
    instance.state.server_account=json.loads(account_path.read_text())
    instance.state.operator_token=Path(config['operator_token_file']).read_text().strip()
    instance.state.sessions=Sessions(DATA_DIR/'server-sessions.sqlite3')
    async with desktop_lifespan(instance):
        worker=LibraryWorker(config,DATA_DIR)
        worker.start()
        try:yield
        finally:worker.stop()

app.router.lifespan_context=lifespan


@app.middleware('http')
async def authenticate(request:Request,call_next):
    if request.url.path=='/healthz':return JSONResponse({'status':'ok','server':True})
    if request.method not in {'GET','HEAD','OPTIONS'}:
        origin=request.headers.get('origin')
        if (origin and origin.rstrip('/')!=str(request.base_url).rstrip('/')) or request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'跨站请求已拒绝'},status_code=403)
    if request.url.path in {'/login','/api/auth/login','/static/css/login.css','/static/js/login.js',
                            '/favicon.ico','/static/favicon.ico','/static/favicon.svg'}:
        return await call_next(request)
    token=getattr(app.state,'operator_token','')
    supplied=request.headers.get('x-aisub-key','')
    authorized=bool(token and supplied and hmac.compare_digest(token,supplied))
    if not authorized:
        sessions=getattr(app.state,'sessions',None)
        authorized=bool(sessions and sessions.valid(request.cookies.get(COOKIE_NAME),app.state.server_account))
    if not authorized:
        if request.method=='GET' and request.url.path in {'/','/library','/desktop'}:
            destination=request.url.path+('?' + request.url.query if request.url.query else '')
            return RedirectResponse('/login?'+urlencode({'next':destination}),status_code=303)
        return JSONResponse({'detail':'登录已失效，请重新登录'},status_code=401,headers={'X-AISub-Login':'/login'})
    if request.url.path=='/':return RedirectResponse('/library')
    if request.method not in {'GET','HEAD','OPTIONS'} and getattr(worker,'restarting',False):
        return JSONResponse({'detail':'正在切换保存目录，请等待服务恢复。'},status_code=503)
    response=await call_next(request)
    if not request.url.path.startswith('/static/'):
        response.headers['Cache-Control']='no-store'
    return response


@app.get('/login')
def login_page():
    return FileResponse(Path(__file__).parent/'static'/'login.html',headers={'Cache-Control':'no-store'})


@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    return FileResponse(Path(__file__).parent/'static'/'favicon.ico',media_type='image/vnd.microsoft.icon')


class Login(BaseModel):
    username:str=Field(min_length=1,max_length=64)
    password:str=Field(min_length=1,max_length=256)


@app.post('/api/auth/login')
def login(body:Login,request:Request):
    address=request.client.host if request.client else 'unknown'
    if not login_attempts.allow(address):
        return JSONResponse({'detail':'尝试次数较多，请一分钟后再试。'},status_code=429,headers={'Retry-After':'60','Cache-Control':'no-store'})
    if not password_matches(app.state.server_account,body.username,body.password):
        return JSONResponse({'detail':'账号或密码不正确，请重新输入。'},status_code=401,headers={'Cache-Control':'no-store'})
    sessions=app.state.sessions
    sessions.revoke(request.cookies.get(COOKIE_NAME))
    token=sessions.create(app.state.server_account)
    response=JSONResponse({'ok':True},headers={'Cache-Control':'no-store'})
    response.set_cookie(COOKIE_NAME,token,max_age=SESSION_SECONDS,httponly=True,
                        secure=request.url.scheme=='https',samesite='lax',path='/')
    return response


@app.post('/api/auth/logout')
def logout(request:Request):
    app.state.sessions.revoke(request.cookies.get(COOKIE_NAME))
    response=JSONResponse({'ok':True},headers={'Cache-Control':'no-store'})
    response.delete_cookie(COOKIE_NAME,path='/',httponly=True,samesite='lax',secure=request.url.scheme=='https')
    return response


@app.get('/library')
def library_page():return FileResponse(Path(__file__).parent/'static'/'library.html')


@app.get('/desktop')
def desktop_page():return FileResponse(Path(__file__).parent/'static'/'index.html')


@app.get('/api/library/status')
def library_status():return worker.status()


@app.get('/api/library/overview')
def library_overview(timezone:str='UTC'):
    from app.library.overview import build_overview
    try:return build_overview(worker,timezone)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@app.get('/api/library/knowledge')
def library_knowledge():
    from app.library.knowledge import summary
    return summary(worker.store)


@app.get('/api/library/settings')
def library_settings():return worker.model_settings.read()


@app.post('/api/library/settings')
def library_settings_update(data:dict):
    result=worker.model_settings.queue(data)
    worker.wake.set()
    return result


@app.get('/api/library/directories')
def library_directories():
    return {'watch': worker.directories.read(),
            'storage': worker.storage.state() if worker.storage else {'supported': False, 'error': '当前部署尚未启用网页目录管理。'}}


@app.get('/api/library/proxy')
def library_proxy():
    return worker.proxy_settings.read()


@app.post('/api/library/proxy')
def library_proxy_update(data: dict):
    try:return worker.proxy_settings.queue(data)
    except ValueError as exc:raise HTTPException(400, str(exc))


class WatchFolders(BaseModel):
    roots:list[str]


@app.post('/api/library/directories/watch')
def library_watch_update(body:WatchFolders):
    try:return worker.directories.queue(body.roots)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@app.post('/api/library/directories/storage')
def library_storage_update(data:dict):
    if not worker.storage:raise HTTPException(400,'当前部署尚未启用网页目录管理。')
    try:result=worker.storage.queue(data)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    worker.wake.set()
    return result


@app.get('/api/library/tasks')
def library_tasks(state:str='',limit:int=100,offset:int=0,view:str='all'):
    if not 1<=limit<=200 or offset<0:raise HTTPException(400,'分页参数无效')
    views={'processed':['translating','publishing','done','error','changed','missing','cancelled','paused','pausing','cancelling'],
           'waiting':['waiting'],'ready':['ready'],'skipped':['skipped','native_language','historical']}
    if view not in {'all',*views}:raise HTTPException(400,'列表类型无效')
    states=views.get(view)
    counts=worker.store.counts()
    if state and states is not None and state not in states:
        rows=[];total=0
    else:
        states=[state] if state else states
        rows=worker.store.rows(states,limit,offset,attention_first=view=='processed')
        total=sum(counts.get(s,0) for s in states) if states else sum(counts.values())
    from app.library.overview import present_task
    rows=[present_task(row,worker.config.get('host_path_maps',{})) for row in rows]
    return {'items':rows,'counts':counts,'total':total,
            'view_counts':{name:sum(counts.get(s,0) for s in states) for name,states in views.items()}}


@app.get('/api/library/artwork')
def library_artwork(path:str=Query(max_length=4096),kind:Literal['poster','backdrop']='poster'):
    # The client selects a ledger row, never an upstream URL, local file or Emby ID.
    row=worker.store.get(path)
    if not row:raise HTTPException(404,'没有这条媒体记录')
    image=worker.sources.artwork.get(row,kind)
    if image is None:raise HTTPException(404,'暂无可用封面')
    return Response(image.content,media_type=image.media_type,headers={'X-Content-Type-Options':'nosniff'})


class Control(BaseModel):
    enabled:bool

@app.post('/api/library/control')
def library_control(body:Control):
    worker.store.set_setting('enabled',body.enabled);worker.wake.set()
    return worker.status()


@app.post('/api/library/scan')
def library_scan():
    worker.wake.set();return {'scheduled':True}


class Retry(BaseModel):
    path:str


class TaskTarget(BaseModel):
    model_config={'extra':'forbid'}
    path:str=Field(max_length=4096)
    revision:str=Field(pattern=r'^[0-9a-f]{64}$')


class TaskAction(BaseModel):
    model_config={'extra':'forbid'}
    action:Literal['pause','resume','cancel','delete']
    items:list[TaskTarget]=Field(min_length=1,max_length=100)
    cleanup_files:bool=Field(default=False,strict=True)


@app.post('/api/library/tasks/control')
def library_task_control(body:TaskAction):
    if body.cleanup_files and body.action!='delete':raise HTTPException(422,'只有删除任务时可以清理缓存')
    results=[];seen=set()
    for item in body.items:
        if item.path in seen:continue
        seen.add(item.path)
        try:results.append(worker.controls.request(item.path,body.action,item.revision,body.cleanup_files))
        except HTTPException as exc:results.append({'path':item.path,'ok':False,'error':worker.safe_error(exc.detail)})
        except (ValueError,OSError) as exc:results.append({'path':item.path,'ok':False,'error':worker.safe_error(exc)})
    return {'results':results}


class HardSubtitle(Retry):
    model_config={'extra':'forbid'}
    present:bool


class CleanupPolicy(BaseModel):
    model_config={'extra':'forbid'}
    enabled:bool
    limit_gb:int=Field(ge=5,le=100000,strict=True)


@app.get('/api/library/cleanup')
def library_cleanup():
    return worker.cleanup.snapshot()


@app.post('/api/library/cleanup')
def library_cleanup_settings(body:CleanupPolicy):
    return worker.cleanup.configure(body.enabled,body.limit_gb)


@app.post('/api/library/hard-subtitle')
def library_hard_subtitle(body:HardSubtitle):
    try:return worker.mark_hard_subtitle(body.path,body.present)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except (ValueError,OSError) as exc:raise HTTPException(409,worker.safe_error(exc)) from exc


EmbyId = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')]


class EmbyItems(BaseModel):
    model_config = {'extra': 'forbid'}
    ids: list[EmbyId] = Field(min_length=1, max_length=50)


def emby_selection_call(method, *args, **kwargs):
    from app.library.selection import EmbySelection
    try:
        return getattr(EmbySelection(worker), method)(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, 'Emby 暂不可用：' + worker.safe_error(exc)) from exc


@app.get('/api/library/emby/search')
def library_emby_search(q: str = Query(min_length=1, max_length=200), kind: Literal['all','movie','series'] = 'all',
                        offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=50)):
    return emby_selection_call('search', q, kind=kind, offset=offset, limit=limit)


@app.get('/api/library/emby/episodes')
def library_emby_episodes(series_id: EmbyId, offset: int = Query(default=0, ge=0),
                          limit: int = Query(default=30, ge=1, le=50)):
    return emby_selection_call('episodes', series_id, offset=offset, limit=limit)


@app.post('/api/library/emby/enqueue')
def library_emby_enqueue(body: EmbyItems):
    return emby_selection_call('enqueue', body.ids)

@app.post('/api/library/retry')
def library_retry(body:Retry):
    with worker.media_lock(body.path):return retry_library_row(body)


def retry_library_row(body):
    row=worker.store.get(body.path)
    if not row:raise HTTPException(404,'记录不存在')
    if row.get('manual_hard_subtitle'):raise HTTPException(409,'请先撤销中文硬字幕标记')
    if not worker.eligible_new_path(body.path,row.get('fingerprint')):raise HTTPException(409,'现有视频不补翻译')
    if row['state'] not in {'error','changed','missing','skipped','native_language'}:raise HTTPException(409,'当前任务不能重试')
    publishing=row.get('retry_stage')=='publish' and bool(row.get('project_id'))
    worker.save(row,state='publishing' if publishing else 'waiting',
                reason='等待重新保存字幕' if publishing else '等待重新检查',
                preparation_progress=None,detection=None,next_attempt_at=0,retry_attempts=0)
    worker.wake.set();return {'scheduled':True}
