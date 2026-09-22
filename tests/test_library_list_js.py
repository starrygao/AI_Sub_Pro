from tests.test_library_panels_js import run_js


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
