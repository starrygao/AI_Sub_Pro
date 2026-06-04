import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_js(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_knowledge_list_exposes_loading_and_error_states():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    expected = [
        "kbListLoading",
        "kbListError",
        "加载知识库列表",
        "@click=\"loadKbProjects()\"",
        "kbSelectingKey === kb.key",
        "加载知识库内容",
        "kbSelectError",
    ]
    for snippet in expected:
        assert snippet in html


def test_knowledge_view_loads_on_navigation_not_hidden_page_init():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    assert 'x-init="loadKbProjects()"' not in html

    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          setInterval: () => 1,
          document: { addEventListener: () => {} },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const calls = [];
          state.api = async (url) => {
            calls.push(url);
            if (url === '/api/settings') return {
              api_keys: {},
              tmdb: {},
              trailer: {},
              asr: {},
              translation: {primary_provider: 'openai', polish_provider: ''},
              providers: {claude_cli: {}},
            };
            if (url === '/api/projects') return [];
            if (url === '/api/system-check') return {ready: false};
            if (url === '/api/knowledge/projects') return {projects: []};
            if (url.startsWith('/api/models/')) return {models: []};
            throw new Error(`unexpected URL ${url}`);
          };
          state.fetchModels = () => {};
          state.toast = () => {};

          await state.init();
          if (calls.includes('/api/knowledge/projects')) {
            throw new Error(`expected app init not to load hidden KB view, got ${JSON.stringify(calls)}`);
          }

          await state.setView('knowledge');
          const kbCalls = calls.filter((url) => url === '/api/knowledge/projects');
          if (kbCalls.length !== 1) {
            throw new Error(`expected one KB load on first navigation, got ${JSON.stringify(calls)}`);
          }

          await state.setView('settings');
          await state.setView('knowledge');
          const secondKbCalls = calls.filter((url) => url === '/api/knowledge/projects');
          if (secondKbCalls.length !== 2) {
            throw new Error(`expected KB list refresh when returning to view, got ${JSON.stringify(calls)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_list_loader_keeps_empty_state_out_of_loading_path():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.toast = () => {};
          let releaseApi;
          state.api = async (url) => {
            if (url !== '/api/knowledge/projects') throw new Error(`unexpected URL ${url}`);
            await new Promise((resolve) => { releaseApi = resolve; });
            return {projects: [{key: 'elsbeth', show_title: 'Elsbeth'}]};
          };

          const pending = state.loadKbProjects();
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (!state.kbListLoading) throw new Error('expected KB list loading flag while request is pending');
          if (state.kbListError) throw new Error(`expected no initial list error, got ${state.kbListError}`);
          releaseApi();
          await pending;

          if (state.kbListLoading) throw new Error('expected KB list loading flag to clear');
          if (state.kbProjects.length !== 1 || state.kbProjects[0].key !== 'elsbeth') {
            throw new Error(`expected loaded KB project, got ${JSON.stringify(state.kbProjects)}`);
          }

          state.api = async () => { throw new Error('network down'); };
          await state.loadKbProjects();
          if (state.kbListLoading) throw new Error('expected KB list loading flag to clear after failure');
          if (!state.kbListError.includes('network down')) {
            throw new Error(`expected visible list error, got ${state.kbListError}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_navigation_closes_new_kb_prompt_without_dirty_editor():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.view = 'knowledge';
          state.kbDirty = false;
          state.kbCurrent = {key: 'elsbeth', show_title: 'Elsbeth'};
          state.kbNewKeyPrompt = true;
          state.kbNewKeyInput = 'draft_key';
          const changed = await state.setView('settings');

          if (!changed || state.view !== 'settings') {
            throw new Error(`expected navigation to settings, got ${JSON.stringify({changed, view: state.view})}`);
          }
          if (state.kbNewKeyPrompt || state.kbNewKeyInput) {
            throw new Error(`expected new KB prompt to close, got ${JSON.stringify({
              prompt: state.kbNewKeyPrompt,
              input: state.kbNewKeyInput,
            })}`);
          }
          if (!state.kbCurrent || state.kbCurrent.key !== 'elsbeth') {
            throw new Error('expected clean KB editor state to remain available after navigation');
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_open_project_respects_unsaved_knowledge_guard_before_fetching_detail():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout, WebSocket: function() {} };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const calls = [];
          state.toast = () => {};
          state.askConfirm = async () => false;
          state.api = async (url) => {
            calls.push(url);
            return url.endsWith('/subtitles')
              ? {blocks: [{index: 1, text: 'new'}]}
              : {id: 'new-project', name: 'New Project'};
          };
          state.view = 'knowledge';
          state.kbDirty = true;
          state.currentProject = {id: 'existing-project', name: 'Existing'};
          state.subtitles = [{index: 1, text: 'old'}];

          await state.openProject('new-project');

          if (calls.length !== 0) {
            throw new Error(`expected no project fetch after cancelled KB leave, got ${JSON.stringify(calls)}`);
          }
          if (state.view !== 'knowledge') {
            throw new Error(`expected to stay in knowledge view, got ${state.view}`);
          }
          if (state.currentProject?.id !== 'existing-project' || state.subtitles[0]?.text !== 'old') {
            throw new Error(`expected detail state to remain unchanged, got ${JSON.stringify({
              project: state.currentProject,
              subtitles: state.subtitles,
            })}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_frontend_loads_usage_trace_for_current_project():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.toast = () => {};
          state.currentProject = {id: 'project one'};
          state.api = async (url) => {
            if (url !== '/api/knowledge/projects/project%20one/usage-trace') {
              throw new Error(`unexpected URL ${url}`);
            }
            return {
              project: ['bad'],
              matches: [
                {source: 'Alice', target: '爱丽丝', category: 'characters'},
                'bad row',
              ],
              extra: 'kept',
            };
          };

          await state.loadKbUsageTrace();

          if (state.kbTraceLoading || state.kbTraceError) {
            throw new Error(`expected loaded trace state, got ${JSON.stringify({
              loading: state.kbTraceLoading,
              error: state.kbTraceError,
            })}`);
          }
          if (!state.kbUsageTrace || state.kbUsageTrace.extra !== 'kept') {
            throw new Error(`expected trace payload, got ${JSON.stringify(state.kbUsageTrace)}`);
          }
          if (Object.keys(state.kbUsageTrace.project).length !== 0) {
            throw new Error(`expected malformed project to normalize to object, got ${JSON.stringify(state.kbUsageTrace.project)}`);
          }
          if (state.kbUsageTrace.matches.length !== 1 || state.kbUsageTrace.matches[0].source !== 'Alice') {
            throw new Error(`expected normalized matches, got ${JSON.stringify(state.kbUsageTrace.matches)}`);
          }

          state.currentProject = null;
          await state.loadKbUsageTrace();
          if (state.kbUsageTrace !== null || state.kbTraceLoading || state.kbTraceError) {
            throw new Error(`expected trace to clear without current project, got ${JSON.stringify({
              trace: state.kbUsageTrace,
              loading: state.kbTraceLoading,
              error: state.kbTraceError,
            })}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_frontend_ignores_stale_usage_trace_response():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let releaseProjectA;
          state.toast = () => {};
          state.currentProject = {id: 'project-a'};
          state.api = async (url) => {
            if (url === '/api/knowledge/projects/project-a/usage-trace') {
              await new Promise((resolve) => { releaseProjectA = resolve; });
              return {project: {show_title: 'A'}, matches: [{source: 'Alice'}]};
            }
            if (url === '/api/knowledge/projects/project-b/usage-trace') {
              return {project: {show_title: 'B'}, matches: [{source: 'Bob'}]};
            }
            throw new Error(`unexpected URL ${url}`);
          };

          const projectALoad = state.loadKbUsageTrace();
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (!state.kbTraceLoading) throw new Error('expected trace loading while project A request is pending');

          state.currentProject = {id: 'project-b'};
          await state.loadKbUsageTrace();
          if (state.kbUsageTrace.matches.length !== 1 || state.kbUsageTrace.matches[0].source !== 'Bob') {
            throw new Error(`expected project B trace, got ${JSON.stringify(state.kbUsageTrace)}`);
          }

          releaseProjectA();
          await projectALoad;
          if (state.kbUsageTrace.matches.length !== 1 || state.kbUsageTrace.matches[0].source !== 'Bob') {
            throw new Error(`expected stale project A trace to be ignored, got ${JSON.stringify(state.kbUsageTrace)}`);
          }
          if (state.kbTraceLoading || state.kbTraceError) {
            throw new Error(`expected final project B trace state, got ${JSON.stringify({
              loading: state.kbTraceLoading,
              error: state.kbTraceError,
            })}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_open_project_loads_usage_trace_after_setting_current_project():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          location: {protocol: 'http:', host: 'localhost'},
          WebSocket: function() { this.close = () => {}; },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const calls = [];
          let traceSawCurrentProject = false;
          state.toast = () => {};
          state.api = async (url) => {
            calls.push(url);
            if (url === '/api/projects/project-open') {
              return {id: 'project-open', name: 'Opened'};
            }
            if (url === '/api/projects/project-open/subtitles') {
              return {blocks: [{index: 1, text: 'hello'}]};
            }
            if (url === '/api/knowledge/projects/project-open/usage-trace') {
              traceSawCurrentProject = state.currentProject?.id === 'project-open';
              return {project: {show_title: 'Opened'}, matches: [{source: 'Alice'}]};
            }
            throw new Error(`unexpected URL ${url}`);
          };

          await state.openProject('project-open');
          await new Promise((resolve) => setTimeout(resolve, 0));

          if (!traceSawCurrentProject) {
            throw new Error('expected usage trace request after current project was assigned');
          }
          if (!calls.includes('/api/knowledge/projects/project-open/usage-trace')) {
            throw new Error(`expected trace endpoint call, got ${JSON.stringify(calls)}`);
          }
          if (!state.kbUsageTrace || state.kbUsageTrace.matches[0]?.source !== 'Alice') {
            throw new Error(`expected trace state to load, got ${JSON.stringify(state.kbUsageTrace)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_frontend_loads_and_accepts_suggestions():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const calls = [];
          let acceptPayload = null;
          state.toast = () => {};
          state.currentProject = {id: 'p1', name: 'Project One'};
          state.kbSelectedKey = 'show-one';
          state.kbCurrent = {key: 'show-one', show_title: 'Show One', tmdb_id: 123};
          state.api = async (url, method = 'GET', body = null) => {
            calls.push({url, method, body});
            if (url === '/api/knowledge/projects/p1/suggestions' && method === 'GET') {
              return {suggestions: [
                {source: 'Alice', target: '', category: 'characters', collision: 'new', notes: '  lead character  '},
                {source: 'Acme', target: '艾克米', category: 'brands', collision: 'existing'},
              ]};
            }
            if (url === '/api/knowledge/projects/p1/suggestions/accept' && method === 'POST') {
              acceptPayload = body;
              return {accepted: 1};
            }
            if (url === '/api/knowledge/projects/show-one' && method === 'GET') {
              return {key: 'show-one', show_title: 'Show One', tmdb_id: 123, characters: [], places: [], brands: [], slang: [], style_notes: {}};
            }
            throw new Error(`unexpected API call ${method} ${url}`);
          };

          await state.loadKbSuggestions();
          if (state.kbSuggestions.length !== 2) {
            throw new Error(`expected suggestions, got ${JSON.stringify(state.kbSuggestions)}`);
          }
          if (!state.kbSuggestions[0].selected || state.kbSuggestions[1].selected) {
            throw new Error(`expected selected defaults from collision, got ${JSON.stringify(state.kbSuggestions)}`);
          }
          state.kbSuggestions[0].target = '爱丽丝';
          state.kbSuggestions[0].notes = '  主角称呼  ';
          state.kbSuggestions[1].selected = false;

          await state.acceptKbSuggestions();
          if (!acceptPayload) throw new Error('expected accept payload');
          if (acceptPayload.key !== 'show-one' || acceptPayload.show_title !== 'Show One' || acceptPayload.tmdb_id !== 123) {
            throw new Error(`unexpected accept metadata ${JSON.stringify(acceptPayload)}`);
          }
          if (acceptPayload.entries.length !== 1) {
            throw new Error(`expected one accepted entry, got ${JSON.stringify(acceptPayload.entries)}`);
          }
          const entry = acceptPayload.entries[0];
          if (entry.source !== 'Alice' || entry.target !== '爱丽丝' || entry.category !== 'characters' || entry.notes !== '主角称呼') {
            throw new Error(`unexpected accepted entry ${JSON.stringify(entry)}`);
          }
          const urls = calls.map((call) => `${call.method} ${call.url}`);
          if (!urls.includes('GET /api/knowledge/projects/show-one')) {
            throw new Error(`expected KB reload after accept, got ${JSON.stringify(urls)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_frontend_rejects_suggestion_and_refreshes():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const posts = [];
          const toasts = [];
          let refreshes = 0;
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.currentProject = {id: 'p1'};
          state.loadKbSuggestions = async () => { refreshes += 1; };
          state.api = async (url, method = 'GET', body = null) => {
            posts.push({url, method, body});
            if (url === '/api/knowledge/projects/p1/suggestions/reject' && method === 'POST') {
              return {rejected: 1};
            }
            throw new Error(`unexpected API call ${method} ${url}`);
          };

          await state.rejectKbSuggestion({source: ' Alice ', target: '爱丽丝'});

          if (posts.length !== 1) {
            throw new Error(`expected one reject POST, got ${JSON.stringify(posts)}`);
          }
          const post = posts[0];
          if (post.url !== '/api/knowledge/projects/p1/suggestions/reject' || post.method !== 'POST') {
            throw new Error(`unexpected reject call ${JSON.stringify(post)}`);
          }
          if (JSON.stringify(post.body) !== JSON.stringify({sources: ['Alice']})) {
            throw new Error(`unexpected reject body ${JSON.stringify(post.body)}`);
          }
          if (refreshes !== 1) {
            throw new Error(`expected suggestions refresh after reject, got ${refreshes}`);
          }
          if (!toasts.some((toast) => toast.type === 'success')) {
            throw new Error(`expected success toast, got ${JSON.stringify(toasts)}`);
          }
          if (state.kbActionPending) {
            throw new Error(`expected pending state cleared, got ${state.kbActionPending}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_frontend_reject_ignores_stale_project_response():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const posts = [];
          const toasts = [];
          let refreshes = 0;
          let releaseReject;
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.currentProject = {id: 'project-a'};
          state.loadKbSuggestions = async () => { refreshes += 1; };
          state.api = async (url, method = 'GET', body = null) => {
            posts.push({url, method, body});
            if (url === '/api/knowledge/projects/project-a/suggestions/reject' && method === 'POST') {
              await new Promise((resolve) => { releaseReject = resolve; });
              return {rejected: 1};
            }
            throw new Error(`unexpected API call ${method} ${url}`);
          };

          const pending = state.rejectKbSuggestion({source: 'Alice'});
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (!state.kbActionPending) throw new Error('expected reject to be pending');

          state.currentProject = {id: 'project-b'};
          releaseReject();
          await pending;

          if (posts.length !== 1 || posts[0].url !== '/api/knowledge/projects/project-a/suggestions/reject') {
            throw new Error(`expected original project reject call, got ${JSON.stringify(posts)}`);
          }
          if (refreshes !== 0) {
            throw new Error(`expected no stale refresh, got ${refreshes}`);
          }
          if (toasts.some((toast) => toast.type === 'success')) {
            throw new Error(`expected no stale success toast, got ${JSON.stringify(toasts)}`);
          }
          if (state.kbSuggestionsError) {
            throw new Error(`expected no stale error mutation, got ${state.kbSuggestionsError}`);
          }
          if (state.kbActionPending) {
            throw new Error(`expected pending state cleared, got ${state.kbActionPending}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_frontend_ignores_stale_suggestions_and_accept_during_load():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const posts = [];
          let releaseProjectA;
          state.toast = () => {};
          state.currentProject = {id: 'project-a'};
          state.kbSelectedKey = 'show-one';
          state.kbCurrent = {key: 'show-one', show_title: 'Show One', tmdb_id: null};
          state.kbSuggestions = [{source: 'Old', target: '旧', selected: true, category: 'characters'}];
          state.api = async (url, method = 'GET', body = null) => {
            if (method === 'POST') {
              posts.push({url, body});
              return {accepted: 1};
            }
            if (url === '/api/knowledge/projects/project-a/suggestions') {
              await new Promise((resolve) => { releaseProjectA = resolve; });
              return {suggestions: [{source: 'Alice', target: '爱丽丝', category: 'characters'}]};
            }
            if (url === '/api/knowledge/projects/project-b/suggestions') {
              return {suggestions: [{source: 'Bob', target: '鲍勃', category: 'characters'}]};
            }
            throw new Error(`unexpected API call ${method} ${url}`);
          };

          const projectALoad = state.loadKbSuggestions();
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (!state.kbSuggestionsLoading) throw new Error('expected suggestions to be loading');

          const acceptAttempt = state.acceptKbSuggestions();
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (posts.length !== 0) {
            throw new Error(`expected no accept while suggestions are loading, got ${JSON.stringify(posts)}`);
          }
          await acceptAttempt;

          state.currentProject = {id: 'project-b'};
          const projectBLoad = state.loadKbSuggestions();
          await projectBLoad;
          if (state.kbSuggestions.length !== 1 || state.kbSuggestions[0].source !== 'Bob') {
            throw new Error(`expected project B suggestions, got ${JSON.stringify(state.kbSuggestions)}`);
          }

          releaseProjectA();
          await projectALoad;
          if (state.kbSuggestions.length !== 1 || state.kbSuggestions[0].source !== 'Bob') {
            throw new Error(`expected stale project A response to be ignored, got ${JSON.stringify(state.kbSuggestions)}`);
          }

          state.currentProject = null;
          await state.loadKbSuggestions();
          if (state.kbSuggestions.length !== 0 || state.kbSuggestionsLoading || state.kbSuggestionsError) {
            throw new Error(`expected suggestions to clear without current project, got ${JSON.stringify({
              suggestions: state.kbSuggestions,
              loading: state.kbSuggestionsLoading,
              error: state.kbSuggestionsError,
            })}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_html_contains_suggestion_and_trace_panels():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    expected = [
        "loadKbSuggestions",
        "rejectKbSuggestion",
        "kbSuggestions",
        "suggestion.notes",
        "kbUsageTrace",
    ]
    for snippet in expected:
        assert snippet in html
