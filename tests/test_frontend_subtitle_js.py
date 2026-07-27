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


def test_save_video_label_reflects_pending_state():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        if (state.saveVideoLabel() !== '保存视频') {
          throw new Error(`expected idle save label, got ${state.saveVideoLabel()}`);
        }
        state.projectActionPending = 'save-video';
        if (state.saveVideoLabel() !== '保存中...') {
          throw new Error(`expected pending save label, got ${state.saveVideoLabel()}`);
        }
        """
    )


def test_persist_subtitles_refreshes_sound_description_metadata():
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
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: '[grunting]',
            translation: '',
            sound_description: false,
            filtered: false,
          }];
          state.api = async (url, method) => {
            if (url !== '/api/projects/p1/subtitles' || method !== 'PUT') {
              throw new Error(`unexpected request ${method} ${url}`);
            }
            return {
              status: 'ok',
              count: 1,
              blocks: [{
                index: 1,
                start: '00:00:00,000',
                end: '00:00:01,000',
                text: '[grunting]',
                translation: '',
                sound_description: true,
                filtered: false,
              }],
            };
          };

          await state.persistSubtitles();

          if (state.subtitles[0].sound_description !== true) {
            throw new Error(`expected refreshed metadata ${JSON.stringify(state.subtitles[0])}`);
          }
          if (state.subtitleQualitySummary('translated').severe !== 0) {
            throw new Error('refreshed sound cue should not be reported as missing');
          }
        })().catch((error) => {
          console.error(error.message);
          process.exit(1);
        });
        """
    )


def test_sync_subtitle_server_metadata_fails_closed_for_malformed_sound_description():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.subtitles = [
          {index: 1, text: '[wind]', translation: '', sound_description: true, filtered: false},
          {index: 2, text: '[rain]', translation: '', sound_description: true, filtered: false},
          {index: 3, text: '[thunder]', translation: '', sound_description: true, filtered: false},
          {index: 4, text: '[leaves]', translation: '', sound_description: true, filtered: false},
          {index: 5, text: '[waves]', translation: '', sound_description: true, filtered: false},
          {index: 6, text: '[birds]', translation: '', sound_description: true, filtered: false},
          {index: 7, text: '[traffic]', translation: '', sound_description: true, filtered: false},
        ];

        state.syncSubtitleServerMetadata([
          {index: 1},
          {index: 2, sound_description: 'true'},
          {index: 3, sound_description: 1},
          {index: 4, sound_description: false},
          {index: 4, sound_description: true},
          {index: 5, sound_description: true},
          {index: 5, sound_description: false},
          {sound_description: true},
          {index: '7', sound_description: true},
        ]);

        if (state.subtitles.some((item) => item.sound_description !== false)) {
          throw new Error(`malformed server metadata must fail closed: ${JSON.stringify(state.subtitles)}`);
        }
        if (state.subtitleQualitySummary('translated').severe !== 7) {
          throw new Error('malformed server metadata must not suppress missing translations');
        }
        """
    )


def test_persist_subtitles_clears_stale_sound_description_from_server():
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
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: '[grunting]',
            translation: '',
            sound_description: true,
            filtered: false,
          }];
          state.api = async () => ({
            status: 'ok',
            blocks: [{index: 1, sound_description: false}],
          });

          await state.persistSubtitles();

          if (state.subtitles[0].sound_description !== false) {
            throw new Error(`canonical false must clear stale local metadata: ${JSON.stringify(state.subtitles[0])}`);
          }
          if (state.subtitleQualitySummary('translated').severe !== 1) {
            throw new Error('canonical non-sound row must report its missing translation');
          }
        })().catch((error) => {
          console.error(error.message);
          process.exit(1);
        });
        """
    )


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


def test_export_srt_uses_native_save_dialog_when_available():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const saved = [];
        const context = {
          console,
          setTimeout,
          clearTimeout,
          window: {
            pywebview: {
              api: {
                save_text_file: async (filename, content) => {
                  saved.push({filename, content});
                  return {ok: true, path: '/Volumes/Media/movie.translated.srt'};
                },
              },
            },
          },
          Blob: function() { throw new Error('native save must not create a Blob download'); },
          URL: { createObjectURL: () => { throw new Error('native save must not create object URLs'); } },
          document: { createElement: () => { throw new Error('native save must not create anchors'); } },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const toasts = [];
          state.currentProject = {id: 'p1', status: 'translated'};
          state.subtitles = [{index: 1, text: 'Hello', translation: 'Translated', filtered: false}];
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.api = async () => ({content: 'Translated subtitle', filename: '../movie.translated.srt'});

          await state.exportSrt('translated');

          if (saved.length !== 1) throw new Error(`expected one native save, got ${saved.length}`);
          if (saved[0].filename !== 'movie.translated.srt') {
            throw new Error(`expected sanitized filename, got ${saved[0].filename}`);
          }
          if (saved[0].content !== 'Translated subtitle') {
            throw new Error(`unexpected saved content ${saved[0].content}`);
          }
          if (!toasts.some((t) => t.message === '字幕已保存')) {
            throw new Error(`expected saved toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_export_subtitle_can_save_webvtt_with_native_dialog():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const saved = [];
        const context = {
          console,
          setTimeout,
          clearTimeout,
          window: {
            pywebview: {
              api: {
                save_text_file: async (filename, content) => {
                  saved.push({filename, content});
                  return {ok: true, path: `/Volumes/Media/${filename}`};
                },
              },
            },
          },
          Blob: function() { throw new Error('native VTT save must not create a Blob download'); },
          URL: { createObjectURL: () => { throw new Error('native VTT save must not create object URLs'); } },
          document: { createElement: () => { throw new Error('native VTT save must not create anchors'); } },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const toasts = [];
          state.currentProject = {id: 'p1', status: 'translated'};
          state.subtitles = [{index: 1, text: 'Hello', translation: '你好', filtered: false}];
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.api = async (url, method) => {
            if (url !== '/api/projects/p1/export?format=translated&container=vtt' || method !== 'POST') {
              throw new Error(`unexpected VTT export API call ${method} ${url}`);
            }
            return {
              content: 'WEBVTT\\n\\n00:00:00.000 --> 00:00:01.000\\n你好\\n',
              filename: 'movie.translated.vtt',
            };
          };

          if (!state.canExportSubtitle('translated')) {
            throw new Error('expected translated subtitles to be VTT-exportable');
          }
          if (!state.exportSubtitleLabel('translated', 'vtt').includes('VTT')) {
            throw new Error(`expected VTT label, got ${state.exportSubtitleLabel('translated', 'vtt')}`);
          }

          await state.exportSubtitle('translated', 'vtt');

          if (saved.length !== 1) throw new Error(`expected one native VTT save, got ${saved.length}`);
          if (saved[0].filename !== 'movie.translated.vtt') {
            throw new Error(`expected VTT filename, got ${saved[0].filename}`);
          }
          if (!saved[0].content.startsWith('WEBVTT')) {
            throw new Error(`expected WebVTT content, got ${saved[0].content}`);
          }
          if (!toasts.some((t) => t.message === '字幕已保存')) {
            throw new Error(`expected saved toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_save_output_video_uses_native_save_dialog_and_blocks_duplicate_submit():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let calls = 0;
        let releaseSave;
        const context = {
          console,
          setTimeout,
          clearTimeout,
          window: {
            pywebview: {
              api: {
                save_project_video: async (pid, filename) => {
                  calls += 1;
                  if (pid !== 'p1') throw new Error(`unexpected pid ${pid}`);
                  if (filename !== 'movie_subtitled.mp4') throw new Error(`unexpected filename ${filename}`);
                  await new Promise((resolve) => { releaseSave = resolve; });
                  return {ok: true, path: '/Volumes/Media/movie_subtitled.mp4'};
                },
              },
            },
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const toasts = [];
          state.currentProject = {
            id: 'p1',
            status: 'completed',
            name: 'movie.mkv',
            output_video: '/tmp/movie_subtitled.mp4',
          };
          state.toast = (message, type) => { toasts.push({message, type}); };

          const first = state.saveOutputVideo();
          await Promise.resolve();
          if (!state.isSavingVideo()) {
            throw new Error(`expected video save pending, got ${state.projectActionPending}`);
          }

          const second = state.saveOutputVideo();
          await Promise.resolve();
          if (calls !== 1) throw new Error(`expected duplicate save to be ignored, got ${calls}`);
          if (!toasts.some((t) => t.type === 'error' && t.message.includes('未完成'))) {
            throw new Error(`expected duplicate pending toast, got ${JSON.stringify(toasts)}`);
          }

          releaseSave();
          await first;
          await second;

          if (state.projectActionPending !== '') {
            throw new Error(`expected pending to clear, got ${state.projectActionPending}`);
          }
          if (!toasts.some((t) => t.message === '视频已保存')) {
            throw new Error(`expected video saved toast, got ${JSON.stringify(toasts)}`);
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

          if (state.currentProject.status !== 'cancelled' || state.currentProject.pipeline_stage !== null) {
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


def test_project_start_action_refreshes_kb_suggestions_when_review_required():
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
          const calls = [];
          const toasts = [];
          state.currentProject = {id: 'p1', status: 'created'};
          state.sysCheck = {translation_ready: true};
          state.toast = (msg, type) => { toasts.push([msg, type || 'success']); };
          state.api = async (url, method, body) => {
            calls.push([method || 'GET', url, body || null]);
            if (url === '/api/projects/p1/start-translate' && method === 'POST') {
              const err = new Error('翻译前需要先审校自动知识库建议：发现 2 条候选。');
              err.status = 409;
              err.detail = {code: 'kb_review_required', suggestions_count: 2};
              throw err;
            }
            if (url === '/api/knowledge/projects/p1/suggestions') {
              return {suggestions: [{id: 'character:oliver-wolf', source: 'Oliver Wolf', target: '奥利弗·沃尔夫'}]};
            }
            throw new Error(`unexpected API call ${method} ${url}`);
          };

          await state.startTranslate();

          const urls = calls.map((call) => `${call[0]} ${call[1]}`);
          if (!urls.includes('POST /api/projects/p1/start-translate')) {
            throw new Error(`expected translation start, got ${JSON.stringify(calls)}`);
          }
          if (!urls.includes('GET /api/knowledge/projects/p1/suggestions')) {
            throw new Error(`expected suggestions refresh, got ${JSON.stringify(calls)}`);
          }
          if (state.kbSuggestions.length !== 1 || state.kbSuggestions[0].source !== 'Oliver Wolf') {
            throw new Error(`expected refreshed suggestions, got ${JSON.stringify(state.kbSuggestions)}`);
          }
          if (state.currentProject.status !== 'created') {
            throw new Error(`expected project not to be processing, got ${state.currentProject.status}`);
          }
          if (!toasts.some((item) => item[1] === 'error' && item[0].includes('知识库建议'))) {
            throw new Error(`expected KB review toast, got ${JSON.stringify(toasts)}`);
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


def test_audio_project_start_full_uses_transcribe_translate_endpoint():
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
          const calls = [];
          state.currentProject = {id: 'aud1', status: 'created', source_type: 'audio'};
          state.sysCheck = {translation_ready: true};
          state.asrLanguage = 'en';
          state.targetLang = 'English';
          state.toast = () => {};
          state.api = async (url, method, body) => {
            calls.push([method, url, body]);
            if (url === '/api/projects/aud1/start-transcribe-translate' && method === 'POST') {
              return {status: 'started'};
            }
            throw new Error(`unexpected API call ${method} ${url}`);
          };

          await state.startFull();

          if (calls.length !== 1) throw new Error(`expected one API call, got ${JSON.stringify(calls)}`);
          if (calls[0][1] !== '/api/projects/aud1/start-transcribe-translate') {
            throw new Error(`expected audio startFull to skip burn endpoint, got ${JSON.stringify(calls)}`);
          }
          if (calls[0][2].language !== 'en' || calls[0][2].target_language !== 'English') {
            throw new Error(`expected language payload, got ${JSON.stringify(calls)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_source_specific_project_actions_skip_unsupported_pipeline_steps():
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
          const calls = [];
          const toasts = [];
          state.sysCheck = {translation_ready: true};
          state.targetLang = 'English';
          state.asrLanguage = 'en';
          state.toast = (msg, type) => { toasts.push([msg, type || 'success']); };
          state.api = async (url, method, body) => {
            calls.push([method, url, body]);
            if (url === '/api/projects/sub1/start-translate' && method === 'POST') return {status: 'started'};
            throw new Error(`unexpected API call ${method} ${url}`);
          };

          state.currentProject = {id: 'aud1', status: 'created', source_type: 'audio'};
          if (!state.canRunAsr(state.currentProject)) throw new Error('audio projects should support ASR');
          if (state.canBurnVideo(state.currentProject)) throw new Error('audio projects should not support burn');
          await state.startBurn();
          if (calls.length !== 0) throw new Error(`audio burn should not call API, got ${JSON.stringify(calls)}`);
          if (!toasts.some((item) => item[0].includes('视频烧录'))) {
            throw new Error(`expected unsupported burn toast, got ${JSON.stringify(toasts)}`);
          }

          toasts.length = 0;
          state.currentProject = {id: 'sub1', status: 'created', source_type: 'subtitle'};
          if (state.canRunAsr(state.currentProject)) throw new Error('subtitle projects should not support ASR');
          if (state.canBurnVideo(state.currentProject)) throw new Error('subtitle projects should not support burn');
          if (!state.canTranslateProject(state.currentProject)) throw new Error('subtitle projects should support translation');
          if (state.projectPrimaryActionLabel(state.currentProject) !== '翻译字幕') {
            throw new Error(`expected subtitle primary label, got ${state.projectPrimaryActionLabel(state.currentProject)}`);
          }
          await state.startASR();
          await state.startBurn();
          if (calls.length !== 0) throw new Error(`subtitle ASR/burn should not call API, got ${JSON.stringify(calls)}`);

          await state.startFull();
          if (calls.length !== 1) throw new Error(`subtitle primary action should call one API, got ${JSON.stringify(calls)}`);
          if (calls[0][1] !== '/api/projects/sub1/start-translate') {
            throw new Error(`subtitle primary action should translate only, got ${JSON.stringify(calls)}`);
          }
          if (calls[0][2].target_language !== 'English') {
            throw new Error(`expected target language payload, got ${JSON.stringify(calls)}`);
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
          if (state.currentProject.status !== 'cancelled' || state.currentProject.error !== null || state.currentProject.progress_msg !== '已取消') {
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
        if ('model' in normalized.providers.claude_cli || normalized.providers.claude_cli.timeout_sec !== 240) {
          throw new Error(`claude defaults not deeply merged: ${JSON.stringify(normalized.providers.claude_cli)}`);
        }
        if (normalized.translation.primary_effort !== 'auto' || normalized.translation.polish_effort !== 'auto') {
          throw new Error(`reasoning effort defaults lost: ${JSON.stringify(normalized.translation)}`);
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


def test_project_metadata_save_patches_manual_context():
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
          let loadProjectsCalls = 0;
          state.toast = () => {};
          state.loadProjects = async () => { loadProjectsCalls += 1; };
          state.currentProject = {
            id: 'p1',
            content_type: 'academic_lecture',
            original_language: ' en ',
            academic_field: ' machine learning ',
            content_notes: ' Lecture about gradient descent. ',
            manual_terms: ' gradient descent=梯度下降 ',
          };
          state.api = async (url, method, body) => {
            calls += 1;
            if (url !== '/api/projects/p1' || method !== 'PATCH') {
              throw new Error(`unexpected metadata PATCH ${method} ${url}`);
            }
            if (body.content_type !== 'academic_lecture') throw new Error(`bad content type ${body.content_type}`);
            if (body.original_language !== 'en') throw new Error(`bad language ${body.original_language}`);
            if (body.academic_field !== 'machine learning') throw new Error(`bad field ${body.academic_field}`);
            if (body.content_notes !== 'Lecture about gradient descent.') throw new Error(`bad notes ${body.content_notes}`);
            if (body.manual_terms !== 'gradient descent=梯度下降') throw new Error(`bad terms ${body.manual_terms}`);
            if (body.metadata_source !== 'manual') throw new Error(`bad metadata source ${body.metadata_source}`);
            return {id: 'p1', content_type: 'academic_lecture', metadata_source: 'manual'};
          };

          await state.saveProjectMetadata();
          if (calls !== 1) throw new Error(`expected one metadata PATCH, got ${calls}`);
          if (loadProjectsCalls !== 1) throw new Error(`expected projects reload, got ${loadProjectsCalls}`);
          if (state.currentProject.metadata_source !== 'manual') {
            throw new Error(`expected current project to update, got ${JSON.stringify(state.currentProject)}`);
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


def test_mergeSubtitleWithNext_combines_adjacent_rows_and_persists():
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
          state.currentProject = {id: 'p1'};
          state.toast = () => {};
          state.persistSubtitles = async () => { persisted += 1; state.renumberSubtitles(); };
          state.subtitles = [
            {
              index: 1,
              start: '00:00:00,000',
              end: '00:00:01,000',
              text: 'Hello',
              translation: '你好',
              filtered: false,
              filter_reason: '',
            },
            {
              index: 2,
              start: '00:00:01,000',
              end: '00:00:03,000',
              text: 'world',
              translation: '世界',
              filtered: false,
              filter_reason: '',
            },
          ];

          await state.mergeSubtitleWithNext(0);

          if (persisted !== 1) throw new Error(`expected one persist, got ${persisted}`);
          if (state.subtitles.length !== 1) throw new Error(`expected one merged row, got ${state.subtitles.length}`);
          const merged = state.subtitles[0];
          if (merged.index !== 1 || merged.start !== '00:00:00,000' || merged.end !== '00:00:03,000') {
            throw new Error(`expected merged timing/index, got ${JSON.stringify(merged)}`);
          }
          if (merged.text !== 'Hello\\nworld' || merged.translation !== '你好\\n世界') {
            throw new Error(`expected joined text, got ${JSON.stringify(merged)}`);
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


def test_mergeSubtitleWithNext_rolls_back_when_persist_fails():
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
          state.currentProject = {id: 'p1'};
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.persistSubtitles = async () => { throw new Error('backend rejected'); };
          state.subtitles = [
            {index: 1, start: '00:00:00,000', end: '00:00:01,000', text: 'A', translation: '甲', filtered: false, filter_reason: ''},
            {index: 2, start: '00:00:01,000', end: '00:00:02,000', text: 'B', translation: '乙', filtered: false, filter_reason: ''},
          ];
          const before = JSON.stringify(state.subtitles);

          await state.mergeSubtitleWithNext(0);

          if (JSON.stringify(state.subtitles) !== before) {
            throw new Error(`expected rollback, got ${JSON.stringify(state.subtitles)}`);
          }
          if (!toasts.some((t) => t.type === 'error' && t.message.includes('保存失败'))) {
            throw new Error(`expected save failure toast, got ${JSON.stringify(toasts)}`);
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


def test_subtitle_quality_summary_flags_timing_translation_and_reading_speed():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.subtitles = [
          {
            index: 1,
            start: '00:00:00,000',
            end: '00:00:02,000',
            text: 'This subtitle line is deliberately very long and should trip the long line detector in the editor quality model.',
            translation: '',
            filtered: false,
            filter_reason: '',
          },
          {
            index: 2,
            start: '00:00:01,500',
            end: '00:00:01,500',
            text: 'Too fast to read because this sentence has many characters packed into no duration.',
            translation: '译文',
            filtered: false,
            filter_reason: '',
          },
          {
            index: 3,
            start: '00:00:01,400',
            end: '00:00:03,000',
            text: '',
            translation: 'Only translated',
            filtered: false,
            filter_reason: '',
          },
          {
            index: 4,
            start: '00:00:04,000',
            end: '00:00:06,000',
            text: 'Normal source',
            translation: '这是一条故意写得非常非常非常非常非常非常非常非常非常非常非常非常长的译文，用来触发长行检测',
            filtered: false,
            filter_reason: '',
          },
        ];

        const issues = state.subtitleQualityIssues();
        const codes = issues.map((issue) => issue.code);
        for (const expected of ['missing_translation', 'overlap', 'non_positive_duration', 'long_line', 'reading_speed', 'empty_source']) {
          if (!codes.includes(expected)) {
            throw new Error(`missing quality code ${expected}: ${JSON.stringify(issues)}`);
          }
        }
        const summary = state.subtitleQualitySummary();
        if (summary.total !== issues.length || summary.severe < 3 || summary.warning < 2) {
          throw new Error(`unexpected summary ${JSON.stringify(summary)} for ${JSON.stringify(issues)}`);
        }
        if (!state.hasSevereSubtitleIssues()) {
          throw new Error('expected severe subtitle issues');
        }
        """
    )


def test_subtitle_quality_uses_backend_sound_description_metadata():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.subtitles = [
          {
            index: 10,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: '[gunshots]\\n[people shouting]',
            translation: '',
            sound_description: true,
            filtered: false,
          },
          {
            index: 11,
            start: '00:00:01,000',
            end: '00:00:02,000',
            text: '[The Martian]',
            translation: '',
            sound_description: false,
            filtered: false,
          },
        ];

        const summary = state.subtitleQualitySummary('translated');
        const missing = summary.issues.filter((issue) => issue.code === 'missing_translation');
        if (summary.severe !== 1 || missing.length !== 1 || missing[0].index !== 11) {
          throw new Error(`unexpected canonical classification result ${JSON.stringify(summary)}`);
        }
        """
    )


def test_translated_export_quality_ignores_sound_cues_and_source_only_length():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.subtitles = [
          {
            index: 18,
            start: '00:00:45,012',
            end: '00:00:47,114',
            text: '[ Thunder crashes ]',
            translation: '',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 19,
            start: '00:00:47,180',
            end: '00:00:50,417',
            text: 'This English source line is deliberately long enough that it would be noisy if translated export checked source line length.',
            translation: '译文合格。',
            sound_description: false,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 20,
            start: '00:00:50,500',
            end: '00:00:54,000',
            text: '♪♪',
            translation: '♪♪',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 21,
            start: '00:00:54,500',
            end: '00:00:59,000',
            text: '♪ I know ♪',
            translation: '',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 60,
            start: '00:01:00,000',
            end: '00:01:02,000',
            text: '-[inspiring music]\\n-[dinosaur soft roar]',
            translation: '',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 95,
            start: '00:01:03,000',
            end: '00:01:05,000',
            text: '♪ The evening breeze',
            translation: '',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 398,
            start: '00:01:06,000',
            end: '00:01:08,000',
            text: '-[shrieking]\\n-[roaring]',
            translation: '',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 433,
            start: '00:01:09,000',
            end: '00:01:11,000',
            text: '[buzzing]',
            translation: '',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 495,
            start: '00:01:12,000',
            end: '00:01:14,000',
            text: '[dinosaur snarls]',
            translation: '',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
          {
            index: 496,
            start: '00:01:15,000',
            end: '00:01:17,000',
            text: '[squawking]',
            translation: '',
            sound_description: true,
            filtered: false,
            filter_reason: '',
          },
        ];

        const translated = state.subtitleQualitySummary('translated');
        if (translated.severe !== 0 || translated.warning !== 0) {
          throw new Error(`translated export should ignore sound cue blanks and source-only length: ${JSON.stringify(translated)}`);
        }
        if (state.hasSevereSubtitleIssues('translated')) {
          throw new Error('translated export should not have severe issues');
        }
        if (state.subtitleExportWarningMessage('translated') !== '') {
          throw new Error(`unexpected translated export warning: ${state.subtitleExportWarningMessage('translated')}`);
        }

        const bilingual = state.subtitleQualitySummary('bilingual');
        if (!bilingual.issues.some((issue) => issue.code === 'long_line')) {
          throw new Error(`bilingual export should still check source line length: ${JSON.stringify(bilingual)}`);
        }
        """
    )


def test_focus_subtitle_by_id_opens_matching_row_for_edit():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        const toasts = [];
        state.toast = (message, type) => { toasts.push({message, type}); };
        state.subtitles = [
          {index: 1, text: 'Hello', translation: '你好'},
          {index: 12, text: 'Hudson Oaks', translation: '哈德森橡树'},
        ];

        if (!state.focusSubtitleById(12)) {
          throw new Error('expected focus to succeed');
        }
        if (state.editingIdx !== 1 || state.editText !== '哈德森橡树') {
          throw new Error(`expected row 12 edit state, got ${state.editingIdx}/${state.editText}`);
        }
        if (state.focusSubtitleById(99)) {
          throw new Error('expected missing row focus to fail');
        }
        if (!toasts.some((item) => item.type === 'error' && item.message.includes('99'))) {
          throw new Error(`expected missing row toast, got ${JSON.stringify(toasts)}`);
        }
        """
    )


def test_subtitle_replace_preview_counts_without_mutating_rows():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.subtitles = [
          {index: 1, text: 'Tony Stark enters', translation: 'Stark 来了', filtered: false},
          {index: 2, text: 'Pepper waits', translation: 'stark 迟到了', filtered: false},
          {index: 3, text: 'Archived Stark', translation: 'Stark filtered', filtered: true},
        ];
        state.subtitleFindText = 'Stark';
        state.subtitleReplaceText = '史塔克';
        state.subtitleReplaceScope = 'translation';
        state.subtitleReplaceCaseSensitive = false;
        const before = JSON.stringify(state.subtitles);

        const preview = state.subtitleReplacePreview();

        if (preview.count !== 2 || preview.rows.length !== 2) {
          throw new Error(`expected two replacement hits, got ${JSON.stringify(preview)}`);
        }
        if (JSON.stringify(state.subtitles) !== before) {
          throw new Error('replace preview mutated subtitles');
        }
        """
    )


def test_apply_subtitle_replace_persists_and_rolls_back_on_failure():
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
          const toasts = [];
          state.currentProject = {id: 'p1'};
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.persistSubtitles = async () => { persisted += 1; state.renumberSubtitles(); };
          state.subtitles = [
            {index: 1, text: 'Tony Stark', translation: 'Stark 来了', filtered: false},
            {index: 2, text: 'Pepper', translation: 'stark 迟到了', filtered: false},
          ];
          state.subtitleFindText = 'Stark';
          state.subtitleReplaceText = '史塔克';
          state.subtitleReplaceScope = 'translation';
          state.subtitleReplaceCaseSensitive = false;

          await state.applySubtitleReplace();

          if (persisted !== 1) throw new Error(`expected one persist, got ${persisted}`);
          if (state.subtitles[0].translation !== '史塔克 来了' || state.subtitles[1].translation !== '史塔克 迟到了') {
            throw new Error(`unexpected replaced translations: ${JSON.stringify(state.subtitles)}`);
          }
          if (!toasts.some((t) => t.message.includes('已替换 2 处'))) {
            throw new Error(`expected replacement toast, got ${JSON.stringify(toasts)}`);
          }

          const beforeFailure = JSON.stringify(state.subtitles);
          state.persistSubtitles = async () => { throw new Error('backend rejected'); };
          state.subtitleFindText = '史塔克';
          state.subtitleReplaceText = 'Stark';

          await state.applySubtitleReplace();

          if (JSON.stringify(state.subtitles) !== beforeFailure) {
            throw new Error(`expected rollback after failed replace, got ${JSON.stringify(state.subtitles)}`);
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


def test_export_quality_requires_confirmation_before_api_call_for_severe_issues():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          Blob: function(parts, options) {
            this.parts = parts;
            this.options = options;
          },
          URL: {
            createObjectURL: () => 'blob:quality-export',
            revokeObjectURL: () => {},
          },
          document: {
            body: { appendChild: () => {} },
            createElement: () => ({ click: () => {}, remove: () => {} }),
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let calls = 0;
          let confirms = 0;
          state.currentProject = {id: 'p1', status: 'translated'};
          state.subtitles = [
            {index: 1, start: '00:00:00,000', end: '00:00:00,000', text: '', translation: '可导出的译文', filtered: false},
          ];
          state.toast = () => {};
          state.askConfirm = async (options) => {
            confirms += 1;
            if (!String(options.message || '').includes('严重问题')) {
              throw new Error(`expected severe warning message, got ${JSON.stringify(options)}`);
            }
            return confirms > 1;
          };
          state.api = async (url, method) => {
            calls += 1;
            if (url !== '/api/projects/p1/export?format=translated' || method !== 'POST') {
              throw new Error(`unexpected export API ${method} ${url}`);
            }
            return {content: 'Translated subtitle', filename: 'movie.translated.srt'};
          };

          await state.exportSrt('translated');
          if (calls !== 0 || confirms !== 1) {
            throw new Error(`declined export should not call API, got calls=${calls} confirms=${confirms}`);
          }

          await state.exportSrt('translated');
          if (calls !== 1 || confirms !== 2) {
            throw new Error(`accepted export should call API once, got calls=${calls} confirms=${confirms}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_normal_blank_dialogue_blocks_export_before_api_call():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          Blob: function(parts, options) {
            this.parts = parts;
            this.options = options;
          },
          URL: {
            createObjectURL: () => 'blob:quality-export',
            revokeObjectURL: () => {},
          },
          document: {
            body: { appendChild: () => {} },
            createElement: () => ({ click: () => {}, remove: () => {} }),
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let calls = 0;
          let confirms = 0;
          state.currentProject = {id: 'p1', status: 'translated'};
          state.subtitles = [
            {
              index: 1,
              start: '00:00:00,000',
              end: '00:00:01,000',
              text: 'This is ordinary dialogue.',
              translation: '',
              sound_description: false,
              filtered: false,
            },
            {
              index: 2,
              start: '00:00:01,000',
              end: '00:00:02,000',
              text: 'This translated row makes export available.',
              translation: '这行已有译文。',
              sound_description: false,
              filtered: false,
            },
          ];
          state.toast = () => {};
          state.askConfirm = async () => {
            confirms += 1;
            return false;
          };
          state.api = async () => {
            calls += 1;
            throw new Error('export API must not be called after declined confirmation');
          };

          const summary = state.subtitleQualitySummary('translated');
          const missing = summary.issues.filter((issue) => issue.code === 'missing_translation');
          if (summary.severe !== 1 || missing.length !== 1 || missing[0].index !== 1) {
            throw new Error(`ordinary blank dialogue must be a severe missing translation: ${JSON.stringify(summary)}`);
          }

          await state.exportSrt('translated');
          if (confirms !== 1 || calls !== 0) {
            throw new Error(`declined ordinary-dialogue export must not call API: calls=${calls} confirms=${confirms}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_subtitle_timeline_segments_use_project_duration_and_clamp_widths():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.currentProject = {id: 'p1', duration: 4};
        state.subtitles = [
          {index: 1, start: '00:00:00,000', end: '00:00:01,000', text: 'A', translation: '甲', filtered: false},
          {index: 2, start: '00:00:02,000', end: '00:00:06,000', text: 'B', translation: '乙', filtered: false},
          {index: 3, start: 'bad', end: '00:00:03,000', text: 'C', translation: '丙', filtered: true},
        ];

        const segments = state.subtitleTimelineSegments();

        if (segments.length !== 3) throw new Error(`expected 3 segments, got ${JSON.stringify(segments)}`);
        if (segments[0].left !== 0 || segments[0].width !== 25) {
          throw new Error(`unexpected first segment ${JSON.stringify(segments[0])}`);
        }
        if (segments[1].left !== 50 || segments[1].width !== 50) {
          throw new Error(`expected clamped second segment, got ${JSON.stringify(segments[1])}`);
        }
        if (!segments[2].filtered || segments[2].width <= 0) {
          throw new Error(`expected filtered fallback segment, got ${JSON.stringify(segments[2])}`);
        }
        """
    )


def test_subtitle_shortcuts_dispatch_common_editor_actions():
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
          const calls = [];
          state.saveEdit = async (idx) => { calls.push(['save', idx]); };
          state.splitSubtitle = async (idx) => { calls.push(['split', idx]); };
          state.mergeSubtitleWithNext = async (idx) => { calls.push(['merge', idx]); };
          state.addSubtitleAfter = async (idx) => { calls.push(['add', idx]); };
          state.deleteSubtitle = async (idx) => { calls.push(['delete', idx]); };
          const event = (key, extra = {}) => ({
            key,
            ctrlKey: true,
            metaKey: false,
            shiftKey: false,
            prevented: false,
            preventDefault() { this.prevented = true; },
            ...extra,
          });

          const save = event('Enter');
          const split = event('S', {shiftKey: true});
          const merge = event('m', {shiftKey: true});
          const add = event('A', {shiftKey: true});
          const del = event('Backspace');
          const ignored = event('x', {ctrlKey: false, metaKey: false});

          await state.handleSubtitleShortcut(save, 4);
          await state.handleSubtitleShortcut(split, 4);
          await state.handleSubtitleShortcut(merge, 4);
          await state.handleSubtitleShortcut(add, 4);
          await state.handleSubtitleShortcut(del, 4);
          const ignoredResult = await state.handleSubtitleShortcut(ignored, 4);

          const expected = JSON.stringify([
            ['save', 4],
            ['split', 4],
            ['merge', 4],
            ['add', 4],
            ['delete', 4],
          ]);
          if (JSON.stringify(calls) !== expected) {
            throw new Error(`unexpected shortcut dispatch ${JSON.stringify(calls)}`);
          }
          for (const item of [save, split, merge, add, del]) {
            if (!item.prevented) throw new Error(`expected ${item.key} shortcut to prevent default`);
          }
          if (ignored.prevented || ignoredResult !== false) {
            throw new Error('plain key should be ignored without preventDefault');
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )
