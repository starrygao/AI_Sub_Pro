'use strict';
const $=id=>document.getElementById(id);
const names={waiting:'等待就绪',translating:'正在翻译',publishing:'等待保存',done:'已保存',skipped:'已有字幕',native_language:'中文原声',error:'需要处理',changed:'视频已变化',missing:'文件已移走',cancelled:'已停止'};
let status={},limit=100,offset=0,view='processed',requestId=0;
const views={processed:{states:['translating','publishing','done','error','changed','missing','cancelled'],all:'全部处理记录',hint:'正在处理、已完成及异常的记录。尚未处理的视频在“待处理”列表。',empty:'暂无处理记录。扫描到的视频会先进入“待处理”。'},waiting:{states:['waiting'],all:'全部待处理',hint:'已发现但尚未开始处理的视频；等待文件稳定或下载、整理、转码完成。',empty:'暂无待处理的视频。'},skipped:{states:['skipped','native_language'],all:'全部跳过记录',hint:'已有中文字幕或已确认中文原声，无需翻译。',empty:'暂无跳过记录。'}};
function selectView(next){view=next;offset=0;$('filter').replaceChildren(...[['',views[view].all],...views[view].states.map(s=>[s,names[s]])].map(([value,label])=>{const option=el('option',label);option.value=value;return option;}));$('filter').disabled=view==='waiting';for(const key of Object.keys(views))$('view-'+key).setAttribute('aria-pressed',String(key===view));$('list-hint').textContent=views[view].hint;$('tasks').replaceChildren();$('empty').hidden=false;$('empty').textContent='正在读取…';$('prev').hidden=true;$('more').hidden=true;$('page').textContent='';refresh();}
for(const key of Object.keys(views))$('view-'+key).onclick=()=>selectView(key);
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
async function request(path,body,method=body?'POST':'GET'){
  const r=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  if(r.status===401){location.replace('/login?next='+encodeURIComponent('/library'+location.hash));throw Error('请重新登录');}
  if(!r.ok){const e=Error(r.status===404?'记录不存在，可能已被移除。':'请求失败（'+r.status+'），请稍后重试。');e.status=r.status;throw e;}
  return r.json();
}
function api(path,body){return request('library/'+path,body);}
function error(message){$('error').textContent=message;$('error').hidden=!message;}

function renderProgress(row,body){
  if(!['translating','publishing'].includes(row.state))return;
  const stages={asr:'语音识别',translate:'翻译与复核',subtitle_extract:'提取字幕',filter:'整理字幕',export:'保存字幕'};
  const data=row.progress||{},hasValue=typeof data.progress==='number'&&Number.isFinite(data.progress);
  const value=hasValue?Math.max(0,Math.min(100,data.progress)):null;
  const box=el('div',undefined,'task-progress'),line=el('div'),bar=el('progress');
  line.append(el('span',row.state==='publishing'?'等待保存双语字幕':stages[data.stage]||'正在处理'),el('strong',hasValue?Math.round(value)+'%':'等待进度更新'));
  bar.max=100;bar.setAttribute('aria-label','任务进度');if(hasValue)bar.value=value;
  box.append(line,bar);body.append(box);
}
function renderRoots(s){
  const roots=s.server_roots||s.roots||[],groups=new Map();
  for(const path of roots){const split=path.lastIndexOf('/'),parent=path.slice(0,split)||'/',name=path.slice(split+1)||'/';if(!groups.has(parent))groups.set(parent,[]);groups.get(parent).push(name);}
  $('root-count').textContent=roots.length+' 个文件夹 · 包含子目录';
  const baseline=s.baseline||{};
  $('scope').textContent=s.new_only?(baseline.completed_at?'仅处理新增视频：无内嵌中文字幕、无外挂中文字幕，且非中文原声。已排除 '+Number(baseline.count||0).toLocaleString()+' 个现有视频（'+new Date(baseline.completed_at*1000).toLocaleString()+' 建立记录）。':'正在记录现有视频，完成前不会启动翻译。'):'检查监控目录内缺少中文字幕的视频；中文原声默认跳过。';
  $('roots').replaceChildren();
  for(const [parent,children] of groups){const group=el('div',undefined,'watch-root'),list=el('ul');group.append(el('code',parent));for(const child of children)list.append(el('li',child));group.append(list);$('roots').append(group);}
  if(!roots.length)$('roots').append(el('p','尚未读取到监控文件夹。','hint'));
}

function renderRows(rows,total){$('tasks').replaceChildren();$('empty').hidden=!!rows.length;$('empty').textContent=$('filter').value?'当前筛选没有任务。':views[view].empty;for(const row of rows){const article=el('article',undefined,'task'),body=el('div'),side=el('div',undefined,'task-side');body.append(el('h3',row.path.split('/').pop()));let reason=row.reason||'';if(row.progress?.message)reason+=' · '+row.progress.message;body.append(el('p',reason,'reason'));renderProgress(row,body);for(const [label,value] of [['视频：',row.server_source_path||row.path],[row.state==='done'?'已保存字幕：':'计划保存：',['skipped','native_language','cancelled'].includes(row.state)?'':row.server_output_path||row.output_path],['来源：',row.subtitle_source]]){if(value){const p=el('p',label,'path');p.append(el('span',value));body.append(p);}}const meta=row.metadata||{};if(meta.tmdb_id)body.append(el('div',(meta.show_title||'影视信息')+' · TMDB '+meta.tmdb_id+' · '+(meta.metadata_source||'Emby'),'metadata'));side.append(el('span',names[row.state]||row.state,'status '+row.state));if(row.project_id){const a=el('a','查看翻译详情 →');a.href='#project/'+encodeURIComponent(row.project_id);side.append(a);}if(['error','changed','missing','skipped','native_language'].includes(row.state)){const b=el('button','重新检查','secondary');b.onclick=async()=>{b.disabled=true;try{await api('retry',{path:row.path});await refresh();}catch(e){error(e.message);}finally{b.disabled=false;}};side.append(b);}article.append(body,side);$('tasks').append(article);}$('more').hidden=offset+rows.length>=total;$('prev').hidden=offset===0;$('page').textContent=rows.length?'第 '+(offset/limit+1)+' 页':'';}
async function refresh(){const request=++requestId;try{const [s,t]=await Promise.all([api('status'),api('tasks?limit='+limit+'&offset='+offset+'&view='+view+'&state='+encodeURIComponent($('filter').value))]);if(request!==requestId)return;status=s;window.LibraryPanels?.statusChanged(s);for(const key of Object.keys(views))$('count-'+key).textContent=t.view_counts[key]||0;$('enabled').textContent=s.enabled?'已开启':'已暂停';$('toggle').textContent=s.enabled?'暂停自动翻译':'开启自动翻译';$('toggle').disabled=false;$('auth').textContent=s.codex_logged_in?'已登录':'等待登录';$('pending').textContent=(s.counts.waiting||0)+' / '+((s.counts.translating||0)+(s.counts.publishing||0));$('done').textContent=s.counts.done||0;$('last').textContent=s.last_scan?new Date(s.last_scan*1000).toLocaleTimeString():'尚未扫描';$('explanation').textContent='文件持续稳定 '+s.quiet_seconds+' 秒后才开始；每 '+s.scan_interval+' 秒检查一次，单任务处理。'+(s.connections.emby?.transcoding?'Emby 正在转码，延后媒体处理。':'');$('connections').replaceChildren(...Object.entries(s.connections).map(([name,v])=>el('span',name+' · '+(v.ok?'已连接':'不可用'),'connection')));renderRoots(s);error(s.error||(!s.codex_logged_in?'Codex CLI 尚未登录，自动翻译不会启动。请在服务器运行 docker exec -it ai-sub-pro codex login --device-auth。':''));renderRows(t.items,t.total);}catch(e){if(request===requestId){error(e.message);window.LibraryPanels?.statusChanged(null);}}}
$('toggle').onclick=async()=>{try{await api('control',{enabled:!status.enabled});await refresh();}catch(e){error(e.message);}};
$('scan').onclick=async()=>{const b=$('scan');b.disabled=true;try{await api('scan',{});b.textContent='检查已排队';setTimeout(()=>{b.disabled=false;b.textContent='检查新文件';refresh();},2000);}catch(e){error(e.message);b.disabled=false;}};
$('filter').onchange=()=>{offset=0;refresh();};$('more').onclick=()=>{offset+=limit;refresh();};$('prev').onclick=()=>{offset=Math.max(0,offset-limit);refresh();};refresh();setInterval(refresh,5000);

$('logout').onclick=async()=>{const b=$('logout');b.disabled=true;try{const r=await fetch('/api/auth/logout',{method:'POST'});if(!r.ok&&r.status!==401)throw Error('退出失败，请重试。');location.replace('/login');}catch(e){error(e.message);b.disabled=false;}};
