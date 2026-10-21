"""Exercise console state transitions without real credentials or model calls."""
import subprocess
from pathlib import Path


HARNESS = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class Element {
 constructor(tag='div',type=''){this.tagName=tag.toUpperCase();this.type=type;this.children=[];this.handlers={};this.hidden=false;this.value='';this.checked=false;this.disabled=false;this.textContent='';this.attrs={};}
 append(...items){this.children.push(...items);} replaceChildren(...items){this.children=items;}
 get options(){return this.children;} addEventListener(n,f){this.handlers[n]=f;}
 setAttribute(n,v){this.attrs[n]=String(v);} getAttribute(n){return this.attrs[n]??null;} removeAttribute(n){delete this.attrs[n];}
 focus(){context.document.activeElement=this;} reportValidity(){return true;}
}
const elements={};
for(const m of fs.readFileSync('app/static/library.html','utf8').matchAll(/<(\w+)[^>]*\bid="([^"]+)"([^>]*)>/g)){
 elements[m[2]]=new Element(m[1],/type="([^"]+)"/.exec(m[3])?.[1]||'');
 for(const attr of m[0].matchAll(/([\w-]+)="([^"]*)"/g))elements[m[2]].setAttribute(attr[1],attr[2]);
 elements[m[2]].hidden=/\bhidden\b/.test(m[3]);
}
const el=(tag,text)=>{const e=new Element(tag);e.textContent=text||'';return e;};
const $=id=>{assert(elements[id],'Unknown DOM id '+id);return elements[id];};
const handlers={},intervals=[],saved=[];
const config={translation:{primary_provider:'codex_cli',primary_model:'gpt-5.5',primary_effort:'medium',batch_size:20,semantic_qa_batch_size:40,full_doc_mode:true,polish_provider:'',polish_model:'',polish_effort:'auto',review_provider:'codex_cli',review_model:'gpt-5.5',review_effort:'medium'},asr:{backend:'faster_whisper',model_size:'small',beam_size:3},credentials_configured:{tmdb:true}};
let state={enabled:false,counts:{}},failSave=false,failModels=false;
const window={addEventListener:(name,fn)=>handlers[name]=fn};
const context={$,el,window,document:{title:'',hidden:false},location:{hash:'#settings'},setInterval:fn=>intervals.push(fn),
 api:async(path,body)=>{
  if(path!=='settings')return state;
  if(body){if(failSave)throw Error('Save failed');saved.push(JSON.parse(JSON.stringify(body)));for(const [section,values] of Object.entries(body))Object.assign(config[section],values);state.model_settings={pending:true,current_provider:'codex_cli',current_model:'gpt-5.5',current_effort:'medium',current_review_provider:'codex_cli',current_review_model:'gpt-5.5',current_review_effort:'medium'};}
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


def test_console_navigation_keeps_knowledge_settings_and_directory_dialog_reachable():
    run_js(r'''
context.location.hash='#tasks';
const originalRequest=context.request,originalApi=context.api;
context.request=async(path,...args)=>path==='knowledge'?{}:originalRequest(path,...args);
context.api=async(path,...args)=>{
 if(path==='knowledge')return {projects:0,terms:0,memory_entries:0,phrase_entries:0,memory_enabled:true,pending:[],storage:{knowledge:'/vol2/data/knowledge.json',data:'/vol2/data',projects:'/vol2/data/projects',temporary:'/vol2/tmp',models:'/vol2/models'}};
 if(path==='directories')return {watch:{current:['/vol2/media'],desired:['/vol2/media'],allowed:['/vol2/media'],pending:false,error:''},storage:{supported:true,current:{data:'/vol2/data',temporary:'/vol2/tmp',models:'/vol2/models'},desired:{data:'/vol2/data',temporary:'/vol2/tmp',models:'/vol2/models'},allowed:'/vol2',pending:false}};
 return originalApi(path,...args);
};
Object.assign($('directory-dialog'),{open:false,showModal(){this.open=true},close(){this.open=false}});
context.setTimeout=()=>1;context.clearTimeout=()=>{};context.refresh=()=>{};
vm.runInContext(fs.readFileSync('app/static/js/library-knowledge.js','utf8'),context);
vm.runInContext(fs.readFileSync('app/static/js/library-directories.js','utf8'),context);
vm.runInContext(code,context);
navigate('#knowledge');await flush();
assert.equal($('panel-knowledge').hidden,false);assert.equal($('panel-tasks').hidden,true);
assert.equal($('nav-knowledge').attrs['aria-current'],'page');
assert.match($('kb-overview').textContent,/0 部作品/);
$('kb-new').onclick();assert.equal($('kb-form').hidden,false);
navigate('#system');await flush();assert.equal($('panel-system').hidden,false);assert.equal($('panel-knowledge').hidden,true);
await $('storage-edit').onclick();assert.equal($('directory-dialog').open,true);
assert.equal($('storage-data').value,'/vol2/data');$('directory-close').onclick();
navigate('#settings');await flush();
assert.equal($('panel-settings').hidden,false);assert.equal($('settings-form').hidden,false);
navigate('#watch');await $('watch-edit').onclick();
assert.equal($('panel-watch').hidden,false);assert.equal($('panel-tasks').hidden,true);
assert.equal($('nav-system').attrs['aria-current'],'page');
assert.equal($('watch-paths').value,'/vol2/media');
assert.equal($('directory-dialog').open,true);
''')


def test_proxy_settings_retry_keep_drafts_and_save_only_changed_fields():
    run_js(r'''
context.location.hash='#proxy';let failLoad=true,proxyFailSave=false;
let proxy={current:{proxy_url:'http://127.0.0.1:7890',dashboard_url:''},desired:{proxy_url:'http://127.0.0.1:7890',dashboard_url:''},pending:false,source:'environment'};
context.api=async(path,body)=>{
 assert.equal(path,'proxy');
 if(failLoad)throw Error('Proxy unavailable');
 if(body){if(proxyFailSave)throw Error('Save failed');saved.push(JSON.parse(JSON.stringify(body)));Object.assign(proxy.desired,body);proxy.pending='proxy_url' in body;proxy.current.dashboard_url=proxy.desired.dashboard_url;}
 return structuredClone(proxy);
};
vm.runInContext(fs.readFileSync('app/static/js/library-proxy.js','utf8'),context);await flush();
assert.equal($('proxy-form').hidden,true);assert.equal($('proxy-fields').disabled,true);
assert.equal($('proxy-reload').hidden,false);assert.match($('proxy-error').textContent,/unavailable/);
failLoad=false;await $('proxy-reload').onclick();
assert.equal($('proxy-form').hidden,false);assert.equal($('proxy-save').disabled,true);
assert.equal($('proxy-dashboard-open').hidden,true);
$('proxy-dashboard').value='http://192.168.31.4:9097/ui/#/proxies';$('proxy-form').handlers.input();
await window.LibraryProxy.open(); // Navigation/refresh must retain an unsaved draft.
assert.equal($('proxy-dashboard').value,'http://192.168.31.4:9097/ui/#/proxies');
proxyFailSave=true;await $('proxy-form').onsubmit({preventDefault(){}});
assert.equal(saved.length,0);assert.match($('proxy-error').textContent,/Save failed/);
assert.equal(context.document.activeElement,$('proxy-error'));
assert.equal($('proxy-save').disabled,false);
proxyFailSave=false;await $('proxy-form').onsubmit({preventDefault(){}});
assert.deepEqual(saved,[{dashboard_url:'http://192.168.31.4:9097/ui/#/proxies'}]);
assert.equal($('proxy-dashboard-open').href,'http://192.168.31.4:9097/ui/#/proxies');
assert.equal($('proxy-save').disabled,true);
$('proxy-url').value='http://new-proxy:7890';$('proxy-form').handlers.input();
await $('proxy-form').onsubmit({preventDefault(){}});
assert.match($('proxy-feedback').textContent,/等待生效/);
assert.equal($('proxy-current').textContent,'http://127.0.0.1:7890');
$('proxy-url').value='http://draft-proxy:7890';$('proxy-form').handlers.input();
proxy.current.proxy_url=proxy.desired.proxy_url;proxy.pending=false;
intervals[0]();await flush();
assert.equal($('proxy-url').value,'http://draft-proxy:7890');
assert.equal($('proxy-current').textContent,'http://new-proxy:7890');
$('proxy-reset').onclick();assert.equal($('proxy-url').value,'http://new-proxy:7890');
assert.equal($('proxy-save').disabled,true);
''')


def test_polish_can_be_enabled_edited_reset_and_disabled_without_changing_primary():
    run_js(r'''
config.providers={claude_cli:{enabled:true}};
vm.runInContext(code,context);await flush();
assert.equal($('setting-polish-provider').value,'');
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


def test_delivered_project_explains_qa_errors_without_hiding_subtitles():
    run_js(r'''
context.location.hash='#project/deadbeef';
let unavailable=false;
context.request=async path=>{
 if(path.endsWith('/quality-report')){
  if(unavailable)throw Error('offline');
  return {status:'ok',summary:{quality_gate:{verdict:'passed_with_warnings'},conclusion:'字幕已可交付：1 项错误'},
   issues:[{block_id:319,severity:'error',message:'信任方向颠倒',source_text:'I do not owe you trust.',translation:'我没义务赢得你的信任'}]};
 }
 if(path.endsWith('/progress'))return {progress:100,message:'已完成'};
 if(path.endsWith('/workflow-state'))return {stages:{}};
 if(path.endsWith('/subtitles'))return {blocks:[{index:1,text:'source',translation:'译文'}]};
 return {id:'deadbeef',name:'已交付任务',status:'translated'};
};
vm.runInContext(code,context);await flush();
const flatten=node=>[node.textContent,...node.children.map(flatten)].join(' ');
let text=flatten($('project-facts'));
assert.match(text,/已交付.*质量问题/);assert.match(text,/1 项错误/);
assert.match(text,/源字幕第 319 条/);assert.match(text,/信任方向颠倒/);
assert.match(text,/I do not owe you trust/);assert.match(text,/我没义务赢得你的信任/);
const details=$('project-facts').children.flatMap(x=>x.children).find(x=>x.tagName==='DETAILS');
assert(details);assert.equal(details.children[0].tagName,'SUMMARY');
details.open=true;if(details.ontoggle)details.ontoggle();
intervals[0]();await flush();
assert.equal($('project-facts').children.flatMap(x=>x.children).find(x=>x.tagName==='DETAILS').open,true);
assert.equal($('subtitle-preview').children.length,1);
unavailable=true;intervals[0]();await flush();
text=flatten($('project-facts'));assert.match(text,/质量报告暂时无法读取/);
assert.doesNotMatch(text,/未发现质量问题/);assert.equal($('subtitle-preview').children.length,1);
''')


def test_model_sync_refreshes_all_three_dropdowns_without_resetting_unsaved_choices():
    run_js(r'''
config.translation.polish_provider='codex_cli';config.translation.polish_model='gpt-5.5';config.translation.polish_effort='medium';
config.translation.review_model='saved-review-model';config.translation.review_effort='xhigh';
vm.runInContext(code,context);await flush();
$('setting-model').value='fixture-model';$('setting-model').onchange();
$('setting-batch').value='31';$('settings-form').handlers.change();
const previous=context.request;let refreshes=0;
context.request=async(path,...args)=>{
 if(path==='models/codex_cli?refresh=true'){
  refreshes++;return {source:'remote',models:['new-model','gpt-5.5','fixture-model'],capabilities:{'new-model':{reasoning_efforts:['high']},'gpt-5.5':{reasoning_efforts:['medium']},'fixture-model':{reasoning_efforts:['low']}}};
 }
 return previous(path,...args);
};
await $('models-refresh').onclick();
assert.equal(refreshes,1); // Same provider shares one synchronization.
assert.equal($('setting-model').value,'fixture-model');assert.equal($('setting-batch').value,'31');
assert.equal($('setting-polish-model').value,'gpt-5.5');assert.equal($('setting-polish-effort').value,'medium');
assert.equal($('setting-review-model').value,'saved-review-model');assert.equal($('setting-review-effort').value,'xhigh');
assert($('setting-model').options.some(x=>x.value==='new-model'));
assert($('setting-polish-model').options.some(x=>x.value==='new-model'));
assert($('setting-review-model').options.some(x=>x.value==='new-model'));
$('setting-model').value='new-model';$('setting-model').onchange();
assert($('setting-effort').options.some(x=>x.value==='high'));
assert.match($('model-hint').textContent,/已同步/);assert.equal(saved.length,0);
context.request=async()=>{throw Error('offline')};
await $('models-refresh').onclick();
assert.equal($('setting-model').value,'new-model');assert.match($('settings-error').textContent,/同步失败/);
''')


def test_claude_is_selectable_without_api_key_and_switch_saves_provider_with_model():
    run_js(r'''
const original=context.request;
context.request=async path=>path.startsWith('models/claude_cli') ? {source:'static',models:['claude-opus-4-7'],capabilities:{'claude-opus-4-7':{reasoning_efforts:['high']}}} : original(path);
vm.runInContext(code,context);await flush();
assert($('setting-provider').options.some(x=>x.value==='claude_cli'));
assert($('setting-polish-provider').options.some(x=>x.value==='claude_cli'));
$('setting-provider').value='claude_cli';await $('setting-provider').onchange();
assert.equal($('setting-model').value,'claude-opus-4-7');
assert.equal($('setting-effort').value,'auto');
assert.match($('cli-login-hint').textContent,/claude auth login/);
await submit();await flush();
assert.deepEqual(saved,[{translation:{primary_provider:'claude_cli',primary_model:'claude-opus-4-7',primary_effort:'auto'}}]);
assert.equal($('setting-provider').value,'claude_cli');
assert.equal($('setting-model').value,'claude-opus-4-7');
''')


def test_primary_catalog_loading_failure_retry_and_reset_ignore_stale_response():
    run_js(r'''
let rejectModels,resolveModels;
const original=context.request;
context.request=path=>path==='models/claude_cli' ? new Promise((resolve,reject)=>{resolveModels=resolve;rejectModels=reject;}) : original(path);
vm.runInContext(code,context);await flush();
$('setting-provider').value='claude_cli';let pending=$('setting-provider').onchange();
assert.equal($('settings-save').disabled,true);await submit();assert.equal(saved.length,0);
rejectModels(Error('offline'));await pending;
assert.equal($('primary-reload').hidden,false);assert.equal($('settings-save').disabled,true);
pending=$('primary-reload').onclick();
$('settings-reset').onclick();await flush();
resolveModels({models:['claude-opus-4-7'],capabilities:{}});await pending;
assert.equal($('setting-provider').value,'codex_cli');
assert.equal($('setting-model').value,'gpt-5.5');
assert.equal($('primary-error').hidden,true);
assert.equal($('settings-save').disabled,true);
''')




def test_switching_omp_model_discards_pending_authentication_result():
    run_js(r'''
const original=context.request;let finish;
context.request=path=>{
 if(path.startsWith('models/omp_cli'))return Promise.resolve({models:['openai-codex/gpt-6-astra','other/model']});
 if(path.startsWith('settings/omp-cli/status'))return new Promise(resolve=>{finish=resolve;});
 return original(path);
};
vm.runInContext(code,context);await flush();
$('setting-provider').value='omp_cli';await $('setting-provider').onchange();
const pending=$('cli-check').onclick();
assert.equal($('cli-check').disabled,true);
$('setting-model').value='other/model';$('setting-model').onchange();
const resetMessage=$('cli-status').textContent;
finish({installed:true,logged_in:true,hint:'Previous model authenticated'});await pending;
assert.equal($('cli-status').textContent,resetMessage);
assert.equal($('cli-check').disabled,false);
assert.equal(saved.length,0);
''')


def test_review_saves_only_its_own_selection_and_reports_current_pending_settings():
    run_js(r'''
config.translation.polish_provider='codex_cli';config.translation.polish_model='fixture-model';config.translation.polish_effort='low';
vm.runInContext(code,context);await flush();
assert.equal($('setting-review-provider').value,'codex_cli');
assert(!$('setting-review-provider').options.some(x=>x.value===''));
$('setting-review-model').value='fixture-model';$('setting-review-model').onchange();
$('setting-review-effort').value='low';$('settings-form').handlers.change();
assert.equal($('setting-model').value,'gpt-5.5');assert.equal($('setting-effort').value,'medium');
assert.equal($('setting-polish-model').value,'fixture-model');assert.equal($('setting-polish-effort').value,'low');
await submit();await flush();
assert.deepEqual(saved,[{translation:{review_model:'fixture-model',review_effort:'low'}}]);
assert.match($('settings-availability').textContent,/当前初译：Codex CLI · gpt-5.5 · 中/);
assert.match($('settings-availability').textContent,/当前质量复核：Codex CLI · gpt-5.5 · 中/);
assert.match($('settings-feedback').textContent,/等待/);
window.LibraryPanels.statusChanged({model_settings:{pending:false,current_review_provider:'codex_cli',current_review_model:'fixture-model',current_review_effort:'low'}});
assert.match($('settings-feedback').textContent,/生效/);
$('setting-review-model').value='gpt-5.5';$('setting-review-model').onchange();
$('settings-reset').onclick();await flush();
assert.equal($('setting-review-model').value,'fixture-model');assert.equal($('setting-review-effort').value,'low');
assert.equal($('setting-model').value,'gpt-5.5');assert.equal($('setting-polish-model').value,'fixture-model');
assert.equal($('settings-save').disabled,true);
''')


def test_review_catalog_failure_retry_and_provider_switch_ignore_stale_responses():
    run_js(r'''
config.credentials_configured.deepseek=true;
const original=context.request;let resolveCatalog,rejectCatalog;
context.request=path=>path==='models/deepseek' ? new Promise((resolve,reject)=>{resolveCatalog=resolve;rejectCatalog=reject;}) : original(path);
vm.runInContext(code,context);await flush();
$('setting-review-provider').value='deepseek';let loading=$('setting-review-provider').onchange();
assert.equal($('review-loading').hidden,false);assert.equal($('setting-review-model').disabled,true);
assert.equal($('settings-save').disabled,true);await submit();assert.equal(saved.length,0);
rejectCatalog(Error('Review catalog offline'));await loading;
assert.equal($('review-reload').hidden,false);assert.match($('review-error').textContent,/offline/);
assert.equal($('settings-save').disabled,true);await submit();assert.equal(saved.length,0);
loading=$('review-reload').onclick();
resolveCatalog({models:['deepseek-review'],capabilities:{'deepseek-review':{reasoning_efforts:['high']}}});await loading;
assert.equal($('setting-review-model').value,'deepseek-review');assert.equal($('review-error').hidden,true);
assert.equal($('settings-save').disabled,false);
$('setting-review-effort').value='high';$('settings-form').handlers.change();await submit();await flush();
assert.deepEqual(saved,[{translation:{review_provider:'deepseek',review_model:'deepseek-review',review_effort:'high'}}]);
context.request=path=>path==='models/claude_cli' ? new Promise(resolve=>{resolveCatalog=resolve;}) : original(path);
$('setting-review-provider').value='claude_cli';loading=$('setting-review-provider').onchange();
$('settings-reset').onclick();await flush();
resolveCatalog({models:['obsolete-review'],capabilities:{}});await loading;
assert.equal($('setting-review-provider').value,'deepseek');assert.equal($('setting-review-model').value,'deepseek-review');
assert.equal($('setting-review-effort').value,'high');assert.equal($('review-error').hidden,true);
assert.equal($('settings-save').disabled,true);
assert.equal($('setting-model').value,'gpt-5.5');
''')


def test_review_provider_uses_catalog_models_and_efforts_without_primary_inheritance():
    run_js(r'''
const original=context.request;
context.request=async path=>path==='models/omp_cli' ? {models:['other/reviewer','openai-codex/gpt-6.1-sol'],capabilities:{'other/reviewer':{reasoning_efforts:['high','max']},'openai-codex/gpt-6.1-sol':{reasoning_efforts:['medium','xhigh']}}} : original(path);
vm.runInContext(code,context);await flush();
$('setting-review-provider').value='omp_cli';await $('setting-review-provider').onchange();
assert.equal($('setting-review-model').value,'other/reviewer');
assert.equal($('setting-review-effort').value,'auto');
assert($('setting-review-effort').options.some(x=>x.value==='max'));
$('setting-review-effort').value='max';$('settings-form').handlers.change();await submit();await flush();
assert.deepEqual(saved,[{translation:{review_provider:'omp_cli',review_model:'other/reviewer',review_effort:'max'}}]);
assert.equal($('setting-effort').value,'medium');
$('setting-review-model').value='openai-codex/gpt-6.1-sol';$('setting-review-model').onchange();
assert.equal($('setting-review-effort').value,'auto');
assert($('setting-review-effort').options.some(x=>x.value==='xhigh'));
''')


def test_cli_auth_includes_review_and_deduplicates_only_identical_omp_models():
    run_js(r'''
Object.assign(config.translation,{primary_provider:'omp_cli',primary_model:'translation/model',primary_effort:'medium',polish_provider:'omp_cli',polish_model:'translation/model',polish_effort:'xhigh',review_provider:'omp_cli',review_model:'review/model',review_effort:'xhigh'});
const original=context.request,calls=[];let finishReview;
context.request=path=>{
 if(path==='models/omp_cli')return Promise.resolve({models:['translation/model','review/model','new-review/model'],capabilities:{}});
 if(path.startsWith('settings/omp-cli/status')){
  calls.push(path);
  if(path.includes(encodeURIComponent('review/model')))return new Promise(resolve=>{finishReview=resolve;});
  return Promise.resolve({installed:true,logged_in:true,hint:'Translation credentials'});
 }
 return original(path);
};
vm.runInContext(code,context);await flush();
const checking=$('cli-check').onclick();
assert.deepEqual(calls,['settings/omp-cli/status?model=translation%2Fmodel','settings/omp-cli/status?model=review%2Fmodel']);
$('setting-review-model').value='new-review/model';$('setting-review-model').onchange();
const message=$('cli-status').textContent;
finishReview({installed:true,logged_in:true,hint:'Obsolete review credentials'});await checking;
assert.equal($('cli-status').textContent,message);
assert.equal($('cli-check').disabled,false);
assert.equal(saved.length,0);
''')
