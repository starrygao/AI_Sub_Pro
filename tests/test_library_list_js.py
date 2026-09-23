from tests.test_library_panels_js import run_js


LIST_FIXTURE = r'''
const rows=[];
const snapshot={enabled:true,codex_logged_in:true,counts:{},connections:{},quiet_seconds:300,scan_interval:60,new_only:true,baseline:{count:12000,completed_at:1700000000},roots:[],server_roots:[]};
const calls=[];
context.document.getElementById=id=>elements[id];
context.document.createElement=tag=>new Element(tag);
context.setTimeout=()=>{};
context.fetch=async (url,options={})=>{
 calls.push({url,body:options.body?JSON.parse(options.body):null});
 return {ok:true,status:200,json:async()=>url.includes('/status')?snapshot:{items:rows,total:rows.length,view_counts:{processed:rows.length,waiting:0,skipped:0}}};
};
const descendants=e=>[e,...e.children.flatMap(descendants)];
const taskNodes=()=>descendants($('tasks'));
const taskText=()=>taskNodes().map(e=>e.textContent).join(' ');
const loadList=async()=>{vm.runInContext(fs.readFileSync('app/static/js/library.js','utf8'),context);await flush();};
'''


def test_task_title_prioritizes_work_identity_and_retains_filename_fallback():
    run_js(LIST_FIXTURE + r'''
rows.push({path:'/video/American.Hostage.S02E03.2160p.WEB-DL.mkv',state:'translating',project_id:'deadbeef',metadata:{show_title:'美国人质',season_number:2,episode_number:3},progress:{progress:37,stage:'translate'}});
await loadList();
assert(taskNodes().find(e=>e.tagName==='H3').textContent.includes('美国人质'));
assert.match(taskText(),/S0?2E0?3|第\s*2\s*季.*第\s*3\s*集/i);
rows[0].metadata={show_title:'测试电影'};await context.refresh();
assert(taskNodes().find(e=>e.tagName==='H3').textContent.includes('测试电影'));
assert(!/S00E00|第\s*0\s*季/.test(taskText()));
rows[0].metadata={};await context.refresh();
assert(taskNodes().find(e=>e.tagName==='H3').textContent.includes('American.Hostage.S02E03.2160p.WEB-DL.mkv'));
''')


def test_task_file_details_start_collapsed_and_keep_user_choice_on_refresh():
    run_js(LIST_FIXTURE + r'''
rows.push({path:'/video/Episode.mkv',server_source_path:'/vol2/media/Episode.mkv',server_output_path:'/vol2/media/Episode.srt',state:'translating',project_id:'deadbeef',progress:{progress:37,stage:'translate'}});
rows.push({path:'/video/Other.mkv',server_source_path:'/vol2/media/Other.mkv',state:'done',project_id:'cafebabe'});
await loadList();
const filesFor=path=>taskNodes().find(e=>e.tagName==='DETAILS'&&descendants(e).some(child=>child.textContent===path));
let details=filesFor('/vol2/media/Episode.mkv');
assert(details,'File information must be reachable through a disclosure');
assert(!details.open,'Long paths must start collapsed');
assert(descendants(details).some(e=>e.textContent==='/vol2/media/Episode.mkv'));
assert(descendants(details).some(e=>e.textContent==='/vol2/media/Episode.srt'));
const toggle=(node,open)=>{node.open=open;node.ontoggle?.({target:node});node.handlers.toggle?.({target:node});};
toggle(details,true);rows[0].progress.progress=48;rows.reverse();await context.refresh();
details=filesFor('/vol2/media/Episode.mkv');assert.equal(details.open,true);
assert(!filesFor('/vol2/media/Other.mkv').open,'A different row must not inherit disclosure state');
assert.match(taskText(),/48%/);
toggle(details,false);await context.refresh();
assert(!filesFor('/vol2/media/Episode.mkv').open);
''')


def test_unknown_active_progress_does_not_invent_a_percentage():
    run_js(LIST_FIXTURE + r'''
rows.push({path:'/video/Episode.mkv',state:'translating',project_id:'deadbeef',progress:null});
await loadList();
assert(!taskNodes().some(e=>e.textContent==='0%'));
assert.match(taskText(),/等待进度更新|暂无记录/);
rows[0].progress={progress:0,stage:'asr'};await context.refresh();
assert(taskNodes().some(e=>e.textContent==='0%'));
rows[0].state='cancelled';rows[0].progress={progress:72,stage:'translate'};await context.refresh();
assert.match(taskText(),/最后进度/);assert.match(taskText(),/72%/);
''')


def test_terminal_task_status_does_not_display_stale_running_message():
    run_js(LIST_FIXTURE + r'''
const row={path:'/video/Episode.mkv',state:'translating',project_id:'deadbeef',reason:'等待处理结果',progress:{progress:72,stage:'translate',message:'正在翻译第 1 批'}};
rows.push(row);await loadList();
const visibleReason=()=>{
 const status=taskNodes().find(e=>e.className==='task-status');
 return descendants(status).find(e=>e.className==='reason')?.textContent;
};
assert.equal(visibleReason(),'正在翻译第 1 批');
for(const [terminal,reason] of [['cancelled','用户已停止任务'],['error','保存字幕失败'],['done','双语字幕已保存']]){
 row.state=terminal;row.reason=reason;await context.refresh();
 assert.equal(visibleReason(),reason,'Terminal task status must describe the final state');
 const files=taskNodes().find(e=>e.tagName==='DETAILS');
 assert(descendants(files).some(e=>String(e.textContent).includes('正在翻译第 1 批')),'The full historical message remains available in file details');
}
''')


def test_refresh_preserves_unchanged_rows_and_keyboard_focus_when_progress_changes():
    run_js(LIST_FIXTURE + r'''
rows.push({path:'/video/Episode.mkv',state:'error',project_id:'deadbeef',progress:{progress:37,stage:'translate'}});
await loadList();
const action=name=>taskNodes().find(e=>e.getAttribute('data-task-path')==='/video/Episode.mkv'&&e.getAttribute('data-task-action')===name);
const initial=$('tasks').children[0],retry=action('retry');
assert(retry);retry.focus();await context.refresh();
assert.equal($('tasks').children[0],initial,'Polling unchanged data must retain the existing DOM');
assert.equal(context.document.activeElement,retry);
rows[0].progress.progress=48;await context.refresh();
assert.equal(context.document.activeElement,action('retry'));
assert.equal(context.document.activeElement.getAttribute('data-task-path'),'/video/Episode.mkv');
action('files').focus();rows[0].progress.progress=49;await context.refresh();
assert.equal(context.document.activeElement,action('files'));
action('detail').focus();rows[0].progress.progress=50;await context.refresh();
assert.equal(context.document.activeElement,action('detail'));
''')


def test_monitoring_directory_disclosure_is_reachable_and_stays_open_on_refresh():
    run_js(LIST_FIXTURE + r'''
snapshot.server_roots=['/vol2/media/电视剧'];
await loadList();
assert.equal($('watch-content').hidden,true);
assert.equal($('watch-expand').getAttribute('aria-expanded'),'false');
$('watch-expand').onclick();
assert.equal($('watch-content').hidden,false);
assert.equal($('watch-expand').getAttribute('aria-expanded'),'true');
await context.refresh();
assert.equal($('watch-content').hidden,false);
assert(descendants($('roots')).some(e=>e.textContent==='/vol2/media'));
assert(descendants($('roots')).some(e=>e.textContent==='电视剧'));
$('watch-expand').onclick();
assert.equal($('watch-content').hidden,true);
assert.equal($('watch-expand').getAttribute('aria-expanded'),'false');
''')


def test_list_views_keep_server_filters_retry_and_project_detail_actions():
    run_js(LIST_FIXTURE + r'''
const records={
 processed:[{path:'/video/Failed.mkv',state:'error',project_id:'deadbeef',progress:{progress:12}},{path:'/video/Stopped.mkv',state:'cancelled',project_id:'cafebabe',progress:{progress:52}}],
 waiting:[{path:'/video/Waiting.mkv',state:'waiting'}],
 skipped:[{path:'/video/Chinese.mkv',state:'native_language'}],
};
context.fetch=async (url,options={})=>{
 calls.push({url,body:options.body?JSON.parse(options.body):null});
 const requested=/[?&]view=([^&]+)/.exec(url)?.[1]||'processed';
 return {ok:true,status:200,json:async()=>url.includes('/status')?snapshot:{items:records[requested],total:records[requested].length,view_counts:{processed:2,waiting:1,skipped:1}}};
};
await loadList();
assert(taskNodes().some(e=>e.href==='#project/deadbeef'));
assert(taskNodes().some(e=>e.href==='#project/cafebabe'));
let retry=taskNodes().filter(e=>e.tagName==='BUTTON'&&e.textContent==='重新检查');
assert.equal(retry.length,1,'Stopped tasks must not expose retry');
await retry[0].onclick();
assert.deepEqual(calls.filter(call=>call.url==='/api/library/retry').map(call=>call.body),[{path:'/video/Failed.mkv'}]);
$('view-waiting').onclick();await flush();
assert(calls.some(call=>call.url.includes('view=waiting')));assert.equal($('filter').disabled,true);
assert.match(taskText(),/Waiting/);assert(!taskText().includes('Failed'));
$('view-skipped').onclick();await flush();
assert(calls.some(call=>call.url.includes('view=skipped')));assert.equal($('filter').disabled,false);
assert.match(taskText(),/Chinese/);assert.equal(taskNodes().filter(e=>e.tagName==='PROGRESS').length,0);
assert.equal(taskNodes().filter(e=>e.tagName==='BUTTON'&&e.textContent==='重新检查').length,1);
$('view-processed').onclick();await flush();
assert.match(taskText(),/Failed/);assert.equal($('filter').value,'');
''')


def test_pausing_automation_does_not_send_a_running_task_cancel_request():
    run_js(LIST_FIXTURE + r'''
rows.push({path:'/video/Episode.mkv',state:'translating',project_id:'deadbeef',progress:{progress:72,stage:'translate'}});
snapshot.counts={translating:1};
const originalFetch=context.fetch;
context.fetch=async(url,options={})=>{
 if(url==='/api/library/control'){
  const body=JSON.parse(options.body);calls.push({url,body});snapshot.enabled=body.enabled;
  return {ok:true,status:200,json:async()=>snapshot};
 }
 return originalFetch(url,options);
};
await loadList();
assert.match($('toggle').textContent,/暂停自动翻译/);
await $('toggle').onclick();
assert.deepEqual(calls.filter(call=>call.body),[{url:'/api/library/control',body:{enabled:false}}]);
assert.match($('toggle').textContent,/开启自动翻译/);
assert(taskNodes().some(e=>e.textContent==='72%'));
assert(!calls.some(call=>/cancel|stop/.test(call.url)));
''')


def test_task_list_shows_live_progress_and_visible_host_monitoring_folders():
    run_js(r'''
const rows=[{path:'/video/Episode.mkv',state:'translating',project_id:'deadbeef',progress:{progress:72,stage:'translate',message:'正在复核 40/156'}}];
const snapshot={enabled:true,codex_logged_in:true,counts:{translating:1},connections:{},quiet_seconds:300,scan_interval:60,new_only:true,baseline:{count:12000,completed_at:1700000000},roots:['/video/电视剧/日番'],server_roots:['/vol2/1000/video/电视剧/日番']};
context.document.getElementById=id=>elements[id];
context.document.createElement=tag=>new Element(tag);
context.fetch=async url=>({ok:true,status:200,json:async()=>url.includes('/status')?snapshot:{items:rows,total:1,view_counts:{processed:1}}});
context.setTimeout=()=>{};
vm.runInContext(fs.readFileSync('app/static/js/library.js','utf8'),context);await flush();
const descendants=e=>[e,...e.children.flatMap(descendants)];
let progress=descendants($('tasks')).find(e=>e.tagName==='PROGRESS');
assert.equal(progress.value,72);assert.equal(progress.max,100);
assert(descendants($('tasks')).some(e=>String(e.textContent).includes('72%')));
assert(descendants($('roots')).some(e=>e.textContent==='/vol2/1000/video/电视剧'));
assert(descendants($('roots')).some(e=>e.textContent==='日番'));
assert.match($('scope').textContent,/仅处理新增/);
rows[0].progress.progress=83;await context.refresh();
progress=descendants($('tasks')).find(e=>e.tagName==='PROGRESS');assert.equal(progress.value,83);
rows[0].state='cancelled';await context.refresh();
assert.equal(descendants($('tasks')).find(e=>e.tagName==='PROGRESS').value,83);
assert(descendants($('tasks')).some(e=>String(e.textContent).includes('已停止')));
assert(!descendants($('tasks')).some(e=>e.textContent==='重新检查'));
rows[0].progress=null;await context.refresh();
assert(descendants($('tasks')).some(e=>e.textContent==='暂无记录'));
assert(!descendants($('tasks')).some(e=>e.textContent==='0%'));
rows[0].progress={progress:0};await context.refresh();
assert(descendants($('tasks')).some(e=>e.textContent==='0%'));
rows[0].state='done';await context.refresh();
assert.equal(descendants($('tasks')).find(e=>e.tagName==='PROGRESS').value,100);
assert(descendants($('tasks')).some(e=>e.textContent==='100%'));
''')


def test_extraction_shows_its_own_progress_before_a_project_exists():
    run_js(LIST_FIXTURE + r'''
rows.push({path:'/video/Episode.mkv',state:'translating',reason:'正在提取字幕',project_id:null,progress:{progress:63,stage:'subtitle_extract',message:'正在提取字幕 · 已用 20 秒'}});
await loadList();
assert.match(taskText(),/提取字幕/);assert.match(taskText(),/63%/);assert.match(taskText(),/已用 20 秒/);
assert(!/等待就绪|无需操作/.test(taskText()));
rows[0].progress.progress=null;await context.refresh();
assert.match(taskText(),/正在读取/);assert(!/0%/.test(taskText()));
''')
