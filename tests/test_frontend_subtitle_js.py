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


def test_subtitle_split_rolls_back_when_persist_fails():
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
          state.toast = () => {};
          state.api = async () => { throw new Error('backend rejected'); };
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:00,300',
            text: 'short line',
            translation: '短句',
            filtered: false,
            filter_reason: '',
          }];
          const before = JSON.stringify(state.subtitles);
          await state.splitSubtitle(0);
          const after = JSON.stringify(state.subtitles);
          if (after !== before) throw new Error(`expected rollback, got ${after}`);
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_subtitle_split_short_line_does_not_call_api():
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
          const toasts = [];
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.api = async () => { throw new Error('api should not be called'); };
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:00,300',
            text: 'short line',
            translation: '短句',
            filtered: false,
            filter_reason: '',
          }];
          const before = JSON.stringify(state.subtitles);
          await state.splitSubtitle(0);
          const after = JSON.stringify(state.subtitles);
          if (after !== before) throw new Error(`expected no mutation, got ${after}`);
          if (!toasts.some((t) => t.type === 'error' && t.message.includes('太短'))) {
            throw new Error(`expected short-line error toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_subtitle_save_edit_rolls_back_when_persist_fails():
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
          state.toast = () => {};
          state.api = async () => { throw new Error('backend rejected'); };
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: 'hello',
            translation: 'old',
            filtered: false,
            filter_reason: '',
          }];
          state.editingIdx = 0;
          state.editText = 'new';
          await state.saveEdit(0);
          if (state.subtitles[0].translation !== 'old') {
            throw new Error(`expected old translation, got ${state.subtitles[0].translation}`);
          }
          if (state.editingIdx !== 0) {
            throw new Error(`expected edit mode to stay open, got ${state.editingIdx}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_subtitle_save_edit_blocks_duplicate_persist_while_pending():
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
          let persists = 0;
          let releasePersist;
          state.currentProject = {id: 'p1'};
          state.toast = () => {};
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: 'hello',
            translation: 'old',
            filtered: false,
            filter_reason: '',
          }];
          state.persistSubtitles = async () => {
            persists += 1;
            await new Promise((resolve) => { releasePersist = resolve; });
          };
          state.editingIdx = 0;
          state.editText = 'new';

          const first = state.saveEdit(0);
          await Promise.resolve();
          if (!state.isSubtitleActionPending('save', 0)) {
            throw new Error(`expected save pending state, got ${state.subtitleActionPending}`);
          }

          const second = state.saveEdit(0);
          await Promise.resolve();
          if (persists !== 1) {
            throw new Error(`expected duplicate save to be ignored, got ${persists} persists`);
          }

          releasePersist();
          await first;
          await second;
          if (state.subtitleActionPending !== '') {
            throw new Error(`expected pending state to clear, got ${state.subtitleActionPending}`);
          }
          if (state.subtitles[0].translation !== 'new' || state.editingIdx !== -1) {
            throw new Error(`expected saved edit, got ${state.subtitles[0].translation}/${state.editingIdx}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_subtitle_edit_actions_ignore_invalid_indexes_without_persisting():
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
          let persisted = 0;
          let confirmations = 0;
          state.currentProject = {id: 'p1'};
          state.toast = () => {};
          state.askConfirm = async () => { confirmations += 1; return true; };
          state.persistSubtitles = async () => { persisted += 1; };
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: 'hello',
            translation: 'old',
            filtered: false,
            filter_reason: '',
          }];
          const before = JSON.stringify(state.subtitles);

          state.editingIdx = 5;
          state.editText = 'new';
          await state.saveEdit(5);
          await state.addSubtitleAfter(9);
          await state.deleteSubtitle(9);
          await state.splitSubtitle(9);

          if (JSON.stringify(state.subtitles) !== before) {
            throw new Error(`expected invalid actions to leave subtitles untouched, got ${JSON.stringify(state.subtitles)}`);
          }
          if (persisted !== 0) {
            throw new Error(`expected no persistence for invalid actions, got ${persisted}`);
          }
          if (confirmations !== 0) {
            throw new Error(`expected delete to skip confirmation for invalid index, got ${confirmations}`);
          }
          if (state.editingIdx !== -1) {
            throw new Error(`expected invalid edit mode to close, got ${state.editingIdx}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_subtitle_delete_blocks_duplicate_confirmation_while_pending():
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
          let confirms = 0;
          let persists = 0;
          let releaseConfirm;
          state.currentProject = {id: 'p1'};
          state.toast = () => {};
          state.askConfirm = async () => {
            confirms += 1;
            await new Promise((resolve) => { releaseConfirm = resolve; });
            return true;
          };
          state.persistSubtitles = async () => { persists += 1; };
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: 'hello',
            translation: 'old',
            filtered: false,
            filter_reason: '',
          }];

          const first = state.deleteSubtitle(0);
          await Promise.resolve();
          if (!state.isSubtitleActionPending('delete', 0)) {
            throw new Error(`expected delete pending state, got ${state.subtitleActionPending}`);
          }

          const second = state.deleteSubtitle(0);
          await Promise.resolve();
          if (confirms !== 1) {
            throw new Error(`expected one delete confirmation, got ${confirms}`);
          }

          releaseConfirm();
          await first;
          await second;
          if (persists !== 1 || state.subtitles.length !== 0) {
            throw new Error(`expected one persisted delete, got ${persists}/${state.subtitles.length}`);
          }
          if (state.subtitleActionPending !== '') {
            throw new Error(`expected pending state to clear, got ${state.subtitleActionPending}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_add_subtitle_after_contiguous_row_creates_positive_duration():
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
          state.toast = () => {};
          state.persistSubtitles = async () => {};
          state.subtitles = [
            {
              index: 1,
              start: '00:00:00,000',
              end: '00:00:01,000',
              text: 'first',
              translation: '第一行',
              filtered: false,
              filter_reason: '',
            },
            {
              index: 2,
              start: '00:00:01,000',
              end: '00:00:02,000',
              text: 'second',
              translation: '第二行',
              filtered: false,
              filter_reason: '',
            },
          ];

          await state.addSubtitleAfter(0);

          if (state.subtitles.length !== 3) {
            throw new Error(`expected inserted row, got ${state.subtitles.length}`);
          }
          const inserted = state.subtitles[1];
          if (state.parseSrtTime(inserted.end) <= state.parseSrtTime(inserted.start)) {
            throw new Error(`expected positive duration, got ${inserted.start} --> ${inserted.end}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_format_srt_time_rejects_non_finite_values():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        const values = [Infinity, -Infinity, NaN, -10];
        for (const value of values) {
          const formatted = state.formatSrtTime(value);
          if (formatted !== '00:00:00,000') {
            throw new Error(`expected zero time for ${value}, got ${formatted}`);
          }
        }
        """
    )


def test_format_date_hides_invalid_dates():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        if (state.formatDate('not-a-date') !== '') {
          throw new Error(`expected invalid date to be hidden, got ${state.formatDate('not-a-date')}`);
        }
        if (!state.formatDate('2026-05-30T06:00:00Z')) {
          throw new Error('expected valid date to render');
        }
        """
    )


def test_parse_srt_time_rejects_out_of_range_minutes_and_seconds():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        if (state.parseSrtTime('00:59:59,999') !== 3599999) {
          throw new Error('expected valid max minute/second time to parse');
        }
        if (state.parseSrtTime('120:00:00,000') !== 432000000) {
          throw new Error('expected long-hour subtitles to parse');
        }
        for (const value of ['00:60:00,000', '00:00:60,000', `${'9'.repeat(400)}:00:00,000`, 'bad']) {
          const parsed = state.parseSrtTime(value);
          if (parsed !== 0) throw new Error(`expected invalid time to parse as zero for ${value}, got ${parsed}`);
        }
        """
    )


def test_progress_websocket_clamps_progress_and_message_shape():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let socket;
        class FakeWebSocket {
          constructor(url) { this.url = url; socket = this; }
          close() {}
        }
        const context = {
          console,
          setTimeout,
          clearTimeout,
          location: {protocol: 'http:', host: 'localhost'},
          WebSocket: FakeWebSocket,
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.currentProject = {id: 'p1', progress: 0, progress_msg: ''};
        state.view = 'detail';
        state.connectWS('p1');
        socket.onmessage({data: JSON.stringify({progress: 999, message: {bad: 'shape'}})});
        if (state.progressPct !== 100 || state.currentProject.progress !== 100) {
          throw new Error(`expected clamped progress, got ${state.progressPct}`);
        }
        if (state.progressMsg !== '' || state.currentProject.progress_msg !== '') {
          throw new Error(`expected empty non-string message, got ${state.progressMsg}`);
        }
        socket.onmessage({data: JSON.stringify({progress: -5, message: 'queued'})});
        if (state.progressPct !== 0 || state.progressMsg !== 'queued') {
          throw new Error(`expected normalized second frame, got ${state.progressPct}/${state.progressMsg}`);
        }
        """
    )


def test_export_srt_requires_exportable_content_before_api_call():
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
          const toasts = [];
          state.currentProject = {id: 'p1', status: 'translated'};
          state.subtitles = [
            {index: 1, text: 'Hello', translation: '', filtered: false},
            {index: 2, text: 'Filtered', translation: '忽略', filtered: true},
          ];
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.api = async () => {
            calls += 1;
            throw new Error('export API should not be called');
          };

          if (state.canExportSrt('translated')) {
            throw new Error('translated export should be disabled without usable translations');
          }
          if (!state.canExportSrt('original')) {
            throw new Error('original export should stay available when source subtitles exist');
          }

          await state.exportSrt('translated');

          if (calls !== 0) throw new Error(`expected no export API calls, got ${calls}`);
          if (!toasts.some((t) => t.type === 'error' && t.message.includes('翻译字幕'))) {
            throw new Error(`expected missing translation export toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_export_srt_sets_pending_and_blocks_duplicate_submit():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let calls = 0;
        let clicked = 0;
        let appended = 0;
        let removed = 0;
        let releaseApi;
        const revoked = [];
        const context = {
          console,
          setTimeout,
          clearTimeout,
          Blob: function(parts, options) {
            this.parts = parts;
            this.options = options;
          },
          URL: {
            createObjectURL: (blob) => {
              if (!blob.parts[0].includes('Translated')) {
                throw new Error(`unexpected blob content ${blob.parts}`);
              }
              return 'blob:test-export';
            },
            revokeObjectURL: (url) => { revoked.push(url); },
          },
          document: {
            body: {
              appendChild: () => { appended += 1; },
            },
            createElement: () => ({
              click: () => { clicked += 1; },
              remove: () => { removed += 1; },
            }),
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const toasts = [];
          state.currentProject = {id: 'p1', status: 'translated'};
          state.subtitles = [{index: 1, text: 'Hello', translation: 'Translated', filtered: false}];
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.api = async (url, method) => {
            calls += 1;
            if (url !== '/api/projects/p1/export?format=translated' || method !== 'POST') {
              throw new Error(`unexpected export API call ${method} ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {content: 'Translated subtitle', filename: 'movie.translated.srt'};
          };

          const first = state.exportSrt('translated');
          await Promise.resolve();
          if (!state.isExportingSrt('translated')) {
            throw new Error(`expected export pending state, got ${state.projectActionPending}`);
          }

          const second = state.exportSrt('translated');
          await Promise.resolve();
          if (calls !== 1) throw new Error(`expected duplicate export to be ignored, got ${calls} calls`);
          if (!toasts.some((t) => t.type === 'error' && t.message.includes('未完成'))) {
            throw new Error(`expected duplicate pending toast, got ${JSON.stringify(toasts)}`);
          }

          releaseApi();
          await first;
          await second;

          if (state.projectActionPending !== '') {
            throw new Error(`expected pending state to clear, got ${state.projectActionPending}`);
          }
          if (clicked !== 1 || appended !== 1 || removed !== 1) {
            throw new Error(`expected one download click/append/remove, got ${clicked}/${appended}/${removed}`);
          }
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (revoked[0] !== 'blob:test-export') {
            throw new Error(`expected object URL revocation, got ${JSON.stringify(revoked)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_delete_current_project_clears_detail_state_and_socket():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let closed = false;
        const context = {
          console,
          setTimeout,
          clearTimeout,
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.currentProject = {id: 'p1'};
          state.subtitles = [{index: 1}];
          state.progressPct = 42;
          state.progressMsg = 'working';
          state.view = 'detail';
          state.wsReconnectTimer = 1;
          state.ws = {onclose: () => {}, close: () => { closed = true; }};
          state.toast = () => {};
          state.api = async (url, method) => {
            if (url !== '/api/projects/p1' || method !== 'DELETE') {
              throw new Error(`unexpected api call ${method} ${url}`);
            }
            return {status: 'ok'};
          };
          state.loadProjects = async () => {};

          const deletion = state.deleteProject('p1');
          await Promise.resolve();
          if (!state.confirmPrompt) throw new Error('expected delete confirmation prompt');
          state.resolveConfirm(true);
          await deletion;

          if (!closed) throw new Error('expected websocket to close');
          if (state.currentProject !== null || state.subtitles.length !== 0) {
            throw new Error(`expected cleared project state, got ${JSON.stringify(state.currentProject)} ${JSON.stringify(state.subtitles)}`);
          }
          if (state.progressPct !== 0 || state.progressMsg !== '') {
            throw new Error(`expected cleared progress, got ${state.progressPct}/${state.progressMsg}`);
          }
          if (state.view !== 'projects') throw new Error(`expected projects view, got ${state.view}`);
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_delete_project_blocks_duplicate_delete_while_pending():
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
          let confirms = 0;
          let releaseConfirm;
          let releaseApi;
          state.projects = [{id: 'p1', name: 'Project'}];
          state.toast = () => {};
          state.askConfirm = async () => {
            confirms += 1;
            await new Promise((resolve) => { releaseConfirm = resolve; });
            return true;
          };
          state.loadProjects = async () => {};
          state.api = async (url, method) => {
            calls += 1;
            if (url !== '/api/projects/p1' || method !== 'DELETE') {
              throw new Error(`unexpected delete call ${method} ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {status: 'ok'};
          };

          const first = state.deleteProject('p1');
          await Promise.resolve();
          if (!state.isProjectMutationPending('delete', 'p1')) {
            throw new Error('delete should be pending while confirmation is open');
          }

          const second = state.deleteProject('p1');
          await Promise.resolve();
          if (confirms !== 1) {
            throw new Error(`expected duplicate delete to reuse pending confirmation state, got ${confirms} confirmations`);
          }
          if (calls !== 0) {
            throw new Error(`expected no DELETE before confirmation, got ${calls} calls`);
          }

          releaseConfirm();
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (calls !== 1) {
            throw new Error(`expected duplicate delete to be ignored, got ${calls} calls`);
          }

          releaseApi();
          await first;
          await second;
          if (state.isProjectMutationPending('delete', 'p1')) {
            throw new Error('delete pending state should clear after DELETE finishes');
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_delete_project_refreshes_current_project_list():
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
          let refreshes = 0;
          state.view = 'projects';
          state.projects = [{id: 'p1', name: 'Project'}];
          state.askConfirm = async () => true;
          state.toast = () => {};
          state.api = async (url, method) => {
            if (url !== '/api/projects/p1' || method !== 'DELETE') {
              throw new Error(`unexpected delete call ${method} ${url}`);
            }
            return {status: 'ok'};
          };
          state.loadProjects = async () => {
            refreshes += 1;
            state.projects = [];
          };

          await state.deleteProject('p1');
          if (refreshes !== 1) {
            throw new Error(`expected one list refresh after deleting from project list, got ${refreshes}`);
          }
          if (state.projects.length !== 0) {
            throw new Error(`expected deleted project to disappear from list, got ${JSON.stringify(state.projects)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_cancel_task_does_not_mark_error_when_backend_reports_no_task():
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
          const toasts = [];
          state.currentProject = {id: 'p1', status: 'translated'};
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.api = async () => ({status: 'no_task'});

          await state.cancelTask();

          if (state.currentProject.status !== 'translated') {
            throw new Error(`expected status unchanged, got ${state.currentProject.status}`);
          }
          if (!toasts.some(t => t.type === 'error' && t.message.includes('没有正在运行'))) {
            throw new Error(`expected no-task toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_cancel_task_clears_pipeline_stage_after_backend_cancel():
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
          state.currentProject = {id: 'p1', status: 'created', pipeline_stage: 'download'};
          state.toast = () => {};
          state.api = async () => ({status: 'cancelled'});

          await state.cancelTask();

          if (state.currentProject.status !== 'error' || state.currentProject.pipeline_stage !== null) {
            throw new Error(`expected cancelled busy project to be cleared, got ${JSON.stringify(state.currentProject)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_start_actions_are_disabled_for_pipeline_stage_projects():
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
          state.currentProject = {id: 'p1', status: 'created', pipeline_stage: 'download'};
          state.api = async () => { calls += 1; return {status: 'started'}; };

          if (!state.isProjectBusy(state.currentProject)) {
            throw new Error('expected pipeline-stage project to be busy');
          }
          await state.startASR();
          await state.startTranslate();
          await state.startFull();
          await state.startBurn();

          if (calls !== 0) throw new Error(`expected no API calls, got ${calls}`);
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_translation_required_project_actions_block_when_not_ready():
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
          let apiCalls = 0;
          let settingsOpens = 0;
          let toastMessage = '';
          state.currentProject = {id: 'p1', status: 'created'};
          state.sysCheck = {translation_ready: false, translation_hint: '请配置 OpenAI API 密钥'};
          state.refreshSystemCheck = async () => {};
          state.toast = (msg, type) => { toastMessage = `${type || 'success'}:${msg}`; };
          state.setView = async (view) => {
            if (view === 'settings') settingsOpens += 1;
            state.view = view;
            return true;
          };
          state.api = async () => {
            apiCalls += 1;
            throw new Error('project start API should not be called');
          };

          await state.startTranslate();
          await state.startFull();

          if (apiCalls !== 0) throw new Error(`expected no API calls, got ${apiCalls}`);
          if (settingsOpens !== 2) throw new Error(`expected settings to open twice, got ${settingsOpens}`);
          if (!toastMessage.includes('OpenAI')) throw new Error(`expected translation toast, got ${toastMessage}`);
          if (state.currentProject.status !== 'created') {
            throw new Error(`expected project to remain created, got ${state.currentProject.status}`);
          }
          if (state.projectActionPending !== '') {
            throw new Error(`expected pending action to clear, got ${state.projectActionPending}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_project_start_actions_ignore_duplicate_submits_while_pending():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const cases = [
            ['startASR', '/api/projects/p1/start-asr'],
            ['startTranslate', '/api/projects/p1/start-translate'],
            ['startFull', '/api/projects/p1/start-full'],
            ['startBurn', '/api/projects/p1/burn'],
          ];

          for (const [methodName, expectedUrl] of cases) {
            const state = context.app();
            let calls = 0;
            let releaseApi;
            state.currentProject = {id: 'p1', status: 'created'};
            state.sysCheck = {translation_ready: true};
            state.toast = () => {};
            state.api = async (url, method) => {
              calls += 1;
              if (url !== expectedUrl || method !== 'POST') {
                throw new Error(`unexpected ${methodName} API call ${method} ${url}`);
              }
              await new Promise((resolve) => { releaseApi = resolve; });
              return {status: 'started'};
            };

            const first = state[methodName]();
            await Promise.resolve();
            if (!state.projectActionPending) {
              throw new Error(`${methodName} should mark an action pending`);
            }

            const second = state[methodName]();
            await Promise.resolve();
            if (calls !== 1) {
              throw new Error(`${methodName} should ignore duplicate submits, got ${calls} calls`);
            }

            releaseApi();
            await first;
            await second;
            if (state.projectActionPending !== '') {
              throw new Error(`${methodName} should clear pending action, got ${state.projectActionPending}`);
            }
            if (state.currentProject.status !== 'processing') {
              throw new Error(`${methodName} should mark project processing, got ${state.currentProject.status}`);
            }
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_cancel_task_ignores_duplicate_submits_while_pending():
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
          let releaseApi;
          state.currentProject = {id: 'p1', status: 'processing'};
          state.toast = () => {};
          state.api = async (url, method) => {
            calls += 1;
            if (url !== '/api/projects/p1/cancel' || method !== 'POST') {
              throw new Error(`unexpected cancel API call ${method} ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {status: 'cancelled'};
          };

          const first = state.cancelTask();
          await Promise.resolve();
          if (state.projectActionPending !== 'cancel') {
            throw new Error(`expected cancel pending state, got ${state.projectActionPending}`);
          }

          const second = state.cancelTask();
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate cancel to be ignored, got ${calls} calls`);
          }

          releaseApi();
          await first;
          await second;
          if (state.projectActionPending !== '') {
            throw new Error(`expected pending state to clear, got ${state.projectActionPending}`);
          }
          if (state.currentProject.status !== 'error' || state.currentProject.error !== 'Cancelled by user') {
            throw new Error(`expected cancelled project state, got ${JSON.stringify(state.currentProject)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_normalize_settings_preserves_default_nested_objects():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        const normalized = state.normalizeSettings({
          api_keys: ['bad'],
          translation: {primary_provider: 'deepseek'},
          tmdb: null,
          providers: {claude_cli: {timeout_sec: 240}},
        });
        if (!normalized.api_keys || typeof normalized.api_keys !== 'object' || Array.isArray(normalized.api_keys)) {
          throw new Error('api_keys shape was not preserved');
        }
        if (normalized.translation.primary_provider !== 'deepseek') {
          throw new Error(`translation provider not merged: ${normalized.translation.primary_provider}`);
        }
        if (normalized.tmdb.language !== 'zh-CN') {
          throw new Error(`tmdb defaults lost: ${JSON.stringify(normalized.tmdb)}`);
        }
        if (normalized.providers.claude_cli.model !== 'claude-opus-4-7' || normalized.providers.claude_cli.timeout_sec !== 240) {
          throw new Error(`claude defaults not deeply merged: ${JSON.stringify(normalized.providers.claude_cli)}`);
        }
        const malformed = state.normalizeSettings({
          translation: {primary_provider: {bad: 'shape'}, polish_provider: ' not-a-provider '},
        });
        if (malformed.translation.primary_provider !== 'openai' || malformed.translation.polish_provider !== '') {
          throw new Error(`providers not normalized: ${JSON.stringify(malformed.translation)}`);
        }
        """
    )


def test_frontend_filters_malformed_project_and_subtitle_entries():
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
            if (url === '/api/projects') return [null, {id: 'p1'}, 'bad'];
            if (url === '/api/projects/p1') return {id: 'p1', status: 'created'};
            if (url === '/api/projects/p1/subtitles') {
              return {blocks: [null, {index: 1, text: 'hello'}, 'bad']};
            }
            throw new Error(`unexpected url ${url}`);
          };
          await state.loadProjects();
          if (JSON.stringify(state.projects) !== JSON.stringify([{id: 'p1'}])) {
            throw new Error(`expected only object projects, got ${JSON.stringify(state.projects)}`);
          }
          await state.openProject('p1');
          if (JSON.stringify(state.subtitles) !== JSON.stringify([{index: 1, text: 'hello'}])) {
            throw new Error(`expected only object subtitles, got ${JSON.stringify(state.subtitles)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_open_project_applies_project_language_choices_to_action_controls():
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
          state.asrLanguage = 'auto';
          state.targetLang = '简体中文';
          state.setView = async (view) => { state.view = view; return true; };
          state.connectWS = () => {};
          state.api = async (url) => {
            if (url === '/api/projects/p1') {
              return {
                id: 'p1',
                status: 'created',
                asr_language: 'ja',
                target_language: 'English',
              };
            }
            if (url === '/api/projects/p1/subtitles') return {blocks: []};
            throw new Error(`unexpected url ${url}`);
          };

          await state.openProject('p1');

          if (state.asrLanguage !== 'ja') {
            throw new Error(`expected ASR selector to follow project, got ${state.asrLanguage}`);
          }
          if (state.targetLang !== 'English') {
            throw new Error(`expected target selector to follow project, got ${state.targetLang}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_open_project_ignores_stale_slow_response_when_user_switches_projects():
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
          const connected = [];
          let releaseSlowProject;
          state.toast = () => {};
          state.setView = async (view) => { state.view = view; return true; };
          state.connectWS = (id) => { connected.push(id); };
          state.api = async (url) => {
            if (url === '/api/projects/slow') {
              await new Promise((resolve) => { releaseSlowProject = resolve; });
              return {id: 'slow', name: 'Slow project'};
            }
            if (url === '/api/projects/slow/subtitles') {
              return {blocks: [{index: 1, text: 'slow subtitle'}]};
            }
            if (url === '/api/projects/fast') {
              return {id: 'fast', name: 'Fast project'};
            }
            if (url === '/api/projects/fast/subtitles') {
              return {blocks: [{index: 1, text: 'fast subtitle'}]};
            }
            throw new Error(`unexpected url ${url}`);
          };

          const slow = state.openProject('slow');
          await Promise.resolve();
          const fast = state.openProject('fast');
          await fast;

          if (state.currentProject.id !== 'fast') {
            throw new Error(`expected fast project after fast click, got ${JSON.stringify(state.currentProject)}`);
          }

          releaseSlowProject();
          await slow;

          if (state.currentProject.id !== 'fast') {
            throw new Error(`stale slow project overwrote current project: ${JSON.stringify(state.currentProject)}`);
          }
          if (JSON.stringify(state.subtitles) !== JSON.stringify([{index: 1, text: 'fast subtitle'}])) {
            throw new Error(`stale slow subtitles overwrote current subtitles: ${JSON.stringify(state.subtitles)}`);
          }
          if (JSON.stringify(connected) !== JSON.stringify(['fast'])) {
            throw new Error(`expected only fast websocket connection, got ${JSON.stringify(connected)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_embedded_subtitle_toggle_blocks_duplicate_patch_while_pending():
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
          let releaseApi;
          state.toast = () => {};
          state.currentProject = {id: 'p1', prefer_embedded_subtitle: false};
          state.api = async (url, method, body) => {
            calls += 1;
            if (url !== '/api/projects/p1' || method !== 'PATCH' || body.prefer_embedded_subtitle !== true) {
              throw new Error(`unexpected embedded subtitle PATCH ${method} ${url} ${JSON.stringify(body)}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {id: 'p1', prefer_embedded_subtitle: true};
          };

          const first = state.toggleEmbeddedSubtitle();
          await Promise.resolve();
          if (!state.isProjectMutationPending('embedded-subtitle', 'p1')) {
            throw new Error('embedded subtitle toggle should be pending');
          }

          const second = state.toggleEmbeddedSubtitle();
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate embedded subtitle toggle to be ignored, got ${calls} calls`);
          }

          releaseApi();
          await first;
          await second;
          if (state.isProjectMutationPending('embedded-subtitle', 'p1')) {
            throw new Error('embedded subtitle pending state should clear');
          }
          if (state.currentProject.prefer_embedded_subtitle !== true) {
            throw new Error(`expected embedded subtitle preference to update, got ${JSON.stringify(state.currentProject)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_tmdb_candidate_actions_block_duplicate_patch_while_pending():
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
          let releaseApi;
          const candidate = {
            tmdb_id: 42,
            tmdb_type: 'movie',
            title: 'Movie',
            poster_path: '/poster.jpg',
            original_language: 'en',
          };
          state.toast = () => {};
          state.currentProject = {id: 'p1', tmdb_candidates: [candidate]};
          state.api = async (url, method, body) => {
            calls += 1;
            if (url !== '/api/projects/p1' || method !== 'PATCH' || body.tmdb_id !== 42) {
              throw new Error(`unexpected TMDB PATCH ${method} ${url} ${JSON.stringify(body)}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {id: 'p1', tmdb_id: 42, show_title: 'Movie'};
          };

          const first = state.pickTmdbCandidate(candidate);
          await Promise.resolve();
          if (!state.isProjectMutationPending('tmdb', 'p1')) {
            throw new Error('TMDB pick should be pending');
          }

          const second = state.pickTmdbCandidate(candidate);
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate TMDB pick to be ignored, got ${calls} calls`);
          }

          releaseApi();
          await first;
          await second;
          if (state.isProjectMutationPending('tmdb', 'p1')) {
            throw new Error('TMDB pending state should clear');
          }
          if (state.currentProject.tmdb_id !== 42) {
            throw new Error(`expected TMDB association to update, got ${JSON.stringify(state.currentProject)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_open_provider_page_rejects_unknown_provider_and_uses_noopener():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const opened = [];
        const context = {
          console,
          setTimeout,
          clearTimeout,
          window: {open: (...args) => opened.push(args)},
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        const toasts = [];
        state.toast = (message, type) => { toasts.push({message, type}); };
        state.openProviderPage('not-a-provider');
        if (opened.length !== 0) throw new Error(`unexpected open calls: ${JSON.stringify(opened)}`);
        if (!toasts.some(t => t.type === 'error' && t.message.includes('未知'))) {
          throw new Error(`expected unknown-provider toast, got ${JSON.stringify(toasts)}`);
        }
        state.openProviderPage('openai');
        if (opened.length !== 1 || opened[0][2] !== 'noopener,noreferrer') {
          throw new Error(`expected noopener open, got ${JSON.stringify(opened)}`);
        }
        """
    )
