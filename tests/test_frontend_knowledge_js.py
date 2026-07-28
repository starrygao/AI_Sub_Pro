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


def test_project_quality_helpers_load_suggestions_and_report():
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
          const toasts = [];
          state.currentProject = {id: 'p1'};
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.api = async (url, method = 'GET', body = null) => {
            calls.push({url, method, body});
            if (url === '/api/knowledge/projects/p1/suggestions') {
              return {suggestions: [{id: 'place:hudson-oaks', type: 'place', source: 'Hudson Oaks', target: '哈德逊奥克斯', status: 'pending'}]};
            }
            if (url === '/api/knowledge/projects/p1/suggestions/generate') {
              return {suggestions: [{id: 'place:hudson-oaks', type: 'place', source: 'Hudson Oaks', target: '哈德逊奥克斯', status: 'pending'}]};
            }
            if (url === '/api/knowledge/projects/p1/suggestions/place%3Ahudson-oaks/status') {
              return {suggestion: {id: 'place:hudson-oaks', type: 'place', source: 'Hudson Oaks', target: '哈德逊奥克斯', status: 'accepted'}};
            }
            if (url === '/api/projects/p1/quality-report') {
              return {
                status: 'needs_review',
                summary: {
                  issue_count: 3,
                  by_type: {reading_speed_too_fast: 1, proper_name_inconsistent: 1, kb_term_missing: 1},
                  repaired_blocks: 2,
                  unresolved_blocks: 1,
                },
                issues: [
                  {type: 'reading_speed_too_fast', severity: 'warning', block_id: 7, message: 'too fast'},
                  {type: 'proper_name_inconsistent', severity: 'warning', block_id: 9, message: 'name drift'},
                  {type: 'kb_term_missing', severity: 'error', block_id: 8, message: 'Use 哈德逊奥克斯'},
                ],
              };
            }
            throw new Error(`unexpected API ${method} ${url}`);
          };

          await state.loadKbSuggestions();
          if (state.kbSuggestions.length !== 1 || state.kbSuggestions[0].source !== 'Hudson Oaks') {
            throw new Error(`suggestions not loaded: ${JSON.stringify(state.kbSuggestions)}`);
          }
          await state.generateKbSuggestions();
          state.kbSuggestions[0].target = ' 哈德逊奥克斯 ';
          await state.setKbSuggestionStatus(state.kbSuggestions[0], 'accepted');
          if (state.kbSuggestions[0].status !== 'accepted') {
            throw new Error(`suggestion not updated: ${JSON.stringify(state.kbSuggestions)}`);
          }
          await state.loadQualityReport();
          if (state.qaReport.summary.issue_count !== 3 || state.qaReport.summary.repaired_blocks !== 2) {
            throw new Error(`QA report not loaded: ${JSON.stringify(state.qaReport)}`);
          }
          const acceptedCall = calls.find((call) => call.method === 'POST' && call.body?.status === 'accepted');
          if (!acceptedCall) {
            throw new Error(`expected accepted status call, got ${JSON.stringify(calls)}`);
          }
          if (acceptedCall.body.target !== '哈德逊奥克斯') {
            throw new Error(`expected inline target in status call, got ${JSON.stringify(acceptedCall.body)}`);
          }
          const topIssues = state.qaReportTopIssues();
          if (topIssues.length !== 3 || topIssues[0].label !== '阅读速度过快' || topIssues[1].label !== '专名不一致' || topIssues[2].severity_label !== '错误') {
            throw new Error(`expected normalized QA issue list, got ${JSON.stringify(topIssues)}`);
          }
          if (!state.qaReportSummaryText().includes('质量门阻止交付')) {
            throw new Error(`expected merged QA summary to block on errors, got ${state.qaReportSummaryText()}`);
          }
          if (!state.qaReportNextAction().includes('阻塞问题')) {
            throw new Error(`expected next action to prioritize blocking issues, got ${state.qaReportNextAction()}`);
          }
          state.qaReport.issues = [
            {type: 'proper_name_inconsistent', severity: 'warning', block_id: 9, message: 'name drift'},
          ];
          state.qaReport.summary.issue_count = 1;
          state.qaReport.summary.repaired_blocks = 0;
          state.qaReport.summary.unresolved_blocks = 1;
          if (!state.qaReportNextAction().includes('人工复核') || state.qaReportNextAction().includes('继续交付')) {
            throw new Error(`expected persisted review state to remain authoritative, got ${state.qaReportNextAction()}`);
          }
          state.qaReport.summary.repaired_blocks = 2;
          state.qaReport.summary.quality_gate = {passed: false, auto_repair_enabled: true, auto_repaired_blocks: 2};
          if (!state.qaReportNextAction().includes('人工复核') || state.qaReportNextAction().includes('抽查确认')) {
            throw new Error(`expected review state to keep delivery blocked, got ${state.qaReportNextAction()}`);
          }
          let focused = null;
          state.focusSubtitleById = (id) => { focused = id; };
          state.focusFirstQaIssue();
          if (focused !== 9) {
            throw new Error(`expected first QA issue focus, got ${focused}`);
          }
          if (!state.kbSuggestionSummaryText().includes('已接受 1')) {
            throw new Error(`expected accepted suggestion summary, got ${state.kbSuggestionSummaryText()}`);
          }
          state.qaReport.summary.conclusion = '达标：已自动重点返工 2 条并复检通过。';
          state.qaReport.summary.quality_gate = {passed: true, auto_repair_enabled: true, auto_repaired_blocks: 2};
          state.qaReport.status = 'ok';
          if (!state.qaReportSummaryText().includes('通过但有警告')) {
            throw new Error(`expected merged warning status, got ${state.qaReportSummaryText()}`);
          }
          if (!state.qaReportNextAction().includes('逐次确认')) {
            throw new Error(`expected warning export confirmation guidance, got ${state.qaReportNextAction()}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_project_translation_strategy_helpers_load_and_format_status():
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
          state.currentProject = {id: 'p1'};
          state.toast = () => {};
          state.api = async (url) => {
            if (url === '/api/projects/p1/translation-strategy') {
              return {
                status: 'ready',
                summary: '已启用 1 个内容策略。',
                active_profiles: [{id: 'academic_lecture', label: 'Academic lecture / research talk'}],
                manual_terms_count: 2,
                retrieval: {translation_memory: true, phrase_library: false},
                qa: {auto_repair: true, auto_repair_rounds: 1},
                quality_mode: {id: 'professional', label: '专业自动', requires_kb_review: false, quality_gate: true},
                recommendations: [{id: 'native_subtitles', message: '优先翻译原生字幕'}],
              };
            }
            throw new Error(`unexpected API ${url}`);
          };

          await state.loadTranslationStrategy();

          if (state.translationStrategy.status !== 'ready') {
            throw new Error(`expected strategy status, got ${JSON.stringify(state.translationStrategy)}`);
          }
          const profiles = state.translationStrategyProfilePills();
          if (profiles.length !== 1 || profiles[0] !== 'Academic lecture / research talk') {
            throw new Error(`bad profile pills ${JSON.stringify(profiles)}`);
          }
          const capabilities = state.translationStrategyCapabilityPills();
          for (const expected of ['专业自动', '术语 2', '用户修订记忆', '自动修复 1 轮']) {
            if (!capabilities.includes(expected)) {
              throw new Error(`missing capability ${expected}: ${JSON.stringify(capabilities)}`);
            }
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
              phrase_hits: [
                {source_text: 'Shoot your shot.', target_text: '主动出击。'},
                'bad phrase',
              ],
              kb_hits: [
                {scope: 'auto_kb_candidate', source: 'Southwick House', target: '索斯威克府'},
              ],
              style_hits: [
                {id: 'zh_cn_general', max_line_chars: 16, max_chars_per_second: 9},
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
          if (state.kbUsageTrace.phrase_hits.length !== 1 || state.kbUsageTrace.phrase_hits[0].source_text !== 'Shoot your shot.') {
            throw new Error(`expected normalized phrase hits, got ${JSON.stringify(state.kbUsageTrace.phrase_hits)}`);
          }
          if (state.kbUsageTrace.display_hits.length !== 4) {
            throw new Error(`expected display hits from matches and quality context, got ${JSON.stringify(state.kbUsageTrace.display_hits)}`);
          }
          if (state.kbUsageTrace.display_hits[1].trace_group !== '例句库' || state.kbUsageTrace.display_hits[1].trace_target !== '主动出击。') {
            throw new Error(`expected phrase display hit, got ${JSON.stringify(state.kbUsageTrace.display_hits[1])}`);
          }
          if (state.kbUsageTrace.display_hits[2].trace_group !== '自动候选' || state.kbUsageTrace.display_hits[2].trace_target !== '索斯威克府') {
            throw new Error(`expected auto candidate display hit, got ${JSON.stringify(state.kbUsageTrace.display_hits[2])}`);
          }
          if (state.kbUsageTrace.display_hits[3].trace_group !== '字幕样式' || !state.kbUsageTrace.display_hits[3].trace_target.includes('16字/行')) {
            throw new Error(`expected style display hit, got ${JSON.stringify(state.kbUsageTrace.display_hits[3])}`);
          }
          if (!state.kbUsageSummaryText().includes('自动候选参与 1')) {
            throw new Error(`expected usage summary to include auto candidates, got ${state.kbUsageSummaryText()}`);
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


def test_open_project_auto_loads_kb_suggestions_without_generating():
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
          let suggestionsSawCurrentProject = false;
          state.toast = () => {};
          state.api = async (url, method = 'GET') => {
            calls.push({url, method});
            if (url === '/api/projects/project-open') {
              return {id: 'project-open', name: 'Opened'};
            }
            if (url === '/api/projects/project-open/subtitles') {
              return {blocks: [{index: 1, text: 'hello'}]};
            }
            if (url === '/api/projects/project-open/workflow-state') {
              return {stages: {}};
            }
            if (url === '/api/knowledge/projects/project-open/suggestions' && method === 'GET') {
              suggestionsSawCurrentProject = state.currentProject?.id === 'project-open';
              return {suggestions: [{source: 'Alice', target: '爱丽丝', category: 'characters'}]};
            }
            if (url === '/api/knowledge/projects/project-open/usage-trace') {
              return {project: {show_title: 'Opened'}, matches: []};
            }
            if (url === '/api/projects/project-open/quality-report') {
              return {status: 'missing'};
            }
            if (url === '/api/projects/project-open/translation-strategy') {
              return {status: 'ready'};
            }
            throw new Error(`unexpected API call ${method} ${url}`);
          };

          await state.openProject('project-open');
          await new Promise((resolve) => setTimeout(resolve, 0));

          if (!suggestionsSawCurrentProject) {
            throw new Error('expected suggestion request after current project was assigned');
          }
          if (state.kbSuggestions.length !== 1 || state.kbSuggestions[0].source !== 'Alice') {
            throw new Error(`expected suggestions to auto-load, got ${JSON.stringify(state.kbSuggestions)}`);
          }
          const generated = calls.some((call) => call.method === 'POST' && call.url.endsWith('/suggestions/generate'));
          if (generated) {
            throw new Error(`openProject should not auto-generate suggestions, got ${JSON.stringify(calls)}`);
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
