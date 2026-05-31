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


def test_upload_video_formats_validation_detail_errors():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          FormData,
          Blob,
          fetch: async () => ({
            ok: false,
            status: 422,
            statusText: 'Unprocessable Entity',
            json: async () => ({
              detail: [
                {loc: ['body', 'file'], msg: 'Expected UploadFile'},
              ],
            }),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          try {
            await state.uploadVideoFile(new Blob(['video']));
          } catch (e) {
            if (!e.message.includes('file: Expected UploadFile')) {
              throw new Error(`expected formatted validation error, got ${e.message}`);
            }
            if (e.message.includes('[object Object]')) {
              throw new Error(`expected no object-string error, got ${e.message}`);
            }
            return;
          }
          throw new Error('expected uploadVideoFile to throw');
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_quick_start_ignores_duplicate_project_creation():
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
          let creates = 0;
          state.newVideoPath = '/tmp/movie.mp4';
          state.sysCheck = {translation_ready: true};
          state.toast = () => {};
          state.setView = async () => {};
          state.connectWS = () => {};
          state.api = async (url, method) => {
            if (url === '/api/projects' && method === 'POST') {
              creates += 1;
              await new Promise(resolve => setTimeout(resolve, 20));
              return {id: 'p1', status: 'created'};
            }
            if (url === '/api/projects/p1/start-full' && method === 'POST') {
              return {status: 'ok'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          const first = state.quickStart();
          const second = state.quickStart();
          await Promise.all([first, second]);

          if (creates !== 1) {
            throw new Error(`expected one project create request, got ${creates}`);
          }
          if (state.projectCreating !== false) {
            throw new Error(`expected projectCreating to reset, got ${state.projectCreating}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_quick_start_ignores_manual_submit_while_file_import_is_busy():
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
          state.newVideoPath = '/tmp/movie.mp4';
          state.fileImporting = true;
          state.sysCheck = {translation_ready: true};
          state.toast = () => {};
          state.api = async () => {
            calls += 1;
            throw new Error('project API should not be called during file import');
          };

          await state.quickStart();

          if (calls !== 0) throw new Error(`expected no project API calls, got ${calls}`);
          if (state.projectCreating !== false) {
            throw new Error(`expected projectCreating to stay false, got ${state.projectCreating}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_selected_file_path_can_start_project_during_import_flow():
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
          let creates = 0;
          state.sysCheck = {translation_ready: true};
          state.toast = () => {};
          state.setView = async () => {};
          state.connectWS = () => {};
          state.api = async (url, method) => {
            if (url === '/api/projects' && method === 'POST') {
              creates += 1;
              return {id: 'p1', status: 'created'};
            }
            if (url === '/api/projects/p1/start-full' && method === 'POST') {
              return {status: 'ok'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          await state.useSelectedVideoFile({name: 'movie.mp4', path: '/tmp/movie.mp4'});

          if (creates !== 1) throw new Error(`expected selected file path to create one project, got ${creates}`);
          if (state.fileImporting !== false || state.projectCreating !== false) {
            throw new Error(`expected busy flags to reset, got ${state.fileImporting}/${state.projectCreating}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_quick_start_blocks_when_translation_is_not_ready():
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
          let settingsOpened = false;
          let toastMessage = '';
          state.newVideoPath = '/tmp/movie.mp4';
          state.sysCheck = {translation_ready: false, translation_hint: '请配置 OpenAI API 密钥'};
          state.refreshSystemCheck = async () => {};
          state.toast = (msg, type) => {
            toastMessage = `${type || 'success'}:${msg}`;
          };
          state.setView = async (view) => {
            if (view === 'settings') settingsOpened = true;
            state.view = view;
            return true;
          };
          state.api = async () => {
            apiCalls += 1;
            throw new Error('project API should not be called');
          };

          await state.quickStart();

          if (apiCalls !== 0) throw new Error(`expected no project API calls, got ${apiCalls}`);
          if (!settingsOpened) throw new Error('expected settings view to open');
          if (!toastMessage.includes('OpenAI')) {
            throw new Error(`expected actionable translation toast, got ${toastMessage}`);
          }
          if (state.projectCreating !== false) {
            throw new Error(`expected projectCreating to reset, got ${state.projectCreating}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_quick_start_sends_selected_workflow_languages_when_creating_project():
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
          let createBody = null;
          state.newVideoPath = '/tmp/movie.mp4';
          state.sysCheck = {translation_ready: true};
          state.asrLanguage = 'ja';
          state.targetLang = 'English';
          state.toast = () => {};
          state.setView = async () => {};
          state.connectWS = () => {};
          state.api = async (url, method, body) => {
            if (url === '/api/projects' && method === 'POST') {
              createBody = body;
              return {id: 'p1', status: 'created'};
            }
            if (url === '/api/projects/p1/start-full' && method === 'POST') {
              return {status: 'ok'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          await state.quickStart();

          if (!createBody || createBody.asr_language !== 'ja' || createBody.target_language !== 'English') {
            throw new Error(`expected workflow languages in create body, got ${JSON.stringify(createBody)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_video_file_import_ignores_duplicate_uploads_while_busy():
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
          let uploads = 0;
          let starts = 0;
          state.toast = () => {};
          state.uploadVideoFile = async () => {
            uploads += 1;
            await new Promise(resolve => setTimeout(resolve, 20));
            return '/tmp/uploaded.mp4';
          };
          state.quickStart = async () => { starts += 1; };

          const file = {name: 'movie.mp4'};
          const first = state.useSelectedVideoFile(file);
          const second = state.useSelectedVideoFile(file);
          await Promise.all([first, second]);

          if (uploads !== 1) {
            throw new Error(`expected one upload while busy, got ${uploads}`);
          }
          if (starts !== 1) {
            throw new Error(`expected one quick start after upload, got ${starts}`);
          }
          if (state.fileImporting !== false) {
            throw new Error(`expected fileImporting to reset, got ${state.fileImporting}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )
