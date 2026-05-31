import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trailer_video_loader_surfaces_http_errors():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => ({
            ok: false,
            status: 400,
            json: async () => ({detail: 'TMDB API key missing'}),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSelectedShow = {id: 1399, media_type: 'movie'};
          await state.fetchTrailerVideos();
          if (!state.trailerError || !state.trailerError.includes('TMDB API key missing')) {
            throw new Error(`expected visible TMDB error, got ${state.trailerError}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_search_formats_validation_detail_errors():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => ({
            ok: false,
            status: 422,
            statusText: 'Unprocessable Entity',
            json: async () => ({
              detail: [
                {loc: ['body', 'query'], msg: 'Field required'},
              ],
            }),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSearchQuery = 'Show';
          await state.searchTrailers();
          if (!state.trailerError || !state.trailerError.includes('query: Field required')) {
            throw new Error(`expected formatted validation error, got ${state.trailerError}`);
          }
          if (String(state.trailerError).includes('[object Object]')) {
            throw new Error(`expected no object-string error, got ${state.trailerError}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_start_formats_validation_detail_errors():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => ({
            ok: false,
            status: 422,
            statusText: 'Unprocessable Entity',
            json: async () => ({
              detail: [
                {loc: ['body', 'video_keys', 0], msg: 'Input should be a valid string'},
              ],
            }),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.sysCheck = {translation_ready: true};
          state.trailerSelectedShow = {id: 1399, media_type: 'movie', name: 'Foo'};
          state.trailerSelectedVideos = ['abc123'];
          await state.startTrailerJobs();
          if (!state.trailerError || !state.trailerError.includes('video_keys.0: Input should be a valid string')) {
            throw new Error(`expected formatted validation error, got ${state.trailerError}`);
          }
          if (state.trailerStep !== 1) throw new Error(`expected to stay on current step, got ${state.trailerStep}`);
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_start_blocks_when_translation_is_not_ready():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => {
            throw new Error('trailer API should not be called');
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let settingsOpened = false;
          let toastMessage = '';
          state.sysCheck = {translation_ready: false, translation_hint: '请配置 OpenAI API 密钥'};
          state.refreshSystemCheck = async () => {};
          state.toast = (msg, type) => { toastMessage = `${type || 'success'}:${msg}`; };
          state.setView = async (view) => {
            if (view === 'settings') settingsOpened = true;
            state.view = view;
            return true;
          };
          state.trailerSelectedShow = {id: 1399, media_type: 'movie', name: 'Foo'};
          state.trailerSelectedVideos = ['abc123'];

          await state.startTrailerJobs();

          if (!settingsOpened) throw new Error('expected settings view to open');
          if (!toastMessage.includes('OpenAI')) throw new Error(`expected translation toast, got ${toastMessage}`);
          if (!state.trailerError || !state.trailerError.includes('OpenAI')) {
            throw new Error(`expected trailer error to mention provider, got ${state.trailerError}`);
          }
          if (state.trailerSubmitting) throw new Error('expected submitting state to clear');
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_error_settings_shortcut_covers_translation_and_tmdb_errors():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const html = fs.readFileSync('app/static/index.html', 'utf8');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        if (!html.includes('x-show="trailerErrorNeedsSettings()"')) {
          throw new Error('expected trailer error settings shortcut to use helper');
        }

        state.trailerError = 'TMDB API key missing';
        if (!state.trailerErrorNeedsSettings()) {
          throw new Error('expected TMDB errors to link to settings');
        }

        state.trailerError = '请先完成翻译引擎配置：润色引擎：请配置 DeepSeek API 密钥';
        if (!state.trailerErrorNeedsSettings()) {
          throw new Error('expected translation readiness errors to link to settings');
        }

        state.trailerError = 'Claude CLI 未登录';
        if (!state.trailerErrorNeedsSettings()) {
          throw new Error('expected Claude CLI errors to link to settings');
        }

        state.trailerError = '网络错误: timeout';
        if (state.trailerErrorNeedsSettings()) {
          throw new Error('expected generic network errors not to force settings shortcut');
        }
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_select_show_clamps_season_count():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.selectShow({
          media_type: 'tv',
          id: 1,
          name: 'Long Show',
          number_of_seasons: 1000000,
          seasons: [],
        });
        if (state.trailerSeasons.length !== 100) {
          throw new Error(`expected 100 seasons max, got ${state.trailerSeasons.length}`);
        }
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_previous_step_skips_season_picker_for_movies_and_terminal_success():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.trailerSelectedShow = {id: 42, media_type: 'movie', title: 'Movie'};
        state.trailerStep = 4;
        state.trailerError = 'old error';
        state.previousTrailerStep();
        if (state.trailerStep !== 2) {
          throw new Error(`movie step 4 should return to candidates, got ${state.trailerStep}`);
        }
        if (state.trailerError !== null) {
          throw new Error(`previousTrailerStep should clear stale errors, got ${state.trailerError}`);
        }

        state.trailerSelectedShow = {id: 1399, media_type: 'tv', name: 'Show'};
        state.trailerStep = 4;
        state.previousTrailerStep();
        if (state.trailerStep !== 3) {
          throw new Error(`tv step 4 should return to seasons, got ${state.trailerStep}`);
        }

        state.trailerStep = 5;
        state.previousTrailerStep();
        if (state.trailerStep !== 5) {
          throw new Error(`success step should be terminal, got ${state.trailerStep}`);
        }
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_open_trailer_wizard_starts_clean_flow():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.setView = async (view) => {
            state.view = view;
            return true;
          };
          state.trailerStep = 4;
          state.trailerSearchQuery = 'old query';
          state.trailerSearchResults = [{id: 1}];
          state.trailerSelectedShow = {id: 1, media_type: 'movie'};
          state.trailerVideos = [{key: 'old'}];
          state.trailerSelectedVideos = ['old'];
          state.trailerSelectedSeasons = [1];
          state.trailerError = 'old error';
          state.trailerSubmitting = true;

          await state.openTrailerWizard();

          if (state.view !== 'trailer' || state.trailerStep !== 1) {
            throw new Error(`expected clean trailer step 1, got ${JSON.stringify({view: state.view, step: state.trailerStep})}`);
          }
          if (state.trailerSearchQuery || state.trailerSearchResults.length || state.trailerSelectedShow || state.trailerVideos.length || state.trailerSelectedVideos.length || state.trailerSelectedSeasons.length || state.trailerError || state.trailerSubmitting) {
            throw new Error(`expected trailer state reset, got ${JSON.stringify({
              query: state.trailerSearchQuery,
              results: state.trailerSearchResults,
              selected: state.trailerSelectedShow,
              videos: state.trailerVideos,
              selectedVideos: state.trailerSelectedVideos,
              seasons: state.trailerSelectedSeasons,
              error: state.trailerError,
              submitting: state.trailerSubmitting,
            })}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_video_loader_filters_malformed_video_entries():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => ({
            ok: true,
            json: async () => ({videos: [null, {key: ''}, {key: 123}, {key: 'abc'}]}),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSelectedShow = {id: 1399, media_type: 'movie'};
          await state.fetchTrailerVideos();
          if (JSON.stringify(state.trailerVideos.map((v) => v.key)) !== JSON.stringify(['abc'])) {
            throw new Error(`expected only valid video key, got ${JSON.stringify(state.trailerVideos)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_video_loader_sanitizes_selected_tv_seasons_before_fetch():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const calls = [];
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async (url) => {
            calls.push(url);
            return {ok: true, json: async () => ({videos: [{key: String(calls.length)}]})};
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSelectedShow = {id: 1399, media_type: 'tv'};
          state.trailerSeasons = [1, 2, 3];
          state.trailerSelectedSeasons = [2, '2', true, 99, 'bad', 1, 0];
          await state.fetchTrailerVideos();

          const expectedCalls = [
            '/api/trailer/videos/1399?type=tv&season=2',
            '/api/trailer/videos/1399?type=tv&season=1',
          ];
          if (JSON.stringify(calls) !== JSON.stringify(expectedCalls)) {
            throw new Error(`expected sanitized season URLs, got ${JSON.stringify(calls)}`);
          }
          if (JSON.stringify(state.trailerSelectedSeasons) !== JSON.stringify([2, 1])) {
            throw new Error(`expected selected seasons to be normalized, got ${JSON.stringify(state.trailerSelectedSeasons)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_video_loader_clears_loading_after_season_change_mid_request():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        let releaseFetch;
        const gate = new Promise((resolve) => { releaseFetch = resolve; });
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => {
            await gate;
            return {ok: true, json: async () => ({videos: [{key: 'stale'}]})};
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSelectedShow = {id: 1399, media_type: 'tv'};
          state.trailerSeasons = [1, 2];
          state.trailerSelectedSeasons = [1];

          const pending = state.fetchTrailerVideos();
          if (!state.trailerLoading) {
            throw new Error('expected trailer loading to start');
          }

          state.trailerSelectedSeasons = [2];
          releaseFetch();
          await pending;

          if (state.trailerLoading) {
            throw new Error('expected stale request to clear loading after season change');
          }
          if (state.trailerVideos.length !== 0) {
            throw new Error(`expected stale videos to be ignored, got ${JSON.stringify(state.trailerVideos)}`);
          }
          if (state.trailerError) {
            throw new Error(`expected no stale error, got ${state.trailerError}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_video_step_blocks_while_loading():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        let fetches = 0;
        state.trailerStep = 3;
        state.trailerSelectedShow = {id: 1399, media_type: 'tv'};
        state.fetchTrailerVideos = () => { fetches += 1; };

        state.trailerLoading = true;
        state.advanceTrailerVideoStep();
        if (state.trailerStep !== 3 || fetches !== 0) {
          throw new Error(`expected loading state to block next step, got ${JSON.stringify({step: state.trailerStep, fetches})}`);
        }

        state.trailerLoading = false;
        state.advanceTrailerVideoStep();
        if (state.trailerStep !== 4 || fetches !== 1) {
          throw new Error(`expected next step to fetch once, got ${JSON.stringify({step: state.trailerStep, fetches})}`);
        }
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_search_ignores_malformed_results_shape():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => ({
            ok: true,
            json: async () => ({results: {bad: 'shape'}}),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSearchQuery = 'Foo';
          await state.searchTrailers();
          if (state.trailerError) throw new Error(`expected no error, got ${state.trailerError}`);
          if (state.trailerSearchResults.length !== 0) {
            throw new Error(`expected empty results, got ${JSON.stringify(state.trailerSearchResults)}`);
          }
          if (state.trailerStep !== 2) throw new Error(`expected step 2, got ${state.trailerStep}`);
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_search_normalizes_result_fields_before_rendering():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => ({
            ok: true,
            json: async () => ({
              results: [
                null,
                {id: 0, media_type: 'movie', title: 'bad'},
                {id: 123, media_type: 'person', name: 'bad'},
                {
                  id: '42',
                  media_type: 'tv',
                  name: 'Show',
                  original_language: {bad: 'shape'},
                  overview: ['bad'],
                  poster_path: 123,
                  number_of_seasons: '2',
                  seasons: {bad: 'shape'},
                },
              ],
            }),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSearchQuery = 'Show';
          await state.searchTrailers();
          if (state.trailerSearchResults.length !== 1) {
            throw new Error(`expected one normalized result, got ${JSON.stringify(state.trailerSearchResults)}`);
          }
          const item = state.trailerSearchResults[0];
          if (item.id !== 42 || item.original_language !== '' || item.overview !== '' || item.poster_path !== null) {
            throw new Error(`unexpected normalized item: ${JSON.stringify(item)}`);
          }
          if (item.number_of_seasons !== 2 || !Array.isArray(item.seasons)) {
            throw new Error(`season fields not normalized: ${JSON.stringify(item)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_search_ignores_stale_slow_response_when_query_changes():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let releaseSlow;
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async (_url, options = {}) => {
            const body = JSON.parse(options.body || '{}');
            if (body.query === 'slow') {
              await new Promise((resolve) => { releaseSlow = resolve; });
              return {
                ok: true,
                json: async () => ({results: [{id: 1, media_type: 'movie', title: 'Slow'}]}),
              };
            }
            if (body.query === 'fast') {
              return {
                ok: true,
                json: async () => ({results: [{id: 2, media_type: 'movie', title: 'Fast'}]}),
              };
            }
            throw new Error(`unexpected search body ${JSON.stringify(body)}`);
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSearchQuery = 'slow';
          const slow = state.searchTrailers();
          await Promise.resolve();

          state.trailerSearchQuery = 'fast';
          const fast = state.searchTrailers();
          await fast;

          if (state.trailerSearchResults[0]?.title !== 'Fast') {
            throw new Error(`expected fast result before slow resolves, got ${JSON.stringify(state.trailerSearchResults)}`);
          }

          releaseSlow();
          await slow;

          if (state.trailerSearchResults[0]?.title !== 'Fast' || state.trailerLoading) {
            throw new Error(`stale slow search overwrote current results: ${JSON.stringify({results: state.trailerSearchResults, loading: state.trailerLoading})}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_search_ignores_response_when_query_changes_without_resubmit():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        let releaseSearch;
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async (_url, options = {}) => {
            const body = JSON.parse(options.body || '{}');
            if (body.query !== 'old query') {
              throw new Error(`unexpected search body ${JSON.stringify(body)}`);
            }
            await new Promise((resolve) => { releaseSearch = resolve; });
            return {
              ok: true,
              json: async () => ({results: [{id: 1, media_type: 'movie', title: 'Old Result'}]}),
            };
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSearchMode = 'title';
          state.trailerSearchQuery = 'old query';
          const pending = state.searchTrailers();
          await Promise.resolve();
          if (!state.trailerLoading) {
            throw new Error('expected trailer search loading to start');
          }

          state.trailerSearchQuery = 'new query';
          releaseSearch();
          await pending;

          if (state.trailerLoading) {
            throw new Error('expected stale query response to clear loading');
          }
          if (state.trailerSearchResults.length !== 0) {
            throw new Error(`expected stale search results to be ignored, got ${JSON.stringify(state.trailerSearchResults)}`);
          }
          if (state.trailerStep !== 1) {
            throw new Error(`expected to stay on search step, got ${state.trailerStep}`);
          }
          if (state.trailerError) {
            throw new Error(`expected no stale search error, got ${state.trailerError}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_select_show_rejects_invalid_result():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.selectShow({id: 0, media_type: 'movie', title: 'Bad'});
        if (!state.trailerError || !state.trailerError.includes('无效')) {
          throw new Error(`expected invalid item error, got ${state.trailerError}`);
        }
        if (state.trailerSelectedShow !== null) {
          throw new Error(`expected no selected show, got ${JSON.stringify(state.trailerSelectedShow)}`);
        }
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_video_loader_ignores_stale_slow_response_when_show_changes():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let releaseSlow;
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async (url) => {
            if (url.includes('/api/trailer/videos/1?')) {
              await new Promise((resolve) => { releaseSlow = resolve; });
              return {ok: true, json: async () => ({videos: [{key: 'slow-video'}]})};
            }
            if (url.includes('/api/trailer/videos/2?')) {
              return {ok: true, json: async () => ({videos: [{key: 'fast-video'}]})};
            }
            throw new Error(`unexpected video URL ${url}`);
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSelectedShow = {id: 1, media_type: 'movie'};
          state.trailerSelectedVideos = ['old-selection'];
          const slow = state.fetchTrailerVideos();
          await Promise.resolve();

          state.trailerSelectedShow = {id: 2, media_type: 'movie'};
          const fast = state.fetchTrailerVideos();
          await fast;

          if (JSON.stringify(state.trailerVideos.map((v) => v.key)) !== JSON.stringify(['fast-video'])) {
            throw new Error(`expected fast videos before slow resolves, got ${JSON.stringify(state.trailerVideos)}`);
          }
          if (state.trailerSelectedVideos.length !== 0) {
            throw new Error(`expected fresh video load to clear selection, got ${JSON.stringify(state.trailerSelectedVideos)}`);
          }

          releaseSlow();
          await slow;

          if (JSON.stringify(state.trailerVideos.map((v) => v.key)) !== JSON.stringify(['fast-video']) || state.trailerLoading) {
            throw new Error(`stale slow videos overwrote current list: ${JSON.stringify({videos: state.trailerVideos, loading: state.trailerLoading})}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_video_loader_ignores_malformed_videos_shape():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => ({
            ok: true,
            json: async () => ({videos: {bad: 'shape'}}),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.trailerSelectedShow = {id: 1399, media_type: 'movie'};
          await state.fetchTrailerVideos();
          if (state.trailerError) throw new Error(`expected no error, got ${state.trailerError}`);
          if (state.trailerVideos.length !== 0) {
            throw new Error(`expected empty videos, got ${JSON.stringify(state.trailerVideos)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_start_blocks_duplicate_submits_while_pending():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let releaseStart;
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => {
            await new Promise((resolve) => { releaseStart = resolve; });
            return {ok: true, json: async () => ({pids: ['p1']})};
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          let calls = 0;
          const originalFetch = context.fetch;
          context.fetch = async (...args) => {
            calls += 1;
            return originalFetch(...args);
          };
          state.trailerSelectedShow = {id: 1399, media_type: 'movie', name: 'Foo'};
          state.trailerSelectedVideos = ['abc123'];
          state.sysCheck = {translation_ready: true};

          const first = state.startTrailerJobs();
          await Promise.resolve();
          if (!state.trailerSubmitting) throw new Error('expected submitting state after first trailer start');

          const second = state.startTrailerJobs();
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate trailer submit to be ignored, got ${calls} calls`);
          }

          releaseStart();
          await first;
          await second;
          if (state.trailerSubmitting) throw new Error('expected submitting state to clear');
          if (state.trailerCreatedCount !== 1) {
            throw new Error(`expected one created trailer, got ${state.trailerCreatedCount}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_start_includes_selected_target_language_in_payload():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        let payload = null;
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async (_url, options) => {
            payload = JSON.parse(options.body);
            return {ok: true, json: async () => ({pids: ['p1']})};
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.targetLang = 'English';
          state.sysCheck = {translation_ready: true};
          state.trailerSelectedShow = {id: 1399, media_type: 'movie', name: 'Foo', original_language: 'ja'};
          state.trailerSelectedVideos = ['abc123'];
          await state.startTrailerJobs();

          if (!payload || payload.target_language !== 'English') {
            throw new Error(`expected selected target language in payload, got ${JSON.stringify(payload)}`);
          }
          if (payload.original_language !== 'ja') {
            throw new Error(`expected original language to be preserved, got ${JSON.stringify(payload)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_frontend_model_loader_filters_malformed_model_entries():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.settings.api_keys.openai = 'sk-test';
          state.api = async () => ({models: [' gpt-4o ', 123, '', null, 'gpt-4o-mini']});
          await state.fetchModels('openai', 'primary');
          const expected = ['gpt-4o', 'gpt-4o-mini'];
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(expected)) {
            throw new Error(`expected sanitized models, got ${JSON.stringify(state.primaryModels)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_trailer_start_counts_only_array_pids():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async () => ({
            ok: true,
            json: async () => ({pids: 'not-an-array'}),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.sysCheck = {translation_ready: true};
          state.trailerSelectedShow = {id: 1399, media_type: 'movie', name: 'Foo'};
          state.trailerSelectedVideos = ['abc123'];
          await state.startTrailerJobs();
          if (state.trailerCreatedCount !== 0) {
            throw new Error(`expected zero created count, got ${state.trailerCreatedCount}`);
          }
          if (state.trailerStep !== 5) throw new Error(`expected step 5, got ${state.trailerStep}`);
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_frontend_toast_ids_are_monotonic():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.toast('one');
        state.toast('two');
        const ids = state.toasts.map(t => t.id);
        if (ids.length !== 2 || ids[0] === ids[1] || ids[0] >= ids[1]) {
          throw new Error(`toast ids are not monotonic: ${JSON.stringify(ids)}`);
        }
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_frontend_kb_editor_normalizes_malformed_categories():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async (url, options) => {
            if (options?.method === 'PUT') {
              const payload = JSON.parse(options.body);
              if (!Array.isArray(payload.characters) || payload.characters.length !== 1) {
                throw new Error(`expected normalized characters, got ${JSON.stringify(payload.characters)}`);
              }
              if (!Array.isArray(payload.places) || payload.places.length !== 0) {
                throw new Error(`expected empty places, got ${JSON.stringify(payload.places)}`);
              }
              return {ok: true, json: async () => ({})};
            }
            return {
              ok: true,
              json: async () => ({
                key: 'show',
                show_title: 123,
                tmdb_id: {bad: 'shape'},
                characters: {bad: 'shape'},
                places: null,
                brands: [{source: 1, target: 'Brand', notes: null}, 'bad'],
                slang: 'bad',
                style_notes: {rules: ['keep', 7], tone: 42},
              }),
            };
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.toast = () => {};
          state.kbSelectedKey = 'show';
          await state.selectKb('show');
          state.addKbEntry('characters');
          state.kbCurrent.characters[0].source = 'Alice';
          state.kbCurrent.characters[0].target = '艾丽丝';
          state.addKbEntry('not-a-real-category');
          await state.saveKb();
          if (state.kbDirty) throw new Error('expected save to clear dirty flag');
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
