"""Authenticated Docker entry point; desktop startup remains unchanged."""
import base64
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from app.main import app as desktop_app, lifespan as desktop_lifespan
from starlette.routing import WebSocketRoute
from app.config import DATA_DIR
from app.library.worker import LibraryWorker
from app.library.guard import map_path

CONFIG_PATH=Path(os.environ.get('AISUBPRO_LIBRARY_CONFIG','/config/library.json'))
worker=None
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
    async with desktop_lifespan(instance):
        worker=LibraryWorker(config,DATA_DIR)
        worker.start()
        try:yield
        finally:worker.stop()

app.router.lifespan_context=lifespan


@app.middleware('http')
async def authenticate(request:Request,call_next):
    if request.url.path=='/healthz':return JSONResponse({'status':'ok','server':True})
    token=getattr(app.state,'operator_token','')
    supplied=request.headers.get('x-aisub-key','')
    authorized=bool(token and supplied and hmac.compare_digest(token,supplied))
    if not authorized:
        try:
            scheme,encoded=request.headers.get('authorization','').split(' ',1)
            name,password=base64.b64decode(encoded,validate=True).decode().split(':',1)
            authorized=scheme.lower()=='basic' and password_matches(app.state.server_account,name,password)
        except (ValueError,KeyError,AttributeError):authorized=False
    if not authorized:return JSONResponse({'detail':'请使用服务器账户登录'},status_code=401,headers={'WWW-Authenticate':'Basic realm="AI Sub Pro Server", charset="UTF-8"'})
    # Basic credentials are sent automatically by browsers: require same-origin mutations.
    if request.method not in {'GET','HEAD','OPTIONS'}:
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'跨站请求已拒绝'},status_code=403)
    if request.url.path=='/':return RedirectResponse('/library')
    return await call_next(request)


@app.get('/library')
def library_page():return FileResponse(Path(__file__).parent/'static'/'library.html')


@app.get('/desktop')
def desktop_page():return FileResponse(Path(__file__).parent/'static'/'index.html')


@app.get('/api/library/status')
def library_status():return worker.status()


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
