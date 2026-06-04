import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str):
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_toast_suppresses_duplicate_active_messages():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.toast('加载项目失败: network down', 'error');
        state.toast('加载项目失败: network down', 'error');
        state.toast('加载项目失败: network down', 'success');
        if (state.toasts.length !== 2) {
          throw new Error(`expected duplicate active error toast to be suppressed, got ${JSON.stringify(state.toasts)}`);
        }
        if (state.toasts[0].id === state.toasts[1].id) {
          throw new Error(`different toast types should keep distinct ids, got ${JSON.stringify(state.toasts)}`);
        }
        """
    )


def test_load_projects_and_settings_surface_errors_without_spam():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.api = async (url) => {
            throw new Error(url.includes('/api/settings') ? 'settings offline' : 'projects offline');
          };

          await state.loadProjects();
          await state.loadProjects();
          await state.loadSettings();
          await state.loadSettings();

          const messages = state.toasts.map((t) => t.msg);
          const projectErrors = messages.filter((msg) => msg === '加载项目失败: projects offline');
          const settingsErrors = messages.filter((msg) => msg === '加载设置失败: settings offline');
          if (projectErrors.length !== 1 || settingsErrors.length !== 1) {
            throw new Error(`expected one visible load error per type, got ${JSON.stringify(messages)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_load_projects_ignores_stale_response_when_archive_filter_changes():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let releaseActive;
          state.toast = () => {};
          state.api = async (url) => {
            if (url === '/api/projects') {
              await new Promise((resolve) => { releaseActive = resolve; });
              return [{id: 'active', name: 'Active'}];
            }
            if (url === '/api/projects?include_archived=true') {
              return [{id: 'archived', name: 'Archived', archived: true}];
            }
            throw new Error(`unexpected projects URL ${url}`);
          };

          state.showArchived = false;
          const activeLoad = state.loadProjects();
          await Promise.resolve();

          state.showArchived = true;
          const archivedLoad = state.loadProjects();
          await archivedLoad;
          if (JSON.stringify(state.projects.map((p) => p.id)) !== JSON.stringify(['archived'])) {
            throw new Error(`expected archived projects before stale response, got ${JSON.stringify(state.projects)}`);
          }

          releaseActive();
          await activeLoad;
          if (JSON.stringify(state.projects.map((p) => p.id)) !== JSON.stringify(['archived'])) {
            throw new Error(`stale active projects overwrote archive filter result: ${JSON.stringify(state.projects)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_project_list_timer_skips_idle_project_lists():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let timerCallback = null;
        const context = {
          console,
          setTimeout,
          clearTimeout,
          setInterval: (callback) => { timerCallback = callback; return 1; },
          document: { addEventListener: () => {} },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let projectCalls = 0;
          state.api = async (url) => {
            if (url === '/api/settings') return {};
            if (url === '/api/system-check') return {ready: true, translation_ready: true};
            if (url === '/api/projects') {
              projectCalls += 1;
              return [];
            }
            throw new Error(`unexpected url ${url}`);
          };

          await state.init();
          if (projectCalls !== 1) {
            throw new Error(`expected initial project load only, got ${projectCalls}`);
          }

          state.view = 'projects';
          timerCallback();
          await Promise.resolve();
          if (projectCalls !== 1) {
            throw new Error(`idle projects view should not poll an empty list, got ${projectCalls}`);
          }

          state.projects = [{id: 'busy', status: 'processing'}];
          timerCallback();
          await Promise.resolve();
          if (projectCalls !== 2) {
            throw new Error(`busy projects view should poll, got ${projectCalls}`);
          }

          state.projects = [{id: 'done', status: 'completed'}];
          timerCallback();
          await Promise.resolve();
          if (projectCalls !== 2) {
            throw new Error(`completed projects view should not keep polling, got ${projectCalls}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_frontend_init_is_idempotent():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let intervalCount = 0;
        let listenerCount = 0;
        const context = {
          console,
          setTimeout,
          clearTimeout,
          setInterval: () => { intervalCount += 1; return intervalCount; },
          document: { addEventListener: () => { listenerCount += 1; } },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let projectCalls = 0;
          let settingsCalls = 0;
          let systemCalls = 0;
          state.api = async (url) => {
            if (url === '/api/settings') {
              settingsCalls += 1;
              return {};
            }
            if (url === '/api/projects') {
              projectCalls += 1;
              return [];
            }
            if (url === '/api/system-check') {
              systemCalls += 1;
              return {ready: true, translation_ready: true};
            }
            throw new Error(`unexpected url ${url}`);
          };

          await state.init();
          await state.init();

          if (settingsCalls !== 1 || projectCalls !== 1 || systemCalls !== 1) {
            throw new Error(`init should load data once, got settings=${settingsCalls} projects=${projectCalls} system=${systemCalls}`);
          }
          if (intervalCount !== 1) {
            throw new Error(`init should create one refresh timer, got ${intervalCount}`);
          }
          if (listenerCount !== 2) {
            throw new Error(`init should install drag/drop listeners once, got ${listenerCount}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_projects_view_refreshes_when_entered():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.view = 'home';
          state.projects = [{id: 'stale', name: 'Stale'}];
          let calls = 0;
          state.api = async (url) => {
            if (url !== '/api/projects') throw new Error(`unexpected url ${url}`);
            calls += 1;
            return [{id: 'fresh', name: 'Fresh'}];
          };

          const changed = await state.setView('projects');
          if (changed !== true) throw new Error(`expected navigation to change view, got ${changed}`);
          if (calls !== 1) throw new Error(`expected one project refresh on enter, got ${calls}`);
          if (JSON.stringify(state.projects.map((p) => p.id)) !== JSON.stringify(['fresh'])) {
            throw new Error(`expected fresh projects after entering list, got ${JSON.stringify(state.projects)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_system_check_errors_are_visible_and_clear_after_success():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.api = async () => { throw new Error('system offline'); };

          await state.refreshSystemCheck();
          if (state.sysCheckError !== 'system offline') {
            throw new Error(`expected visible system-check error, got ${state.sysCheckError}`);
          }

          state.api = async () => ({ready: true, translation_ready: true});
          await state.refreshSystemCheck();
          if (state.sysCheckError !== '') {
            throw new Error(`expected system-check error to clear, got ${state.sysCheckError}`);
          }
          if (!state.sysCheck || state.sysCheck.ready !== true) {
            throw new Error(`expected system-check payload to update, got ${JSON.stringify(state.sysCheck)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_system_check_retry_blocks_duplicate_requests_while_loading():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let calls = 0;
          let releaseCheck;
          state.api = async () => {
            calls += 1;
            await new Promise((resolve) => { releaseCheck = resolve; });
            return {ready: true, translation_ready: true};
          };

          const first = state.refreshSystemCheck();
          await Promise.resolve();
          if (!state.sysCheckLoading) {
            throw new Error('expected system-check loading flag during request');
          }

          const duplicate = state.refreshSystemCheck();
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate retry to be ignored, got ${calls} calls`);
          }

          releaseCheck();
          await first;
          await duplicate;
          if (state.sysCheckLoading) {
            throw new Error('expected system-check loading flag to clear');
          }
          if (!state.sysCheck || state.sysCheck.ready !== true) {
            throw new Error(`expected latest system-check payload, got ${JSON.stringify(state.sysCheck)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_system_check_force_refresh_ignores_stale_response():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let releaseStale;
          state.api = async () => {
            await new Promise((resolve) => { releaseStale = resolve; });
            return {ready: false, translation_ready: false};
          };

          const stale = state.refreshSystemCheck();
          await Promise.resolve();
          state.api = async () => ({ready: true, translation_ready: true});
          const fresh = state.refreshSystemCheck({force: true});
          await fresh;

          releaseStale();
          await stale;
          if (state.sysCheckLoading) {
            throw new Error('expected force refresh to clear loading flag');
          }
          if (!state.sysCheck || state.sysCheck.ready !== true) {
            throw new Error(`stale system-check response overwrote fresh result: ${JSON.stringify(state.sysCheck)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_progress_poll_errors_are_visible_and_clear_after_success():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.currentProject = {id: 'p1', status: 'processing'};
          state.api = async () => { throw new Error('progress offline'); };

          await state.pollProgress();
          if (state.progressRefreshError !== 'progress offline') {
            throw new Error(`expected visible progress error, got ${state.progressRefreshError}`);
          }
          if (!state.progressMsg.includes('重试')) {
            throw new Error(`expected retry progress message, got ${state.progressMsg}`);
          }

          state.api = async (url) => {
            if (url === '/api/projects/p1') return {id: 'p1', status: 'processing', progress: 20};
            throw new Error(`unexpected url ${url}`);
          };
          await state.pollProgress();
          if (state.progressRefreshError !== '') {
            throw new Error(`expected progress error to clear, got ${state.progressRefreshError}`);
          }
          if (state.currentProject.progress !== 20) {
            throw new Error(`expected project refresh to update progress, got ${JSON.stringify(state.currentProject)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_progress_poll_ignores_stale_response_after_project_changes():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let releaseOldPoll;
          state.toast = () => {};
          state.currentProject = {id: 'p1', status: 'processing', progress: 10};
          state.subtitles = [{index: 1, text: 'p1 old'}];
          state.api = async (url) => {
            if (url === '/api/projects/p1') {
              await new Promise((resolve) => { releaseOldPoll = resolve; });
              return {id: 'p1', status: 'completed', progress: 100};
            }
            if (url === '/api/projects/p1/subtitles') {
              return {blocks: [{index: 1, text: 'p1 completed subtitle'}]};
            }
            throw new Error(`unexpected url ${url}`);
          };

          const oldPoll = state.pollProgress();
          await Promise.resolve();
          state.currentProject = {id: 'p2', status: 'processing', progress: 30};
          state.subtitles = [{index: 1, text: 'p2 subtitle'}];

          releaseOldPoll();
          await oldPoll;

          if (state.currentProject.id !== 'p2' || state.currentProject.progress !== 30) {
            throw new Error(`stale poll overwrote current project: ${JSON.stringify(state.currentProject)}`);
          }
          if (JSON.stringify(state.subtitles) !== JSON.stringify([{index: 1, text: 'p2 subtitle'}])) {
            throw new Error(`stale poll overwrote current subtitles: ${JSON.stringify(state.subtitles)}`);
          }
          if (state.progressRefreshError) {
            throw new Error(`stale poll should not set progress error, got ${state.progressRefreshError}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_frontend_loads_workflow_state_and_retries_failed_stage():
    _run_node(
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
          const calls = [];
          state.api = async (url, method = 'GET', body = null) => {
            calls.push({url, method, body});
            if (url === '/api/projects/p1/workflow-state') {
              return {stages: {translate: {status: 'failed', error_summary: 'bad key'}}};
            }
            if (url === '/api/projects/p1/retry' && method === 'POST') {
              return {status: 'started'};
            }
            throw new Error(`unexpected request ${method} ${url}`);
          };

          await state.loadWorkflowState();
          if (state.workflowState.stages.translate.status !== 'failed') {
            throw new Error(`expected failed translate state, got ${JSON.stringify(state.workflowState)}`);
          }

          await state.retryWorkflowStage('translate');
          const retryCall = calls.find((call) => call.url === '/api/projects/p1/retry');
          if (!retryCall) {
            throw new Error(`expected retry API call, got ${JSON.stringify(calls)}`);
          }
          if (retryCall.method !== 'POST') {
            throw new Error(`expected retry POST, got ${retryCall.method}`);
          }
          if (JSON.stringify(retryCall.body) !== JSON.stringify({stage: 'translate'})) {
            throw new Error(`expected retry body with stage, got ${JSON.stringify(retryCall.body)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_resume_workflow_uses_backend_stage_and_keeps_pending_guard():
    _run_node(
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
          state.currentProject = {id: 'p1', status: 'error'};
          const calls = [];
          state.api = async (url, method = 'GET') => {
            calls.push({url, method});
            if (url === '/api/projects/p1/resume' && method === 'POST') {
              return {status: 'started', stage: 'translate'};
            }
            if (url === '/api/projects/p1/workflow-state') {
              return {stages: {}};
            }
            throw new Error(`unexpected request ${method} ${url}`);
          };

          await state.resumeWorkflow();
          if (state.currentProject.status !== 'processing') {
            throw new Error(`expected processing status after resume, got ${JSON.stringify(state.currentProject)}`);
          }
          if (state.currentProject.pipeline_stage !== 'translate') {
            throw new Error(`expected backend resume stage, got ${JSON.stringify(state.currentProject)}`);
          }
          if (state.workflowActionPending !== '') {
            throw new Error(`expected workflow pending flag to clear, got ${state.workflowActionPending}`);
          }

          state.currentProject = {id: 'p1', status: 'error'};
          state.workflowActionPending = 'retry:asr';
          await state.resumeWorkflow();
          const resumeCalls = calls.filter((call) => call.url === '/api/projects/p1/resume');
          if (resumeCalls.length !== 1) {
            throw new Error(`pending guard should block duplicate resume calls, got ${JSON.stringify(calls)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_open_project_ignores_stale_mutations_after_workflow_state_delay():
    _run_node(
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
          state.setView = async (view) => { state.view = view; return true; };
          state.connectWS = () => {};
          state.loadKbUsageTrace = () => {};

          let releaseP1Workflow;
          let markP1WorkflowStarted;
          const p1WorkflowStarted = new Promise((resolve) => { markP1WorkflowStarted = resolve; });
          state.api = async (url) => {
            if (url === '/api/projects/p1') return {id: 'p1', status: 'error'};
            if (url === '/api/projects/p1/subtitles') return {blocks: [{index: 1, text: 'p1 subtitle'}]};
            if (url === '/api/projects/p1/workflow-state') {
              markP1WorkflowStarted();
              await new Promise((resolve) => { releaseP1Workflow = resolve; });
              return {stages: {translate: {status: 'failed'}}};
            }
            if (url === '/api/projects/p2') return {id: 'p2', status: 'completed'};
            if (url === '/api/projects/p2/subtitles') return {blocks: [{index: 2, text: 'p2 subtitle'}]};
            if (url === '/api/projects/p2/workflow-state') return {stages: {}};
            throw new Error(`unexpected url ${url}`);
          };

          const p1Open = state.openProject('p1');
          await p1WorkflowStarted;
          await state.openProject('p2');

          if (state.currentProject.id !== 'p2') {
            throw new Error(`expected p2 after newer open, got ${JSON.stringify(state.currentProject)}`);
          }
          if (JSON.stringify(state.subtitles) !== JSON.stringify([{index: 2, text: 'p2 subtitle'}])) {
            throw new Error(`expected p2 subtitles before stale release, got ${JSON.stringify(state.subtitles)}`);
          }

          releaseP1Workflow();
          await p1Open;
          if (state.currentProject.id !== 'p2') {
            throw new Error(`stale p1 open overwrote current project: ${JSON.stringify(state.currentProject)}`);
          }
          if (JSON.stringify(state.subtitles) !== JSON.stringify([{index: 2, text: 'p2 subtitle'}])) {
            throw new Error(`stale p1 open overwrote subtitles: ${JSON.stringify(state.subtitles)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_home_dashboard_summary_counts_active_projects_and_sorts_recent_items():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.projects = [
          {id: 'old', name: 'Old.mp4', status: 'created', duration: 90, created_at: '2026-01-01T00:00:00Z'},
          {id: 'done', name: 'Done.mp4', status: 'completed', output_video: '/out.mp4', duration: 120, created_at: '2026-01-04T00:00:00Z'},
          {id: 'busy', name: 'Busy.mp4', status: 'processing', progress: 40, duration: 30, created_at: '2026-01-03T00:00:00Z'},
          {id: 'failed', name: 'Failed.mp4', status: 'error', duration: 15, created_at: '2026-01-02T00:00:00Z'},
          {id: 'archived', name: 'Archived.mp4', status: 'completed', archived: true, duration: 999, created_at: '2026-01-05T00:00:00Z'},
          null,
        ];

        const summary = state.homeProjectSummary();
        if (JSON.stringify(summary) !== JSON.stringify({
          total: 4,
          running: 1,
          completed: 1,
          failed: 1,
          totalDuration: 255,
        })) {
          throw new Error(`unexpected home summary: ${JSON.stringify(summary)}`);
        }

        const recentIds = state.recentHomeProjects(3).map((p) => p.id);
        if (JSON.stringify(recentIds) !== JSON.stringify(['done', 'busy', 'failed'])) {
          throw new Error(`recent projects should ignore archived and sort newest first, got ${JSON.stringify(recentIds)}`);
        }
        """
    )
