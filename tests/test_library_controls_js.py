from tests.test_library_panels_js import run_js
from tests.test_library_list_js import LIST_FIXTURE


FIXTURE=LIST_FIXTURE+r'''
const loadControls=async()=>{
 Object.assign($('task-cancel-dialog'),{open:false,showModal(){this.open=true},close(){this.open=false}});
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
