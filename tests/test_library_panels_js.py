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
const config={translation:{primary_provider:'codex_cli',primary_model:'gpt-5.5',primary_effort:'medium',batch_size:20,semantic_qa_batch_size:40,full_doc_mode:true,polish_provider:'',polish_model:'',polish_effort:'auto'},asr:{backend:'faster_whisper',model_size:'small',beam_size:3},credentials_configured:{tmdb:true}};
let state={enabled:false,counts:{}},failSave=false,failModels=false;
const window={addEventListener:(name,fn)=>handlers[name]=fn};
const context={$,el,window,document:{title:'',hidden:false},location:{hash:'#settings'},setInterval:fn=>intervals.push(fn),
 api:async(path,body)=>{
  if(path!=='settings')return state;
  if(body){if(failSave)throw Error('Save failed');saved.push(JSON.parse(JSON.stringify(body)));for(const [section,values] of Object.entries(body))Object.assign(config[section],values);state.model_settings={pending:true,current_model:'gpt-5.5',current_effort:'medium'};}
  return {settings:structuredClone(config),state:state.model_settings||{pending:false,current_model:'gpt-5.5'}};
 },
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


def test_settings_remain_editable_during_automatic_tasks_and_queue_only_changed_fields():
    run_js(r'''
state={enabled:true,counts:{translating:1}};
vm.runInContext(code,context);await flush();
assert.equal($('settings-fields').disabled,false);
assert.equal($('settings-save').disabled,true);
$('setting-model').value='fixture-model';$('setting-model').onchange();$('settings-form').handlers.change();
assert.equal($('setting-effort').value,'auto'); // Unsupported effort must not follow another model.
assert.equal($('settings-save').disabled,false);
navigate('#tasks');navigate('#settings');await flush();
assert.equal($('setting-model').value,'fixture-model'); // Internal navigation retains draft.
window.LibraryPanels.statusChanged(state);
assert.equal($('settings-fields').disabled,false);
failSave=true;await submit();assert.equal(saved.length,0);assert.equal($('setting-model').value,'fixture-model');
failSave=false;await submit();
assert.deepEqual(saved,[{translation:{primary_model:'fixture-model',primary_effort:'auto'}}]);
assert.equal($('settings-save').disabled,true);assert.match($('settings-feedback').textContent,/已保存/);
assert.match($('settings-availability').textContent,/当前任务|生效/);
assert.equal($('settings-fields').disabled,false);
window.LibraryPanels.statusChanged({...state,model_settings:{pending:false}});
assert.match($('settings-feedback').textContent,/生效/);
''')


def test_settings_load_failure_can_retry_without_exposing_empty_editable_form():
    run_js(r'''
failModels=true;vm.runInContext(code,context);await flush();
assert.equal($('settings-form').hidden,true);assert.equal($('settings-reload').hidden,false);
failModels=false;await $('settings-reload').onclick();
assert.equal($('settings-form').hidden,false);assert.equal($('setting-model').value,'gpt-5.5');
assert.equal($('settings-save').disabled,true);
''')


def test_polish_can_be_enabled_edited_reset_and_disabled_without_changing_primary():
    run_js(r'''
config.providers={claude_cli:{enabled:true}}; // A default flag does not prove the CLI is configured.
vm.runInContext(code,context);await flush();
assert.equal($('setting-polish-provider').value,'');
assert.deepEqual($('setting-polish-provider').options.map(option=>option.value),['','codex_cli']);
assert.equal($('polish-model-fields').hidden,true);
assert.equal($('settings-save').disabled,true);
$('setting-polish-provider').value='codex_cli';await $('setting-polish-provider').onchange();
assert.equal($('polish-model-fields').hidden,false);
$('setting-polish-model').value='fixture-model';$('setting-polish-model').onchange();
$('setting-polish-effort').value='low';$('settings-form').handlers.change();
assert.equal($('setting-model').value,'gpt-5.5');
await submit();
assert.deepEqual(saved,[{translation:{polish_provider:'codex_cli',polish_model:'fixture-model',polish_effort:'low'}}]);
$('setting-polish-model').value='gpt-5.5';$('setting-polish-model').onchange();
assert.equal($('setting-polish-effort').value,'auto');
$('settings-reset').onclick();await flush();
assert.equal($('setting-polish-model').value,'fixture-model');
assert.equal($('setting-polish-effort').value,'low');
$('setting-polish-provider').value='';await $('setting-polish-provider').onchange();await submit();
assert.deepEqual(saved[1],{translation:{polish_provider:'',polish_model:'',polish_effort:'auto'}});
assert.equal($('polish-model-fields').hidden,true);
''')


def test_polish_catalog_failure_blocks_save_and_stale_response_cannot_enable_it():
    run_js(r'''
config.credentials_configured.deepseek=true;
const originalRequest=context.request;let rejectCatalog,resolveCatalog;
context.request=path=>path==='models/deepseek' ? new Promise((resolve,reject)=>{resolveCatalog=resolve;rejectCatalog=reject;}) : originalRequest(path);
vm.runInContext(code,context);await flush();
$('setting-polish-provider').value='deepseek';let loading=$('setting-polish-provider').onchange();
assert.equal($('settings-save').disabled,true);await submit();assert.equal(saved.length,0);
rejectCatalog(Error('Catalog unavailable'));await loading;
assert.equal($('polish-reload').hidden,false);assert.match($('polish-error').textContent,/Catalog unavailable/);
assert.equal($('settings-save').disabled,true);
loading=$('polish-reload').onclick();
$('setting-polish-provider').value='';await $('setting-polish-provider').onchange();
resolveCatalog({models:['deepseek-chat'],capabilities:{}});await loading;
assert.equal($('setting-polish-provider').value,'');assert.equal($('setting-polish-model').value,'');
assert.equal($('polish-model-fields').hidden,true);assert.equal($('polish-error').hidden,true);
assert.equal($('settings-save').disabled,true); // Switching off restores the original settings.
''')


def test_existing_polish_provider_uses_its_own_catalog_and_preserves_saved_values():
    run_js(r'''
Object.assign(config.translation,{polish_provider:'deepseek',polish_model:'deepseek-chat',polish_effort:'auto'});
const originalRequest=context.request;
context.request=async path=>path==='models/deepseek' ? {models:['deepseek-chat'],capabilities:{}} : originalRequest(path);
vm.runInContext(code,context);await flush();
assert.equal($('setting-polish-provider').value,'deepseek');
assert.equal($('setting-polish-model').value,'deepseek-chat');
assert.equal($('setting-polish-effort').disabled,true);
assert.equal($('settings-save').disabled,true);
assert.equal($('setting-model').value,'gpt-5.5');
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
