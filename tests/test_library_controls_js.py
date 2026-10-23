from tests.test_library_panels_js import run_js
from tests.test_library_list_js import LIST_FIXTURE


FIXTURE=LIST_FIXTURE+r'''
const loadControls=async()=>{
 Object.assign($('task-cancel-dialog'),{open:false,showModal(){this.open=true},close(){this.open=false}});
 Object.assign($('task-delete-dialog'),{open:false,showModal(){this.open=true},close(){this.open=false}});
 await loadList();
 const fetch=context.fetch;
 context.fetch=async(url,options={})=>url.endsWith('tasks/control')?{ok:true,status:200,json:async()=>{const body=JSON.parse(options.body);calls.push({url,body});return {results:body.items.map(r=>({path:r.path,ok:!r.path.includes('failed'),error:'正在保存，请重试'}))};}}:fetch(url,options);
 vm.runInContext(fs.readFileSync('app/static/js/library-controls.js','utf8'),context);await flush();
};
const control=(path,action)=>taskNodes().find(e=>e.getAttribute('data-task-path')===path&&e.getAttribute('data-task-action')===action);
'''


def test_row_controls_and_batch_selection_survive_polling_with_partial_results():
    run_js(FIXTURE+r'''
rows.push({path:'/video/one.mkv',state:'translating',control_revision:"a".repeat(64),available_actions:['pause','cancel']},
 {path:'/video/failed.mkv',state:'ready',control_revision:"b".repeat(64),available_actions:['pause','cancel']});
await loadControls();assert(control(rows[0].path,'pause'));assert(control(rows[0].path,'cancel'));
$('task-select-page').checked=true;await $('task-select-page').onchange();
assert.equal($('tasks-pause').disabled,false);assert.equal($('tasks-resume').disabled,true);
await context.refresh();assert.equal(control(rows[0].path,'select').checked,true);
await $('tasks-pause').onclick();
const sent=calls.find(c=>c.url.endsWith('tasks/control'));assert.equal(sent.body.items.length,2);assert.equal(sent.body.action,'pause');
assert.match($('task-action-feedback').textContent,/1 项.*1 项/);
assert.equal($('task-action-errors').hidden,false);assert.match($('task-selection-count').textContent,/已选 1 项/);
''')


def test_single_delete_has_named_confirmation_and_back_does_not_submit():
    run_js(FIXTURE+r'''
rows.push({path:'/video/completed.mkv',state:'done',control_revision:'a'.repeat(64),available_actions:['delete']});
await loadControls();
assert(control(rows[0].path,'delete'));assert(control(rows[0].path,'select'));
assert.equal($('tasks-delete').hidden,false);assert.equal($('tasks-delete').disabled,true);
assert.equal($('tasks-pause').hidden,true);assert.equal($('task-selection-hint').hidden,false);
await control(rows[0].path,'delete').onclick();
assert.equal($('task-delete-dialog').open,true);
assert.match($('task-delete-description').textContent,/1 项/);
assert.match($('task-delete-items').children[0].textContent,/completed.mkv/);
assert.equal(context.document.activeElement,$('task-delete-back'));
await $('task-delete-back').onclick();
assert(!calls.some(c=>c.url.endsWith('tasks/control')));
await control(rows[0].path,'delete').onclick();await $('task-delete-confirm').onclick();
assert.equal($('task-delete-dialog').open,false);
const sent=calls.find(c=>c.url.endsWith('tasks/control'));
assert.equal(sent.body.action,'delete');assert.equal(sent.body.items[0].path,rows[0].path);
''')


def test_batch_delete_supports_mixed_states_and_retains_failed_selections():
    run_js(FIXTURE+r'''
rows.push({path:'/video/running.mkv',state:'translating',control_revision:'a'.repeat(64),available_actions:['pause','cancel','delete']},
 {path:'/video/failed.mkv',state:'done',control_revision:'b'.repeat(64),available_actions:['delete']});
await loadControls();
const first=control(rows[0].path,'select');first.checked=true;first.onchange();
assert.equal($('task-select-page').indeterminate,true);
$('task-select-page').checked=true;await $('task-select-page').onchange();
assert.equal($('tasks-delete').disabled,false);assert.equal($('tasks-pause').disabled,true);
assert.equal($('task-selection-hint').hidden,true);
await $('tasks-delete').onclick();assert.equal($('task-delete-items').children.length,2);
await $('task-delete-confirm').onclick();
assert.match($('task-selection-count').textContent,/已选 1 项/);
assert.equal(control(rows[1].path,'select').checked,true);
assert.equal(control(rows[0].path,'select').checked,false);
assert.equal($('task-action-errors').hidden,false);
assert.match($('task-action-feedback').textContent,/视频与已有字幕保留/);
''')


def test_delete_network_failure_and_empty_page_leave_controls_consistent():
    run_js(FIXTURE+r'''
rows.push({path:'/video/completed.mkv',state:'done',control_revision:'a'.repeat(64),available_actions:['delete']});
await loadControls();
$('task-select-page').checked=true;await $('task-select-page').onchange();
const fetch=context.fetch;context.fetch=(url,options)=>url.endsWith('tasks/control')?Promise.reject(Error('offline')):fetch(url,options);
await $('tasks-delete').onclick();await $('task-delete-confirm').onclick();
assert.match($('task-action-feedback').textContent,/offline.*已保留选择/);
assert.equal($('tasks-delete').disabled,false);
await $('tasks-clear').onclick();rows.length=0;await context.refresh();
assert.equal($('task-select-page').disabled,true);assert.equal($('tasks-delete').disabled,true);
assert.equal($('tasks-clear').hidden,true);
''')


def test_deleting_last_page_returns_to_existing_tasks():
    run_js(FIXTURE+r'''
for(let i=0;i<101;i++)rows.push({path:'/video/'+i+'.mkv',state:'done',control_revision:'a'.repeat(64),available_actions:['delete']});
await loadControls();
const fetch=context.fetch;
context.fetch=async(url,options={})=>{
 if(url.endsWith('tasks/control')){
  const body=JSON.parse(options.body);const paths=body.items.map(r=>r.path);
  for(let i=rows.length-1;i>=0;i--)if(paths.includes(rows[i].path))rows.splice(i,1);
  return {ok:true,status:200,json:async()=>({results:paths.map(path=>({path,ok:true,state:'deleted'}))})};
 }
 if(url.includes('/tasks?')){
  const offset=Number(/[?&]offset=(\d+)/.exec(url)[1]);
  return {ok:true,status:200,json:async()=>({items:rows.slice(offset,offset+100),total:rows.length,view_counts:{processed:rows.length}})};
 }
 return fetch(url,options);
};
$('more').onclick();await flush();assert.equal($('tasks').children.length,1);
await control('/video/100.mkv','delete').onclick();await $('task-delete-confirm').onclick();
assert.equal($('tasks').children.length,100);assert.equal($('prev').hidden,true);assert.equal($('more').hidden,true);
''')


def test_cancel_requires_concrete_confirmation_and_stale_selection_is_removed():
    run_js(FIXTURE+r'''
rows.push({path:'/video/one.mkv',state:'paused',control_revision:"a".repeat(64),available_actions:['resume','cancel']});
await loadControls();assert(control(rows[0].path,'resume'));assert(!control(rows[0].path,'pause'));
await control(rows[0].path,'cancel').onclick();assert.equal($('task-cancel-dialog').open,true);
assert(!calls.some(c=>c.url.endsWith('tasks/control')));
await $('task-cancel-confirm').onclick();assert.equal($('task-cancel-dialog').open,false);
assert.equal(calls.find(c=>c.url.endsWith('tasks/control')).body.action,'cancel');
$('task-select-page').checked=true;await $('task-select-page').onchange();rows[0].control_revision="c".repeat(64);await context.refresh();
assert.match($('task-selection-count').textContent,/已选 0 项/);
''')
