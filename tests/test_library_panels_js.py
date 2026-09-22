"""Exercise console state transitions without real credentials or model calls."""
import subprocess
from pathlib import Path


HARNESS = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class Element {
 constructor(tag='div',type=''){this.tagName=tag.toUpperCase();this.type=type;this.children=[];this.handlers={};this.hidden=false;this.value='';this.checked=false;this.disabled=false;this.textContent='';this.attrs={};}
 append(...items){this.children.push(...items);} replaceChildren(...items){this.children=items;}
 get options(){return this.children;} addEventListener(n,f){this.handlers[n]=f;}
 setAttribute(n,v){this.attrs[n]=v;} removeAttribute(n){delete this.attrs[n];} focus(){} reportValidity(){return true;}
}
const elements={};
for(const m of fs.readFileSync('app/static/library.html','utf8').matchAll(/<(\w+)[^>]*\bid="([^"]+)"([^>]*)>/g)){
 elements[m[2]]=new Element(m[1],/type="([^"]+)"/.exec(m[3])?.[1]||'');
 elements[m[2]].hidden=/\bhidden\b/.test(m[3]);
}
const el=(tag,text)=>{const e=new Element(tag);e.textContent=text||'';return e;};
const $=id=>{assert(elements[id],'Unknown DOM id '+id);return elements[id];};
const handlers={},intervals=[],saved=[];
const config={translation:{primary_provider:'codex_cli',primary_model:'gpt-5.5',primary_effort:'medium',batch_size:20,semantic_qa_batch_size:40,full_doc_mode:true,polish_provider:'unchanged'},asr:{backend:'faster_whisper',model_size:'small',beam_size:3},credentials_configured:{tmdb:true}};
let state={enabled:false,counts:{}},failSave=false,failModels=false;
const window={addEventListener:(name,fn)=>handlers[name]=fn};
const context={$,el,window,document:{title:'',hidden:false},location:{hash:'#settings'},setInterval:fn=>intervals.push(fn),
 api:async()=>state,
 request:async(path,body)=>{
  if(path==='settings'&&body){if(failSave)throw Error('Save failed');saved.push(JSON.parse(JSON.stringify(body)));return {status:'ok'};}
  if(path==='settings')return structuredClone(config);
  if(path==='models/codex_cli'){if(failModels)throw Error('Models unavailable');return {models:['gpt-5.5','fixture-model'],capabilities:{'gpt-5.5':{reasoning_efforts:['medium','high']},'fixture-model':{reasoning_efforts:['low']}}};}
  throw Error('Unexpected request '+path);
 }};
vm.createContext(context);const code=fs.readFileSync('app/static/js/library-panels.js','utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const navigate=hash=>{context.location.hash=hash;handlers.hashchange();};
const submit=()=>$('settings-form').onsubmit({preventDefault(){}});
'''


def run_js(script):
    result = subprocess.run(
        ['node', '-e', HARNESS + '\n(async()=>{\n' + script + '\n})().catch(e=>{console.error(e);process.exit(1)});'],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_settings_preserve_drafts_recheck_running_tasks_and_save_only_changed_fields():
    run_js(r'''
vm.runInContext(code,context);await flush();
assert.equal($('settings-fields').disabled,false);
assert.equal($('settings-save').disabled,true);
$('setting-model').value='fixture-model';$('setting-model').onchange();$('settings-form').handlers.change();
assert.equal($('setting-effort').value,'auto'); // Unsupported effort must not follow another model.
assert.equal($('settings-save').disabled,false);
navigate('#tasks');navigate('#settings');await flush();
assert.equal($('setting-model').value,'fixture-model'); // Internal navigation retains draft.
state={enabled:false,counts:{translating:1}};await submit();
assert.equal(saved.length,0);assert.equal($('settings-fields').disabled,true);
assert.match($('settings-error').textContent,/任务状态已变化/);
state={enabled:false,counts:{}};window.LibraryPanels.statusChanged(state);
failSave=true;await submit();assert.equal(saved.length,0);assert.equal($('setting-model').value,'fixture-model');
failSave=false;await submit();
assert.deepEqual(saved,[{translation:{primary_model:'fixture-model',primary_effort:'auto'}}]);
assert.equal($('settings-save').disabled,true);assert.match($('settings-feedback').textContent,/已保存/);
window.LibraryPanels.statusChanged(null);assert.equal($('settings-fields').disabled,true);
''')


def test_settings_load_failure_can_retry_without_exposing_empty_editable_form():
    run_js(r'''
failModels=true;vm.runInContext(code,context);await flush();
assert.equal($('settings-form').hidden,true);assert.equal($('settings-reload').hidden,false);
failModels=false;await $('settings-reload').onclick();
assert.equal($('settings-form').hidden,false);assert.equal($('setting-model').value,'gpt-5.5');
assert.equal($('settings-save').disabled,true);
''')


def test_project_navigation_discards_stale_preview_and_retries_certification_conflict():
    run_js(r'''
context.location.hash='#project/deadbeef';
let resolveOld,conflict=true;
context.request=async path=>{
 const id=path.split('/')[1];
 if(path.endsWith('/progress'))return {progress:72,message:'正在复核'};
 if(path.endsWith('/workflow-state'))return {stages:{translate:{status:'succeeded'}}};
 if(path.endsWith('/subtitles')){
  if(id==='deadbeef')return new Promise(resolve=>resolveOld=resolve);
  if(conflict)throw Object.assign(Error('Delivery in progress'),{status:409});
  return {blocks:[{index:1,text:'New source',translation:'新译文'}]};
 }
 return {id,name:id,status:'processing',tmdb_id:1};
};
vm.runInContext(code,context);await flush();
navigate('#project/cafebabe');await flush();
assert.match($('subtitle-message').textContent,/质量检查/);
resolveOld({blocks:[{index:1,text:'Old source'}]});await flush();
assert.equal($('project-title').textContent,'cafebabe');
assert.equal($('subtitle-preview').children.length,0);
conflict=false;intervals[0]();await flush();
assert.equal($('subtitle-preview').children[0].children[1].children[1].textContent,'新译文');
assert.equal($('project-stages').children[0].children[1].textContent,'已完成');
navigate('#settings');await flush();assert.equal($('panel-project').hidden,true);
''')
