"""Polling races use unresolved HTTP promises, without wall-clock sleeps."""
from tests.test_library_list_js import LIST_FIXTURE
from tests.test_library_panels_js import run_js


LIST_NETWORK = LIST_FIXTURE + r'''
const pending=[];
context.fetch=url=>new Promise((resolve,reject)=>pending.push({url,resolve,reject}));
const finishList=async(index,items)=>{
 for(const item of pending.slice(index,index+2))item.resolve({ok:true,status:200,json:async()=>item.url.includes('/status')?snapshot:{items,total:items.length,view_counts:{processed:1,waiting:1,skipped:0}}});
 await flush();
};
'''


def test_slow_list_poll_completes_then_later_polls_continue():
    run_js(LIST_NETWORK + r'''
await loadList();
// The first response is still pending when the next 5-second tick arrives.
intervals[0]();await flush();
await finishList(0,[{path:'/fixture/episode.mkv',state:'translating',progress:{progress:37}}]);
assert.match(taskText(),/37%/,'A successful response must render even after the next polling tick');
const next=pending.length;intervals[0]();await flush();
intervals[0]();await flush();
await finishList(next,[{path:'/fixture/episode.mkv',state:'translating',progress:{progress:48}}]);
assert.match(taskText(),/48%/,'Later successful polls must keep updating');
''')


def test_list_view_change_rejects_old_response_and_recovers_after_failure():
    run_js(LIST_NETWORK + r'''
await loadList();
const waiting=pending.length;$('view-waiting').onclick();await flush();
await finishList(waiting,[{path:'/fixture/new.mkv',state:'waiting'}]);
await finishList(0,[{path:'/fixture/old.mkv',state:'done'}]);
assert.match(taskText(),/new.mkv/);assert(!taskText().includes('old.mkv'));
const failed=pending.length;intervals[0]();await flush();
pending[failed].reject(Error('Temporary connection failure'));await flush();
assert.match($('error').textContent,/Temporary/);
const recovery=pending.length;intervals[0]();await flush();
await finishList(recovery,[{path:'/fixture/recovered.mkv',state:'waiting'}]);
assert.match(taskText(),/recovered.mkv/);assert.equal($('error').hidden,true);
''')


DETAIL_NETWORK = r'''
context.location.hash='#project/deadbeef';
const pending=[];
context.request=path=>path.endsWith('/subtitles')?Promise.resolve({blocks:[]}):new Promise((resolve,reject)=>pending.push({path,resolve,reject}));
const finishDetail=async(index,name,progress=48)=>{
 for(const item of pending.slice(index,index+4))item.resolve(item.path.endsWith('/quality-report')?{status:'missing'}:item.path.endsWith('/workflow-state')?{stages:{}}:item.path.endsWith('/progress')?{progress,message:'fixture running'}:{name,status:'processing'});
 await flush();
};
vm.runInContext(code,context);await flush();
'''


def test_slow_detail_poll_completes_then_later_polls_continue():
    run_js(DETAIL_NETWORK + r'''
intervals[0]();await flush();
await finishDetail(0,'First episode');
assert.equal($('project-content').hidden,false);
assert.equal($('project-title').textContent,'First episode');
const next=pending.length;intervals[0]();await flush();intervals[0]();await flush();
await finishDetail(next,'First episode',60);
assert.equal($('project-progress').value,60);
''')


def test_detail_route_change_rejects_old_response_and_recovers_after_failure():
    run_js(DETAIL_NETWORK + r'''
const newer=pending.length;navigate('#project/cafebabe');await flush();
await finishDetail(newer,'New episode');await finishDetail(0,'Old episode');
assert.equal($('project-title').textContent,'New episode');
const failed=pending.length;intervals[0]();await flush();
pending[failed].reject(Error('Temporary connection failure'));await flush();
assert.match($('project-error').textContent,/Temporary/);
const recovery=pending.length;intervals[0]();await flush();
await finishDetail(recovery,'New episode',72);
assert.equal($('project-progress').value,72);assert.equal($('project-error').hidden,true);
''')


def test_publishing_explains_why_subtitle_has_not_been_saved():
    run_js(LIST_FIXTURE + r'''
rows.push({path:'/fixture/episode.mkv',state:'publishing',reason:'等待媒体整理结束后保存',progress:{progress:100,message:'翻译完成'}});
await loadList();
const status=taskNodes().find(e=>e.className==='task-status');
assert.equal(descendants(status).find(e=>e.className==='reason').textContent,rows[0].reason);
rows[0].state='translating';rows[0].progress.message='正在复核';await context.refresh();
const active=taskNodes().find(e=>e.className==='task-status');
assert.equal(descendants(active).find(e=>e.className==='reason').textContent,'正在复核');
''')
