"""Authenticated Docker entry point; desktop startup remains unchanged."""
import base64
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from app.main import app as desktop_app, lifespan as desktop_lifespan
from starlette.routing import WebSocketRoute
from app.config import DATA_DIR
from app.library.worker import LibraryWorker
from app.library.guard import map_path
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
    if request.url.path in {'/login','/api/auth/login','/static/css/login.css','/static/js/login.js'}:
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
    response=await call_next(request)
    if not request.url.path.startswith('/static/'):
        response.headers['Cache-Control']='no-store'
    return response


@app.get('/login')
def login_page():
    return FileResponse(Path(__file__).parent/'static'/'login.html',headers={'Cache-Control':'no-store'})


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


@app.get('/api/library/settings')
def library_settings():return worker.model_settings.read()


@app.post('/api/library/settings')
def library_settings_update(data:dict):
    result=worker.model_settings.queue(data)
    worker.wake.set()
    return result


@app.get('/api/library/tasks')
def library_tasks(state:str='',limit:int=100,offset:int=0,view:str='all'):
    if not 1<=limit<=200 or offset<0:raise HTTPException(400,'分页参数无效')
    views={'processed':['translating','publishing','done','error','changed','missing'],
           'waiting':['waiting'],'skipped':['skipped','native_language']}
    if view not in {'all',*views}:raise HTTPException(400,'列表类型无效')
    states=views.get(view)
    counts=worker.store.counts()
    if state and states is not None and state not in states:
        rows=[];total=0
    else:
        states=[state] if state else states
        rows=worker.store.rows(states,limit,offset)
        total=sum(counts.get(s,0) for s in states) if states else sum(counts.values())
    for row in rows:
        mappings=worker.config.get('host_path_maps',{})
        if row['state'] not in {'done','skipped','native_language'}:
            row['output_path']=str(Path(row['path']).with_suffix('.srt'))
        row['server_source_path']=map_path(row['path'],mappings)
        row['server_output_path']=map_path(row.get('output_path',''),mappings)
        if row.get('project_id') and row['state']=='translating':
            from app.services.translation_tasks import get_progress
            row['progress']=get_progress(row['project_id'])
    return {'items':rows,'counts':counts,'total':total,
            'view_counts':{name:sum(counts.get(s,0) for s in states) for name,states in views.items()}}


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

@app.post('/api/library/retry')
def library_retry(body:Retry):
    row=worker.store.get(body.path)
    if not row:raise HTTPException(404,'记录不存在')
    if row['state'] not in {'error','changed','missing','skipped','native_language'}:raise HTTPException(409,'当前任务不能重试')
    worker.save(row,state='waiting',reason='等待重新检查')
    worker.wake.set();return {'scheduled':True}
