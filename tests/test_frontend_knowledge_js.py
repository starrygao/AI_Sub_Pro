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
