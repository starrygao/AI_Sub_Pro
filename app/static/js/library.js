'use strict';
const $=id=>document.getElementById(id);
const names={waiting:'待检测',ready:'待翻译',historical:'旧媒体',translating:'正在翻译',publishing:'等待保存',done:'已保存',skipped:'已有字幕',native_language:'中文原声',error:'需要处理',changed:'视频已变化',missing:'文件已移走',cancelled:'已停止'};
let status={},limit=100,offset=0,view='processed',requestId=0,refreshPending=0;
let rowsSignature='',rowDetails=new Map();
const expandedPaths=new Set();
const views={processed:{states:['translating','publishing','done','error','changed','missing','cancelled'],all:'全部处理记录',hint:'正在处理、已完成及异常的记录。新发现文件先检测，通过后才进入待翻译。',empty:'暂无处理记录。新发现文件会先进入“待检测”。'},waiting:{states:['waiting'],all:'全部待检测',hint:'尚未确认是否需要翻译。检查下载、字幕和原声后，自动跳过或加入待翻译。',empty:'暂无待检测的视频。'},ready:{states:['ready'],all:'全部待翻译',hint:'已确认缺少中文字幕且需要翻译，等待名额；开始前再次检查文件与下载状态。',empty:'暂无确认需要翻译的视频。'},skipped:{states:['skipped','native_language','historical'],all:'全部跳过记录',hint:'已有中文字幕、中文原声或监控启用前的旧媒体。旧媒体仍可从 Emby 手动添加。',empty:'暂无跳过记录。'}};
function selectView(next){view=next;offset=0;$('filter').replaceChildren(...[['',views[view].all],...views[view].states.map(s=>[s,names[s]])].map(([value,label])=>{const option=el('option',label);option.value=value;return option;}));$('filter').disabled=['waiting','ready'].includes(view);for(const key of Object.keys(views))$('view-'+key).setAttribute('aria-pressed',String(key===view));$('list-hint').textContent=views[view].hint;rememberExpanded();rowsSignature='';$('tasks').replaceChildren();$('empty').hidden=false;$('empty').textContent='正在读取…';$('prev').hidden=true;$('more').hidden=true;$('page').textContent='';refresh();}
for(const key of Object.keys(views))$('view-'+key).onclick=()=>selectView(key);
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
async function request(path,body,method=body?'POST':'GET'){
  const r=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  if(r.status===401){location.replace('/login?next='+encodeURIComponent('/library'+location.hash));throw Error('请重新登录');}
  if(!r.ok){let detail;try{detail=(await r.json()).detail;}catch{}const e=Error(typeof detail==='string'?detail:r.status===404?'记录不存在，可能已被移除。':'请求失败（'+r.status+'），请稍后重试。');e.status=r.status;throw e;}
  return r.json();
}
function api(path,body){return request('library/'+path,body);}
function error(message){$('error').textContent=message;$('error').hidden=!message;}

function icon(name){const node=el('span',undefined,'icon icon-'+name);node.setAttribute('aria-hidden','true');return node;}
const stages={asr:'语音识别',translate:'翻译与复核',subtitle_extract:'正在提取字幕',filter:'整理字幕',export:'保存字幕'};
function progressLabel(row){return row.state==='done'?'字幕已保存':row.state==='publishing'?'等待保存':row.state==='translating'?(stages[row.progress?.stage]||'正在处理'):names[row.state]||row.state;}
function renderProgress(row,body){
  if(!['translating','publishing','done','cancelled','error','changed','missing'].includes(row.state)){
    body.append(el('p',row.state==='waiting'?'正在排队检测':row.state==='ready'?'等待翻译名额':'无需翻译','progress-idle'));return;
  }
  const data=row.progress||{},hasValue=typeof data.progress==='number'&&Number.isFinite(data.progress);
  const value=row.state==='done'?100:hasValue?Math.max(0,Math.min(100,data.progress)):null;
  const box=el('div',undefined,'task-progress'),line=el('div'),bar=el('progress');
  const stopped=['cancelled','error','changed','missing'].includes(row.state);
  const label=stopped?(names[row.state]+' · 最后进度'):progressLabel(row);
  line.append(el('span',label,'task-progress-label'),el('strong',value!==null?Math.round(value)+'%':stopped?'暂无记录':data.stage==='subtitle_extract'?'正在读取…':'等待进度更新'));
  bar.max=100;bar.setAttribute('aria-label',label);
  if(value!==null)bar.value=value;
  else {bar.value=0;bar.setAttribute('aria-hidden','true');box.setAttribute('data-unknown','true');}
  if(stopped)box.setAttribute('data-state','stopped');
  box.append(line,bar);body.append(box);
}
function renderRoots(s){
  const roots=s.server_roots||s.roots||[],groups=new Map();
  for(const path of roots){const split=path.lastIndexOf('/'),parent=path.slice(0,split)||'/',name=path.slice(split+1)||'/';if(!groups.has(parent))groups.set(parent,[]);groups.get(parent).push(name);}
  $('scope-summary').textContent=s.new_only?'自动处理新增；支持从 Emby 手动添加':'检查监控目录内缺少中文字幕的视频';
  $('root-count').textContent='监控 '+roots.length+' 个文件夹 · '+(s.new_only?'仅处理新增':'检查全部视频');
  const baseline=s.baseline||{};
  $('scope').textContent=s.new_only?(baseline.completed_at?'仅处理新增视频：无内嵌中文字幕、无外挂中文字幕，且非中文原声。已排除 '+Number(baseline.count||0).toLocaleString()+' 个现有视频（'+new Date(baseline.completed_at*1000).toLocaleString()+' 建立记录）。':'正在记录现有视频，完成前不会启动翻译。'):'检查监控目录内缺少中文字幕的视频；中文原声默认跳过。';
  $('roots').replaceChildren();
  for(const [parent,children] of groups){const group=el('div',undefined,'watch-root'),list=el('ul');group.append(el('code',parent));for(const child of children)list.append(el('li',child));group.append(list);$('roots').append(group);}
  if(!roots.length)$('roots').append(el('p','尚未读取到监控文件夹。','hint'));
}

function rememberExpanded(){
  for(const [path,details] of rowDetails){if(details.open)expandedPaths.add(path);else expandedPaths.delete(path);}
}
function taskTitle(row){
  const meta=row.metadata||{},filename=row.path.split('/').pop();
  const season=meta.season_number,episode=meta.episode_number;
  const validEpisode=Number.isInteger(episode)&&episode>0,validSeason=Number.isInteger(season)&&season>=0;
  const episodeLabel=validEpisode&&validSeason?'S'+String(season).padStart(2,'0')+'E'+String(episode).padStart(2,'0'):(filename.match(/\bS\d{1,3}E\d{1,4}\b/i)?.[0]||'').toUpperCase();
  return {title:meta.show_title?.trim()||filename,episode:episodeLabel,filename};
}
function taskArtwork(row){
  const box=el('div',undefined,'task-art'),fallback=el('div',undefined,'art-fallback');
  fallback.append(icon('photo'),el('span','暂无封面'));box.append(fallback);
  // Artwork is served by an authenticated same-origin endpoint. Never render arbitrary metadata URLs.
  const urls=[...new Set([row.backdrop_url,row.poster_url].filter(value=>typeof value==='string'&&value.startsWith('/api/library/artwork?')))];
  if(urls.length){
    const img=el('img');img.alt='';img.loading='lazy';img.decoding='async';img.src=urls.shift();
    img.onload=()=>{fallback.hidden=true;};img.onerror=()=>{if(urls.length){img.src=urls.shift();return;}img.hidden=true;fallback.hidden=false;};
    box.append(img);fallback.hidden=true;
  }
  return box;
}
function renderRows(rows,total){
  $('empty').hidden=!!rows.length;
  $('empty').textContent=$('filter').value?'当前筛选没有任务。':views[view].empty;
  const signature=JSON.stringify([view,offset,rows]);
  if(signature!==rowsSignature){
    rememberExpanded();
    const focused=document.activeElement;
    const focusPath=focused?.getAttribute?.('data-task-path'),focusAction=focused?.getAttribute?.('data-task-action');
    const articles=[],nextDetails=new Map();let restoreFocus=null;
    for(const row of rows){
      const article=el('article',undefined,'task'),identity=el('div',undefined,'task-identity'),taskStatus=el('div',undefined,'task-status'),side=el('div',undefined,'task-side');
      const meta=row.metadata||{},title=taskTitle(row);
      article.setAttribute('aria-label',title.title+(title.episode?' '+title.episode:''));
      identity.append(el('h3',title.title));
      if(title.episode)identity.append(el('span',title.episode,'task-episode'));
      const resolution=title.filename.match(/(?:^|[. _-])(2160p|1080p|720p|480p|4k)(?:[. _-]|$)/i)?.[1];
      const extension=title.filename.includes('.')?title.filename.split('.').pop().toUpperCase():'';
      const format=[resolution?.toUpperCase(),extension].filter(Boolean).join('  ·  ');
      if(format)identity.append(el('p',format,'task-format'));
      const reason=row.state==='translating'?(row.progress?.message||row.reason||''):(row.reason||row.progress?.message||'');
      const details=el('details',undefined,'task-files'),summary=el('summary','文件信息');
      const focusable=(node,action)=>{node.setAttribute('data-task-path',row.path);node.setAttribute('data-task-action',action);if(row.path===focusPath&&action===focusAction)restoreFocus=node;return node;};
      details.open=expandedPaths.has(row.path);details.append(focusable(summary,'files'));
      for(const [label,value] of [['视频',row.server_source_path||row.path],[row.state==='done'?'已保存字幕':'计划保存',['skipped','native_language','historical','cancelled'].includes(row.state)?'':row.server_output_path||row.output_path],['添加方式',row.manual_requested?'从 Emby 手动添加':'自动发现'],['字幕来源',row.subtitle_source],['处理说明',[row.reason,row.progress?.message].filter(Boolean).join(' · ')]]){
        if(value){const p=el('p',label,'path');p.append(el('span',value));details.append(p);}
      }
      if(meta.tmdb_id)details.append(el('div','TMDB '+meta.tmdb_id+' · '+(meta.metadata_source||'影视信息'),'metadata'));
      identity.append(details);nextDetails.set(row.path,details);
      const stateIcon=row.state==='done'?'done':['translating','publishing'].includes(row.state)?'running':['error','changed','missing'].includes(row.state)?'attention':row.state==='cancelled'?'stopped':'waiting';
      const badge=el('span',undefined,'status '+row.state);badge.append(icon(stateIcon),el('span',progressLabel(row)));taskStatus.append(badge);
      if(reason){const description=el('p',reason,'reason');description.title=reason;taskStatus.append(description);}
      article.append(taskArtwork(row),identity,taskStatus);renderProgress(row,article);
      if(row.project_id){const link=el('a','查看详情');link.href='#project/'+encodeURIComponent(row.project_id);link.append(icon('arrow'));side.append(focusable(link,'detail'));}
      if(['error','changed','missing','skipped','native_language'].includes(row.state)){
        const button=el('button','重新检查','secondary');
        button.onclick=async()=>{button.disabled=true;try{await api('retry',{path:row.path});rowsSignature='';await refresh();}catch(e){error(e.message);}finally{button.disabled=false;}};
        side.append(focusable(button,'retry'));
      }
      if(!side.children.length)side.append(el('span',row.state==='waiting'?'检测后决定是否翻译':row.state==='ready'?'按队列自动开始':row.state==='translating'?'处理中':'无需操作','hint'));
      article.append(side);articles.push(article);
    }
    $('tasks').replaceChildren(...articles);rowDetails=nextDetails;rowsSignature=signature;
    if(restoreFocus)restoreFocus.focus({preventScroll:true});
  }
  $('more').hidden=offset+rows.length>=total;$('prev').hidden=offset===0;
  $('page').textContent=rows.length&&total>limit?'第 '+(offset/limit+1)+' 页':'';
}
async function refresh(poll=false){if(poll&&refreshPending)return;const request=++requestId;refreshPending=request;try{const [s,t]=await Promise.all([api('status'),api('tasks?limit='+limit+'&offset='+offset+'&view='+view+'&state='+encodeURIComponent($('filter').value))]);if(request!==requestId)return;status=s;window.LibraryPanels?.statusChanged(s);for(const key of Object.keys(views))$('count-'+key).textContent=t.view_counts[key]||0;$('enabled').textContent=s.enabled?'已开启':'已暂停';$('toggle').textContent=s.enabled?'暂停自动翻译':'开启自动翻译';$('toggle').setAttribute('data-enabled',String(!!s.enabled));$('toggle').title=s.enabled?'自动翻译已开启，暂停后当前任务会继续完成':'自动翻译已暂停';$('toggle').disabled=false;$('auth').textContent=s.codex_logged_in?'已登录':'等待登录';$('pending').textContent=s.counts.ready||0;$('running').textContent=(s.counts.translating||0)+(s.counts.publishing||0);const attention=(s.counts.error||0)+(s.counts.changed||0)+(s.counts.missing||0);$('attention').textContent=attention;$('attention').setAttribute('data-active',String(attention>0));$('done').textContent=s.counts.done||0;$('last').textContent=s.last_scan?new Date(s.last_scan*1000).toLocaleTimeString():'尚未扫描';$('explanation').textContent='文件稳定 '+s.quiet_seconds+' 秒后检测；每 '+s.scan_interval+' 秒批量检查。检测与翻译排队独立，单任务翻译。'+(s.connections.emby?.transcoding?'Emby 正在转码，延后媒体处理。':'');const connections=Object.entries(s.connections),connected=connections.length>0&&connections.every(([,v])=>v.ok);$('connection-summary').textContent=connected?'服务连接正常':connections.length?'部分服务不可用':'暂无连接信息';$('connection-summary').setAttribute('data-ok',String(connected));$('connections').replaceChildren(...connections.map(([name,v])=>el('span',name+' · '+(v.ok?'已连接':'不可用'),'connection')));renderRoots(s);error(s.error||(!s.codex_logged_in?'Codex CLI 尚未登录，自动翻译不会启动。请在服务器运行 docker exec -it ai-sub-pro codex login --device-auth。':''));renderRows(t.items,t.total);}catch(e){if(request===requestId){error(e.message);window.LibraryPanels?.statusChanged(null);}}finally{if(refreshPending===request)refreshPending=0;}}
$('watch-expand').onclick=()=>{const open=$('watch-expand').getAttribute('aria-expanded')!=='true';$('watch-expand').setAttribute('aria-expanded',String(open));$('watch-content').hidden=!open;};
$('toggle').onclick=async()=>{const button=$('toggle');if(button.disabled)return;button.disabled=true;try{await api('control',{enabled:!status.enabled});await refresh();}catch(e){error(e.message);}finally{button.disabled=false;}};
$('scan').onclick=async()=>{const b=$('scan');b.disabled=true;try{await api('scan',{});b.textContent='检查已排队';setTimeout(()=>{b.disabled=false;b.textContent='检查新文件';refresh();},2000);}catch(e){error(e.message);b.disabled=false;}};
$('filter').onchange=()=>{offset=0;refresh();};$('more').onclick=()=>{offset+=limit;refresh();};$('prev').onclick=()=>{offset=Math.max(0,offset-limit);refresh();};refresh();setInterval(()=>refresh(true),5000);

$('logout').onclick=async()=>{const b=$('logout');b.disabled=true;try{const r=await fetch('/api/auth/logout',{method:'POST'});if(!r.ok&&r.status!==401)throw Error('退出失败，请重试。');location.replace('/login');}catch(e){error(e.message);b.disabled=false;}};
