"""Knowledge edits must preserve concurrent candidates and report real acceptance."""
import copy
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_knowledge_api import patched_kb_file
from tests.test_library_panels_js import run_js


@pytest.fixture
def knowledge_client(tmp_project_dir, patched_kb_file):
    from app.api.knowledge import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _create(client, category='characters'):
    response = client.put('/api/knowledge/projects/example', json={
        'key': 'example', 'show_title': 'Example', 'tmdb_id': 42, 'tmdb_type': 'tv',
        category: [{'source': 'Maya', 'target': '旧译名', 'notes': '原有说明'}],
    })
    assert response.status_code == 200
    return client.get('/api/knowledge/projects/example').json()


def _candidate(tmp_project_dir, client, target='新审定译名'):
    from app.engines.kb_suggestions import extract_kb_suggestions, save_suggestions
    from app.engines.knowledge import _get_singleton
    from app.utils.project_store import atomic_write_json
    project = {'id': 'deadbeef', 'name': 'Example.S01E01', 'show_title': 'Example',
               'tmdb_id': 42, 'tmdb_type': 'tv', 'cast': [{'character': 'Maya'}]}
    pdir = tmp_project_dir / project['id']
    atomic_write_json(pdir / 'project.json', project)
    suggestions = extract_kb_suggestions(project, [{'text': 'Maya has arrived.'}],
                                         _get_singleton().select_for_project(project))
    candidate = next(item for item in suggestions if item.source == 'Maya')
    save_suggestions(pdir / 'kb_suggestions.json', suggestions)
    response = client.post(f'/api/knowledge/projects/deadbeef/suggestions/{candidate.id}/status',
                           json={'status': 'accepted', 'target': target})
    return project, candidate, response


@pytest.mark.parametrize('existing_category', ['characters', 'places'])
def test_confirmed_existing_source_updates_the_term_used_by_the_next_prompt(
    knowledge_client, tmp_project_dir, monkeypatch, existing_category,
):
    from app.engines import translator
    _create(knowledge_client, existing_category)
    project, candidate, response = _candidate(tmp_project_dir, knowledge_client)
    assert response.status_code == 200 and response.json()['suggestion']['status'] == 'accepted'
    stored = knowledge_client.get('/api/knowledge/projects/example').json()
    matches = [entry for category in ('characters', 'places', 'brands', 'slang')
               for entry in stored[category] if entry['source'].casefold() == 'maya']
    assert len(matches) == 1
    assert matches[0]['target'] == '新审定译名'
    assert matches[0]['notes'] == '原有说明'
    monkeypatch.setattr(translator, 'get_provider', lambda *args: Mock())
    engine = translator.SubtitleTranslator({'translation': {
        'primary_provider': 'codex_cli', 'use_translation_memory': False, 'use_phrase_library': False,
    }})
    prompt = engine._build_prompt('简体中文', project, {}, [], [], items=[{'id': 1, 'original': 'Maya has arrived.'}])
    assert '新审定译名' in prompt and '旧译名' not in prompt


def test_stale_full_replacement_is_rejected_but_current_and_legacy_edits_work(knowledge_client):
    original = _create(knowledge_client)
    changed = copy.deepcopy(original)
    changed['characters'].append({'source': 'Bob', 'target': '鲍勃'})
    assert knowledge_client.put('/api/knowledge/projects/example', json={'key': 'example', **changed}).status_code == 200
    stale = {'key': 'example', **original, 'expected_state': original,
             'style_notes': {'tone': 'concise'}}
    response = knowledge_client.put('/api/knowledge/projects/example', json=stale)
    assert response.status_code == 409
    latest = knowledge_client.get('/api/knowledge/projects/example').json()
    assert {entry['source'] for entry in latest['characters']} == {'Maya', 'Bob'}
    assert latest['style_notes']['tone'] == ''
    current = {'key': 'example', **latest, 'expected_state': latest,
               'style_notes': {'tone': 'concise'}}
    assert knowledge_client.put('/api/knowledge/projects/example', json=current).status_code == 200
    assert knowledge_client.get('/api/knowledge/projects/example').json()['style_notes']['tone'] == 'concise'


def test_expected_record_deleted_before_save_is_not_recreated(knowledge_client):
    original = _create(knowledge_client)
    assert knowledge_client.delete('/api/knowledge/projects/example').status_code == 200
    response = knowledge_client.put('/api/knowledge/projects/example', json={
        'key': 'example', **original, 'expected_state': original,
    })
    assert response.status_code == 409
    assert knowledge_client.get('/api/knowledge/projects/example').status_code == 404


def test_failed_knowledge_save_does_not_mark_candidate_accepted(knowledge_client, tmp_project_dir, monkeypatch):
    from app.engines.knowledge import _get_singleton
    _create(knowledge_client)
    monkeypatch.setattr(_get_singleton(), 'save', Mock(side_effect=OSError('fixture disk full')))
    with pytest.raises(OSError, match='fixture disk full'):
        _candidate(tmp_project_dir, knowledge_client)
    suggestions = knowledge_client.get('/api/knowledge/projects/deadbeef/suggestions').json()['suggestions']
    assert next(item for item in suggestions if item['source'] == 'Maya')['status'] == 'pending'
    assert knowledge_client.get('/api/knowledge/projects/example').json()['characters'][0]['target'] == '旧译名'


KNOWLEDGE_UI = r'''
let kb={example:{show_title:'Example',tmdb_id:42,tmdb_type:'tv',characters:[{source:'Bob',target:'鲍勃'}],places:[],brands:[],slang:[],style_notes:{tone:'',perspective:'',rules:[]}}};
let candidate={id:'character:maya',source:'Maya',target:'玛雅',category:'characters',status:'pending'},lastPut;
context.request=async(path,body,method)=>{
 if(path==='knowledge')return structuredClone(kb);
 if(path==='knowledge/projects/deadbeef/suggestions')return {suggestions:[structuredClone(candidate)]};
 if(path==='knowledge/projects/deadbeef/usage-trace')return {};
 if(path==='knowledge/projects/deadbeef/suggestions/character%3Amaya/status'){
  candidate.status=body.status;candidate.target=body.target;
  kb.example.characters.push({source:'Maya',target:body.target});return {ok:true,suggestion:structuredClone(candidate)};
 }
 if(path==='knowledge/projects/example'&&method==='PUT'){
  lastPut=structuredClone(body);
  if(JSON.stringify(body.expected_state)!==JSON.stringify(kb.example)){const error=Error('知识库已更新，请撤销更改后重新编辑');error.status=409;throw error;}
  const {key,expected_state,...project}=body;kb.example=structuredClone(project);return {ok:true,project};
 }
 throw Error('Unexpected '+path);
};
context.api=async()=>({projects:1,terms:kb.example.characters.length,memory_entries:0,phrase_entries:0,memory_enabled:true,pending:[],storage:{}});
vm.runInContext(fs.readFileSync('app/static/js/library-knowledge.js','utf8'),context);
context.location.hash='#knowledge';await window.LibraryKnowledge.open();$('kb-list').children[0].onclick();
assert.equal($('kb-terms').children.length,1);
const accept=async()=>{context.location.hash='#project/deadbeef';await window.LibraryKnowledge.project('deadbeef');await $('project-kb-suggestions').children[0].children[2].onclick();assert.equal(kb.example.characters.length,2);};
'''


def test_clean_editor_refreshes_after_candidate_acceptance_and_preserves_the_new_term():
    run_js(KNOWLEDGE_UI + r'''
await accept();
context.location.hash='#knowledge';await window.LibraryKnowledge.open();
assert.equal($('kb-terms').children.length,2);
$('kb-tone').value='concise';$('kb-form').handlers.input();
await $('kb-form').onsubmit({preventDefault(){}});
assert.equal(lastPut.characters.length,2);assert.equal(kb.example.characters.length,2);
assert.equal(kb.example.style_notes.tone,'concise');
assert.equal($('kb-error').hidden,true);assert.match($('kb-feedback').textContent,/已保存/);
''')


def test_dirty_editor_keeps_draft_and_original_expectation_then_can_reload_after_conflict():
    run_js(KNOWLEDGE_UI + r'''
$('kb-tone').value='draft tone';$('kb-form').handlers.input();
await accept();
context.location.hash='#knowledge';await window.LibraryKnowledge.open();
assert.equal($('kb-tone').value,'draft tone');assert.equal($('kb-terms').children.length,1);
await $('kb-form').onsubmit({preventDefault(){}});
assert.equal(lastPut.expected_state.characters.length,1);
assert.equal(kb.example.characters.length,2);assert.equal($('kb-tone').value,'draft tone');
assert.equal($('kb-error').hidden,false);assert.match($('kb-error').textContent,/更新/);
$('kb-reset').onclick();
assert.equal($('kb-terms').children.length,2);assert.equal($('kb-tone').value,'');
$('kb-tone').value='revised';$('kb-form').handlers.input();await $('kb-form').onsubmit({preventDefault(){}});
assert.equal(lastPut.expected_state.characters.length,2);assert.equal(kb.example.style_notes.tone,'revised');
''')


@pytest.mark.parametrize('stale_result', ['success', 'failure'])
def test_pre_save_read_cannot_overwrite_successful_save_or_its_feedback(stale_result):
    run_js(KNOWLEDGE_UI + "\nconst staleResult=" + repr(stale_result) + ";\n" + r'''
const oldState=structuredClone(kb),originalRequest=context.request;
let resolveRead,rejectRead,readCount=0;
context.request=(path,...args)=>{
 if(path==='knowledge'&&++readCount===1)return new Promise((resolve,reject)=>{resolveRead=resolve;rejectRead=reject;});
 return originalRequest(path,...args);
};
const reading=window.LibraryKnowledge.open();await flush();
$('kb-tone').value='Successfully saved tone';$('kb-form').handlers.input();
await $('kb-form').onsubmit({preventDefault(){}});
if(staleResult==='success')resolveRead(oldState);else rejectRead(Error('Obsolete read failed'));
await reading;
assert.equal(kb.example.style_notes.tone,'Successfully saved tone');
assert.equal($('kb-tone').value,'Successfully saved tone');
assert.match($('kb-feedback').textContent,/已保存/);assert.equal($('kb-error').hidden,true);
assert(readCount>=2,'Saving must refresh from a new read, not reuse the older pending read');
$('kb-tone').value='Second edit';$('kb-form').handlers.input();await $('kb-form').onsubmit({preventDefault(){}});
assert.equal(kb.example.style_notes.tone,'Second edit');assert.equal($('kb-error').hidden,true);
''')


def test_reset_of_a_deleted_record_closes_the_stale_editor():
    run_js(KNOWLEDGE_UI + r'''
$('kb-tone').value='draft';$('kb-form').handlers.input();
context.api=async()=>({projects:0,terms:0,memory_entries:0,phrase_entries:0,memory_enabled:true,pending:[],storage:{}});
delete kb.example;await window.LibraryKnowledge.open();
assert.equal($('kb-tone').value,'draft');
$('kb-reset').onclick();
assert.equal($('kb-form').hidden,true);
$('kb-new').onclick();assert.equal($('kb-form-title').textContent,'新建影视知识库');
assert.equal($('kb-name').value,'');
''')
