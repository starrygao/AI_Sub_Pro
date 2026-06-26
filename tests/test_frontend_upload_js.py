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


def test_drop_video_uri_uses_local_path_without_uploading_large_file():
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
          const starts = [];
          const event = {
            prevented: false,
            stopped: false,
            preventDefault() { this.prevented = true; },
            stopPropagation() { this.stopped = true; },
            dataTransfer: {
              files: [{name: 'My Movie.mkv'}],
              getData(type) {
                return type === 'text/uri-list'
                  ? 'file:///Users/me/Movies/My%20Movie.mkv\\n'
                  : '';
              },
            },
          };
          state.toast = () => {};
          state.uploadVideoFile = async () => {
            throw new Error('dragged local videos should not be uploaded');
          };
          state.quickStart = async (options) => {
            starts.push([state.newVideoPath, options]);
          };

          await state.handleDrop(event);

          if (!event.prevented || !event.stopped) {
            throw new Error('expected drop event propagation to be stopped and prevented');
          }
          if (starts.length !== 1) {
            throw new Error(`expected one local quick start, got ${JSON.stringify(starts)}`);
          }
          if (starts[0][0] !== '/Users/me/Movies/My Movie.mkv') {
            throw new Error(`expected decoded local path, got ${starts[0][0]}`);
          }
          if (!starts[0][1]?.allowDuringImport) {
            throw new Error(`expected import-aware quick start, got ${JSON.stringify(starts[0][1])}`);
          }
          if (state.fileImporting !== false) {
            throw new Error(`expected fileImporting reset, got ${state.fileImporting}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_desktop_drop_without_path_refuses_video_upload_fallback():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          window: {pywebview: {api: {}}},
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let uploads = 0;
          let starts = 0;
          const toasts = [];
          state.toast = (message, type) => { toasts.push([message, type || 'success']); };
          state.uploadVideoFile = async () => {
            uploads += 1;
            return '/tmp/uploaded.mkv';
          };
          state.quickStart = async () => { starts += 1; };

          await state.handleDrop({
            dataTransfer: {
              files: [{name: 'movie.mkv'}],
              getData() { return ''; },
            },
          });

          if (uploads !== 0) throw new Error(`expected no desktop video upload fallback, got ${uploads}`);
          if (starts !== 0) throw new Error(`expected no quick start without a local path, got ${starts}`);
          if (!toasts.some((toast) => String(toast[0]).includes('未获得视频本地路径'))) {
            throw new Error(`expected clear missing-path toast, got ${JSON.stringify(toasts)}`);
          }
          if (state.fileImporting !== false) {
            throw new Error(`expected fileImporting to stay false, got ${state.fileImporting}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_batch_drop_uri_list_starts_video_paths_without_folder_dialog():
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
          state.homeSourceMode = 'batch';
          state.toast = () => {};
          state.startBatchVideoPaths = async (paths, options) => {
            calls.push([paths, options]);
          };
          state.quickStartBatch = async () => {
            throw new Error('video URI drops should not open folder discovery');
          };

          await state.handleDrop({
            dataTransfer: {
              files: [],
              getData(type) {
                return type === 'text/uri-list'
                  ? 'file:///Shows/A.mkv\\nfile:///Shows/B.mp4\\n'
                  : '';
              },
            },
          });

          if (calls.length !== 1) {
            throw new Error(`expected one batch path start, got ${JSON.stringify(calls)}`);
          }
          if (JSON.stringify(calls[0][0]) !== JSON.stringify(['/Shows/A.mkv', '/Shows/B.mp4'])) {
            throw new Error(`expected decoded batch video paths, got ${JSON.stringify(calls)}`);
          }
          if (calls[0][1]?.sourceLabel !== '拖入的视频文件') {
            throw new Error(`expected drag source label, got ${JSON.stringify(calls[0][1])}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_drop_zone_click_is_suppressed_immediately_after_drop():
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
          let pickerCalls = 0;
          state.openPrimaryPicker = async () => { pickerCalls += 1; };

          state.dropClickSuppressUntil = Date.now() + 1000;
          await state.handleDropZoneClick();
          if (pickerCalls !== 0) {
            throw new Error(`expected suppressed picker click, got ${pickerCalls}`);
          }

          state.dropClickSuppressUntil = 0;
          await state.handleDropZoneClick();
          if (pickerCalls !== 1) {
            throw new Error(`expected picker click after suppression expires, got ${pickerCalls}`);
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


def test_quick_start_opens_task_settings_after_project_create_and_uses_selection():
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
          state.newVideoPath = '/tmp/movie.mp4';
          state.sysCheck = {translation_ready: true};
          state.asrLanguage = 'en';
          state.targetLang = '简体中文';
          state.toast = () => {};
          state.setView = async (view) => { calls.push(['view', view]); state.view = view; return true; };
          state.connectWS = (pid) => { calls.push(['ws', pid]); };
          state.openTaskSettings = async (options) => {
            calls.push(['settings', options.title, options.canBurn, state.currentProject?.id]);
            if (state.currentProject?.id !== 'p1') {
              throw new Error(`expected project to be recognized before task settings, got ${JSON.stringify(state.currentProject)}`);
            }
            return {
              workflow_mode: 'translate_only',
              asr_language: 'fr',
              target_language: 'English',
            };
          };
          state.api = async (url, method, body) => {
            calls.push([method, url, body]);
            if (url === '/api/projects' && method === 'POST') {
              return {id: 'p1', status: 'created', source_type: 'upload', asr_language: 'en', target_language: '简体中文'};
            }
            if (url === '/api/projects/p1/start-full' && method === 'POST') {
              return {status: 'started', stage: 'asr_translate'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          await state.quickStart();

          const settingsIndex = calls.findIndex((call) => call[0] === 'settings');
          const createIndex = calls.findIndex((call) => call[1] === '/api/projects');
          const startCall = calls.find((call) => call[1] === '/api/projects/p1/start-full');
          if (createIndex < 0 || settingsIndex < 0 || !(createIndex < settingsIndex)) {
            throw new Error(`expected task settings after project create, got ${JSON.stringify(calls)}`);
          }
          if (!startCall) throw new Error(`expected start-full call, got ${JSON.stringify(calls)}`);
          const body = startCall[2] || {};
          if (body.workflow_mode !== 'translate_only' || body.language !== 'fr' || body.target_language !== 'English') {
            throw new Error(`expected selected task settings in start body, got ${JSON.stringify(body)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_quick_start_batch_discovers_folder_and_starts_each_video():
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
          state.newVideoPath = '/Shows';
          state.sysCheck = {translation_ready: true};
          state.toast = (message, type) => { toasts.push([message, type || 'success']); };
          state.loadProjects = async () => { calls.push(['loadProjects']); };
          state.setView = async (view) => { calls.push(['view', view]); state.view = view; return true; };
          state.openTaskSettings = async (options) => {
            calls.push(['settings', options.title, options.message, options.workflow_mode]);
            return {
              workflow_mode: 'translate_only',
              asr_language: 'en',
              target_language: '简体中文',
            };
          };
          let projectSeq = 0;
          state.api = async (url, method, body) => {
            calls.push([method, url, body]);
            if (url === '/api/projects/discover-local-videos' && method === 'POST') {
              return {
                videos: [
                  {path: '/Shows/A.mkv', name: 'A.mkv'},
                  {path: '/Shows/B.mp4', name: 'B.mp4'},
                ],
                truncated: false,
              };
            }
            if (url === '/api/projects' && method === 'POST') {
              projectSeq += 1;
              return {id: `p${projectSeq}`, source_type: 'upload', status: 'created'};
            }
            if (url === `/api/projects/p${projectSeq}/start-full` && method === 'POST') {
              return {status: 'started'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          await state.quickStartBatch();

          const creates = calls.filter((call) => call[0] === 'POST' && call[1] === '/api/projects');
          const starts = calls.filter((call) => call[0] === 'POST' && call[1].endsWith('/start-full'));
          if (creates.length !== 2 || starts.length !== 2) {
            throw new Error(`expected two create/start calls, got ${JSON.stringify(calls)}`);
          }
          if (creates[0][2].asr_language !== 'en' || creates[1][2].target_language !== '简体中文') {
            throw new Error(`expected selected languages in create calls, got ${JSON.stringify(creates)}`);
          }
          if (!starts.every((call) => call[2].workflow_mode === 'translate_only')) {
            throw new Error(`expected translate_only batch start, got ${JSON.stringify(starts)}`);
          }
          if (!calls.some((call) => call[0] === 'settings' && call[3] === 'translate_only')) {
            throw new Error(`expected batch settings default to translate_only, got ${JSON.stringify(calls)}`);
          }
          if (!calls.some((call) => call[0] === 'view' && call[1] === 'projects')) {
            throw new Error(`expected batch start to return to projects view, got ${JSON.stringify(calls)}`);
          }
          if (!toasts.some((toast) => String(toast[0]).includes('批量任务已启动：2 个'))) {
            throw new Error(`expected success toast, got ${JSON.stringify(toasts)}`);
          }
          if (state.projectCreating !== false || state.newVideoPath !== '') {
            throw new Error(`expected batch state to reset, got ${state.projectCreating}/${state.newVideoPath}`);
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


def test_home_source_mode_routes_supported_sources_and_explains_pending_ones():
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
          if (state.homeSourceMode !== 'local') {
            throw new Error(`expected local source by default, got ${state.homeSourceMode}`);
          }

          const options = state.homeSourceOptions();
          const modes = options.map((option) => option.mode);
          const expectedModes = ['local', 'batch', 'network', 'subtitle', 'audio'];
          if (JSON.stringify(modes) !== JSON.stringify(expectedModes)) {
            throw new Error(`expected broad source modes, got ${JSON.stringify(modes)}`);
          }
          const batchOption = options.find((option) => option.mode === 'batch');
          if (!batchOption?.strategy.includes('批量创建项目') || !batchOption?.strategy.includes('默认仅翻译')) {
            throw new Error(`expected batch mode to explain automatic batch translation, got ${JSON.stringify(batchOption)}`);
          }
          const batchCapabilities = state.homeSourceCapabilities(batchOption);
          if (!batchCapabilities.some((item) => item.includes('递归扫描')) || !batchCapabilities.some((item) => item.includes('自动创建'))) {
            throw new Error(`expected batch capabilities to mention folder scanning and automatic start, got ${JSON.stringify(batchCapabilities)}`);
          }
          if (!options.find((option) => option.mode === 'network')?.strategy.includes('原生字幕')) {
            throw new Error(`expected network mode to explain native subtitle priority, got ${JSON.stringify(options)}`);
          }
          const networkCapabilities = state.homeSourceCapabilities({mode: 'network'});
          if (!networkCapabilities.some((item) => item.includes('YouTube')) || !networkCapabilities.some((item) => item.includes('平台字幕'))) {
            throw new Error(`expected network capabilities to mention URL sources and platform subtitles, got ${JSON.stringify(networkCapabilities)}`);
          }
          const subtitleOption = options.find((option) => option.mode === 'subtitle');
          if (subtitleOption?.disabled) {
            throw new Error('expected subtitle-only mode to be enabled for SRT import');
          }
          if (!subtitleOption?.strategy.includes('SRT') || !subtitleOption?.strategy.includes('VTT') || !subtitleOption?.strategy.includes('ASS')) {
            throw new Error(`expected subtitle source to explain SRT/VTT/ASS import, got ${JSON.stringify(subtitleOption)}`);
          }
          const subtitleCapabilities = state.homeSourceCapabilities(subtitleOption);
          if (!subtitleCapabilities.some((item) => item.includes('无需 ASR')) || !subtitleCapabilities.some((item) => item.includes('保留时间轴'))) {
            throw new Error(`expected subtitle capabilities to explain direct translation, got ${JSON.stringify(subtitleCapabilities)}`);
          }
          if (!state.homeSourceStrategy().includes('内嵌字幕')) {
            throw new Error(`expected local strategy to mention embedded subtitles, got ${state.homeSourceStrategy()}`);
          }
          const localCapabilities = state.homeSourceCapabilities();
          if (!localCapabilities.some((item) => item.includes('内嵌字幕')) || !localCapabilities.some((item) => item.includes('烧录'))) {
            throw new Error(`expected local capabilities to mention embedded subtitles and burn-in output, got ${JSON.stringify(localCapabilities)}`);
          }
          const audioOption = options.find((option) => option.mode === 'audio');
          if (audioOption?.disabled) {
            throw new Error('expected audio mode to be enabled for ASR import');
          }
          if (!audioOption?.strategy.includes('ASR') && !audioOption?.strategy.includes('听写')) {
            throw new Error(`expected audio source to explain transcription, got ${JSON.stringify(audioOption)}`);
          }
          const audioCapabilities = state.homeSourceCapabilities(audioOption);
          if (!audioCapabilities.some((item) => item.includes('ASR')) || !audioCapabilities.some((item) => item.includes('SRT / VTT'))) {
            throw new Error(`expected audio capabilities to mention ASR and subtitle export, got ${JSON.stringify(audioCapabilities)}`);
          }

          let picked = false;
          state.openFilePicker = async () => { picked = true; };
          await state.startHomeSourceAction();
          if (!picked) throw new Error('expected local source action to open file picker');

          let folderPicked = false;
          state.openFolderPicker = async () => { folderPicked = true; };
          state.setHomeSourceMode('batch');
          await state.startHomeSourceAction();
          if (!folderPicked) throw new Error('expected batch source action to open folder picker');

          state.setHomeSourceMode('network');
          state.trailerUrlInput = 'https://youtu.be/demo';
          let trailerStarted = false;
          state.startTrailerUrlJob = async () => { trailerStarted = true; };
          await state.startHomeSourceAction();
          if (!trailerStarted) throw new Error('expected network source action to start URL job');

          if (
            !state.isSubtitleFile({name: 'lecture.srt'})
            || !state.isSubtitleFile({name: 'lecture.vtt'})
            || !state.isSubtitleFile({name: 'lecture.ass'})
            || !state.isSubtitleFile({name: 'lecture.ssa'})
          ) {
            throw new Error('expected SRT, VTT, ASS, and SSA files to be accepted');
          }
          if (state.isSubtitleFile({name: 'lecture.sub'})) {
            throw new Error('expected unsupported subtitle containers to be rejected');
          }

          let subtitlePickerOpened = false;
          state.openSubtitleFilePicker = async () => { subtitlePickerOpened = true; };
          state.setHomeSourceMode('subtitle');
          await state.startHomeSourceAction();
          if (!subtitlePickerOpened) throw new Error('expected subtitle source action to open subtitle picker');

          let audioPickerOpened = false;
          state.openAudioFilePicker = async () => { audioPickerOpened = true; };
          state.setHomeSourceMode('audio');
          await state.startHomeSourceAction();
          if (!audioPickerOpened) throw new Error('expected audio source action to open audio picker');
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_home_source_readiness_points_to_settings_for_missing_translation_or_asr():
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
          const pendingReadiness = state.homeSourceReadiness({mode: 'local'});
          if (pendingReadiness.message) {
            throw new Error(`expected no readiness warning before system check, got ${JSON.stringify(pendingReadiness)}`);
          }

          state.sysCheck = {
            translation_ready: false,
            translation_hint: '请配置 OpenAI API Key',
            asr_install_prompts: [
              {
                id: 'asr-backend-local-missing',
                title: '未检测到本地 ASR 后端',
                message: '请安装 faster-whisper 或 mlx-whisper。',
              },
            ],
            asr_recommendation: {ready: false, download_required: true, download_hint: '~1.6GB'},
          };

          const translationReadiness = state.homeSourceReadiness({mode: 'subtitle'});
          if (!translationReadiness.message.includes('翻译引擎') || !translationReadiness.message.includes('OpenAI')) {
            throw new Error(`expected translation readiness warning, got ${JSON.stringify(translationReadiness)}`);
          }
          if (translationReadiness.actionText !== '去设置') {
            throw new Error(`expected settings action, got ${JSON.stringify(translationReadiness)}`);
          }

          const views = [];
          state.setView = async (view) => { views.push(view); state.view = view; return true; };
          await state.handleHomeSourceReadinessAction(translationReadiness);
          if (views[0] !== 'settings') {
            throw new Error(`expected readiness action to open settings, got ${JSON.stringify(views)}`);
          }

          state.sysCheck.translation_ready = true;
          const audioReadiness = state.homeSourceReadiness({mode: 'audio'});
          if (!audioReadiness.message.includes('音频入口需要 ASR') || !audioReadiness.message.includes('请安装 faster-whisper')) {
            throw new Error(`expected audio ASR warning, got ${JSON.stringify(audioReadiness)}`);
          }
          if (audioReadiness.tone !== 'warn') {
            throw new Error(`expected warn tone for missing ASR, got ${JSON.stringify(audioReadiness)}`);
          }

          const networkReadiness = state.homeSourceReadiness({mode: 'network'});
          if (!networkReadiness.message.includes('无平台字幕时需要 ASR')) {
            throw new Error(`expected network ASR fallback warning, got ${JSON.stringify(networkReadiness)}`);
          }

          const subtitleReadiness = state.homeSourceReadiness({mode: 'subtitle'});
          if (subtitleReadiness.message) {
            throw new Error(`subtitle-only source should not warn about ASR, got ${JSON.stringify(subtitleReadiness)}`);
          }

          state.sysCheck.asr_install_prompts = [];
          state.sysCheck.asr_recommendation = {
            ready: false,
            download_required: true,
            download_hint: '~1.6GB',
            model_size: 'large-v3-turbo',
          };
          const modelReadiness = state.homeSourceReadiness({mode: 'audio'});
          if (!modelReadiness.message.includes('ASR 模型未下载') || !modelReadiness.message.includes('large-v3-turbo') || !modelReadiness.message.includes('~1.6GB')) {
            throw new Error(`expected source warning for missing ASR model download, got ${JSON.stringify(modelReadiness)}`);
          }

          state.sysCheck = {
            translation_ready: true,
            network_downloader_ready: false,
            network_downloader_hint: '请安装 yt-dlp 以启用网络视频下载。',
            asr_install_prompts: [],
            asr_recommendation: {ready: true, download_required: false},
          };
          const downloaderReadiness = state.homeSourceReadiness({mode: 'network'});
          if (!downloaderReadiness.message.includes('网络视频下载器') || !downloaderReadiness.message.includes('yt-dlp')) {
            throw new Error(`expected network downloader warning, got ${JSON.stringify(downloaderReadiness)}`);
          }
          if (downloaderReadiness.actionText !== '去设置') {
            throw new Error(`expected network downloader settings action, got ${JSON.stringify(downloaderReadiness)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_selected_subtitle_file_creates_project_and_starts_translation():
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
          state.sysCheck = {translation_ready: true};
          state.targetLang = 'English';
          state.toast = () => {};
          state.setView = async (view) => { state.view = view; return true; };
          state.connectWS = () => {};
          state.uploadSubtitleFile = async (file) => {
            calls.push(['upload', file.name]);
            return {id: 'sub1', name: file.name, source_type: 'subtitle', target_language: 'English'};
          };
          state.api = async (url, method, body) => {
            calls.push([method, url, body]);
            if (url === '/api/projects/sub1/start-translate' && method === 'POST') {
              return {status: 'started'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          await state.useSelectedSubtitleFile({name: 'lecture.srt'});

          if (JSON.stringify(calls[0]) !== JSON.stringify(['upload', 'lecture.srt'])) {
            throw new Error(`expected subtitle upload first, got ${JSON.stringify(calls)}`);
          }
          const startCall = calls.find((call) => call[1] === '/api/projects/sub1/start-translate');
          if (!startCall || startCall[2].target_language !== 'English') {
            throw new Error(`expected start-translate with target language, got ${JSON.stringify(calls)}`);
          }
          if (state.currentProject?.id !== 'sub1') {
            throw new Error(`expected current subtitle project, got ${JSON.stringify(state.currentProject)}`);
          }
          if (state.view !== 'detail') {
            throw new Error(`expected subtitle project detail view, got ${state.view}`);
          }
          if (state.fileImporting || state.projectCreating) {
            throw new Error(`expected busy flags reset, got ${state.fileImporting}/${state.projectCreating}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_selected_vtt_file_creates_project_and_starts_translation():
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
          state.sysCheck = {translation_ready: true};
          state.targetLang = '简体中文';
          state.toast = () => {};
          state.setView = async (view) => { state.view = view; return true; };
          state.connectWS = () => {};
          state.uploadSubtitleFile = async (file) => {
            calls.push(['upload', file.name]);
            return {id: 'subvtt1', name: file.name, source_type: 'subtitle'};
          };
          state.api = async (url, method, body) => {
            calls.push([method, url, body]);
            if (url === '/api/projects/subvtt1/start-translate' && method === 'POST') {
              return {status: 'started'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          await state.useSelectedSubtitleFile({name: 'lecture.zh-Hans.vtt'});

          if (JSON.stringify(calls[0]) !== JSON.stringify(['upload', 'lecture.zh-Hans.vtt'])) {
            throw new Error(`expected VTT upload first, got ${JSON.stringify(calls)}`);
          }
          const startCall = calls.find((call) => call[1] === '/api/projects/subvtt1/start-translate');
          if (!startCall || startCall[2].target_language !== '简体中文') {
            throw new Error(`expected start-translate with target language, got ${JSON.stringify(calls)}`);
          }
          if (state.currentProject?.id !== 'subvtt1' || state.view !== 'detail') {
            throw new Error(`expected VTT project detail, got ${JSON.stringify(state.currentProject)}/${state.view}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_selected_ass_file_creates_project_and_starts_translation():
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
          state.sysCheck = {translation_ready: true};
          state.targetLang = '简体中文';
          state.toast = () => {};
          state.setView = async (view) => { state.view = view; return true; };
          state.connectWS = () => {};
          state.uploadSubtitleFile = async (file) => {
            calls.push(['upload', file.name]);
            return {id: 'subass1', name: file.name, source_type: 'subtitle'};
          };
          state.api = async (url, method, body) => {
            calls.push([method, url, body]);
            if (url === '/api/projects/subass1/start-translate' && method === 'POST') {
              return {status: 'started'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          await state.useSelectedSubtitleFile({name: 'anime.episode.ass'});

          if (JSON.stringify(calls[0]) !== JSON.stringify(['upload', 'anime.episode.ass'])) {
            throw new Error(`expected ASS upload first, got ${JSON.stringify(calls)}`);
          }
          const startCall = calls.find((call) => call[1] === '/api/projects/subass1/start-translate');
          if (!startCall || startCall[2].target_language !== '简体中文') {
            throw new Error(`expected start-translate with target language, got ${JSON.stringify(calls)}`);
          }
          if (state.currentProject?.id !== 'subass1' || state.view !== 'detail') {
            throw new Error(`expected ASS project detail, got ${JSON.stringify(state.currentProject)}/${state.view}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )


def test_selected_audio_file_creates_project_and_starts_transcribe_translate():
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
          state.sysCheck = {translation_ready: true};
          state.targetLang = 'English';
          state.asrLanguage = 'en';
          state.toast = () => {};
          state.setView = async (view) => { state.view = view; return true; };
          state.connectWS = () => {};
          state.uploadAudioFile = async (file) => {
            calls.push(['upload', file.name]);
            return {id: 'aud1', name: file.name, source_type: 'audio', target_language: 'English'};
          };
          state.api = async (url, method, body) => {
            calls.push([method, url, body]);
            if (url === '/api/projects/aud1/start-transcribe-translate' && method === 'POST') {
              return {status: 'started'};
            }
            throw new Error(`unexpected api call ${method} ${url}`);
          };

          await state.useSelectedAudioFile({name: 'lecture.mp3'});

          if (JSON.stringify(calls[0]) !== JSON.stringify(['upload', 'lecture.mp3'])) {
            throw new Error(`expected audio upload first, got ${JSON.stringify(calls)}`);
          }
          const startCall = calls.find((call) => call[1] === '/api/projects/aud1/start-transcribe-translate');
          if (!startCall || startCall[2].language !== 'en' || startCall[2].target_language !== 'English') {
            throw new Error(`expected start-transcribe-translate with ASR and target language, got ${JSON.stringify(calls)}`);
          }
          if (state.currentProject?.id !== 'aud1') {
            throw new Error(`expected current audio project, got ${JSON.stringify(state.currentProject)}`);
          }
          if (state.view !== 'detail') {
            throw new Error(`expected audio project detail view, got ${state.view}`);
          }
          if (state.fileImporting || state.projectCreating) {
            throw new Error(`expected busy flags reset, got ${state.fileImporting}/${state.projectCreating}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )
