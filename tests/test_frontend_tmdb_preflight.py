import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_js(body):
    script = """
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const ctx = {console, setTimeout, clearTimeout};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('app/static/js/model-settings.js','utf8') + ';' + fs.readFileSync('app/static/js/app.js','utf8'), ctx);
const candidate = {tmdb_id: 42, tmdb_type: 'tv', title: 'Example Series', original_language: 'en'};
const project = () => ({id: 'preflight', name: 'Example.mkv', status: 'created', tmdb_candidates: [candidate]});
function setup() {
 const state = ctx.app();
 const calls = [];
 state.newVideoPath = '/tmp/Example.mkv';
 state.ensureTranslationReadyForWorkflow = async () => true;
 for (const name of ['clearKbSuggestions','clearKbUsageTrace','clearQualityReport','clearTranslationStrategy','applyWorkflowDefaultsFromProject','connectWS','toast']) state[name] = () => {};
 state.setView = state.loadProjects = state.loadWorkflowState = async () => {};
 state.openProjectTaskSettings = state.openTaskSettings = async () => ({workflow_mode:'translate_only', asr_language:'auto', target_language:'简体中文'});
 state.api = async (url, method, body) => {
  calls.push({url, method, body});
  if (url === '/api/projects') return project();
  if (method === 'PATCH') return {...project(), ...body, tmdb_candidates: []};
  return {};
 };
 return {state, calls};
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const deadline = setTimeout(() => {console.error('Preflight did not settle'); process.exit(1)}, 5000);
(async () => {
""" + body + "\n})().then(() => clearTimeout(deadline)).catch(e => {console.error(e); process.exit(1)});"
    result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_quick_start_waits_for_tmdb_save_before_starting():
    run_js("""
const {state,calls}=setup();
const pending=state.quickStart(); await tick();
assert.equal(state.tmdbChoicePrompt,true);
assert.equal(calls.length,1);
await state.finishTmdbChoice(candidate); await pending;
assert.deepEqual(calls.map(c=>c.method),['POST','PATCH','POST']);
assert.equal(calls[1].body.tmdb_id,42);
assert.equal(calls[2].url,'/api/projects/preflight/start-full');
assert.equal(state.currentProject.tmdb_id,42);
""")


def test_cancel_preserves_unstarted_project_and_candidates():
    run_js("""
const {state,calls}=setup();
const pending=state.quickStart(); await tick();
assert.equal(state.tmdbChoicePrompt,true);
await state.finishTmdbChoice(null); await pending;
assert.equal(calls.length,1);
assert.equal(state.currentProject.status,'created');
assert.equal(state.currentProject.tmdb_candidates.length,1);
assert.equal(state.projectCreating,false);
""")


def test_failed_association_keeps_dialog_open_and_retry_starts_once():
    run_js("""
const {state,calls}=setup(); let fail=true; const api=state.api;
state.api=async (...args)=> {if(args[1]==='PATCH' && fail) throw Error('网络不可用'); return api(...args)};
const pending=state.quickStart(); await tick();
assert.equal(state.tmdbChoicePrompt,true);
await state.finishTmdbChoice(candidate);
assert.equal(state.tmdbChoicePrompt,true); assert.equal(state.tmdbChoiceError,'网络不可用');
assert.equal(calls.length,1);
fail=false; await state.finishTmdbChoice(candidate); await pending;
assert.equal(calls.filter(c=>c.url.endsWith('/start-full')).length,1);
""")


def test_explicit_skip_clears_candidates_before_translation():
    run_js("""
const {state,calls}=setup(); state.currentProject=project();
const pending=state.startTranslate(); await tick();
assert.equal(state.tmdbChoicePrompt,true); assert.equal(calls.length,0);
await state.finishTmdbChoice('skip'); await pending;
assert.equal(calls[0].method,'PATCH'); assert.deepEqual(Array.from(calls[0].body.clear),['tmdb_candidates']);
assert.equal(calls[1].url,'/api/projects/preflight/start-translate');
""")


def test_batch_waits_for_choice_and_cancel_does_not_launch():
    run_js("""
const {state,calls}=setup();
const pending=state.runBatchVideoPaths(['/tmp/Example.mkv','/tmp/Second.mkv']); await tick();
assert.equal(state.tmdbChoicePrompt,true); assert.equal(calls.length,1);
await state.finishTmdbChoice(null); await pending;
assert.equal(calls.length,1);
""")


def test_no_candidates_or_existing_association_needs_no_prompt():
    run_js("""
const {state}=setup();
assert.equal(await state.prepareTmdbBeforeStart({...project(),tmdb_candidates:[]}),true);
assert.equal(await state.prepareTmdbBeforeStart({...project(),tmdb_id:42}),true);
assert.equal(state.tmdbChoicePrompt,false);
""")


def test_existing_launch_paths_wait_for_tmdb_choice():
    for method,args in [('startFull',''),('startASR',''),('retryWorkflowStage',"'translate'"),('resumeWorkflow','')]:
        run_js("""
const {state,calls}=setup(); state.currentProject={...project(),source_type:'video',video_path:'/tmp/Example.mkv'};
const pending=state.METHOD(ARGS); await tick();
assert.equal(state.tmdbChoicePrompt,true); assert.equal(calls.length,0);
await state.finishTmdbChoice(null); await pending;
assert.equal(calls.length,0);
""".replace('METHOD',method).replace('ARGS',args))


def test_manual_association_during_processing_is_blocked_without_request():
    run_js("""
const {state,calls}=setup(); state.currentProject={...project(),status:'processing'};
let message=''; state.toast=text=>message=text;
await state.pickTmdbCandidate(candidate); await state.unlinkTmdb();
assert.equal(calls.length,0); assert.ok(message.includes('任务'));
""")


def test_double_click_during_save_does_not_start_twice():
    run_js("""
const {state,calls}=setup(); const original=state.api; let release;
state.api=async (...args)=> {if(args[1]==='PATCH') await new Promise(resolve=>release=resolve); return original(...args)};
const pending=state.quickStart(); await tick();
const save=state.finishTmdbChoice(candidate); await tick();
assert.equal(state.tmdbChoiceBusy,true);
await state.finishTmdbChoice('skip'); await state.finishTmdbChoice(null);
assert.equal(state.tmdbChoicePrompt,true); release(); await save; await pending;
assert.equal(calls.filter(c=>c.method==='PATCH').length,1);
assert.equal(calls.filter(c=>c.url.endsWith('/start-full')).length,1);
""")
