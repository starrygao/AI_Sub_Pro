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


def test_load_settings_applies_workflow_language_defaults_to_project_actions():
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
          state.fetchModels = () => {};
          state.api = async (url) => {
            if (url !== '/api/settings') throw new Error(`unexpected settings URL ${url}`);
            return {
              api_keys: {},
              tmdb: {},
              trailer: {},
              asr: { language: 'ja' },
              translation: {
                primary_provider: 'claude_cli',
                polish_provider: '',
                target_language: 'Japanese',
              },
              providers: { claude_cli: { enabled: true, model: 'claude-sonnet-4-6' } },
            };
          };

          await state.loadSettings();

          if (state.asrLanguage !== 'ja') {
            throw new Error(`expected ASR selector to follow settings, got ${state.asrLanguage}`);
          }
          if (state.targetLang !== 'Japanese') {
            throw new Error(`expected target selector to follow settings, got ${state.targetLang}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_display_language_defaults_to_system_language():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          navigator: { language: 'en-US', languages: ['en-US', 'zh-CN'] },
          document: { documentElement: { lang: '' } },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.settings.general = { display_language: 'auto' };
        state.applyDisplayLanguageFromSettings();

        if (state.uiLanguage !== 'en-US') {
          throw new Error(`expected system English, got ${state.uiLanguage}`);
        }
        if (context.document.documentElement.lang !== 'en-US') {
          throw new Error(`expected document lang to update, got ${context.document.documentElement.lang}`);
        }
        if (state.t('nav.settings') !== 'Settings') {
          throw new Error(`expected English settings label, got ${state.t('nav.settings')}`);
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_display_language_can_be_set_to_chinese():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          navigator: { language: 'en-US', languages: ['en-US'] },
          document: { documentElement: { lang: '' } },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.settings.general = { display_language: 'zh-CN' };
        state.applyDisplayLanguageFromSettings();

        if (state.uiLanguage !== 'zh-CN') {
          throw new Error(`expected manual Chinese, got ${state.uiLanguage}`);
        }
        if (state.t('nav.settings') !== '设置') {
          throw new Error(`expected Chinese settings label, got ${state.t('nav.settings')}`);
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_settings_exposes_display_language_control():
    html = (ROOT / "app/static/index.html").read_text()

    assert 'x-model="settings.general.display_language"' in html
    assert '@change="applyDisplayLanguageFromSettings()"' in html
    assert 'value="auto"' in html
    assert 'value="zh-CN"' in html
    assert 'value="en-US"' in html


def test_frontend_api_key_panel_only_lists_selected_key_providers():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        const setProviders = (primary, polish) => {
          state.settings.translation = {
            primary_provider: primary,
            polish_provider: polish,
          };
        };

        setProviders('openai', '');
        if (JSON.stringify(state.settingsApiKeyProviders()) !== JSON.stringify(['openai'])) {
          throw new Error(`expected only OpenAI key row, got ${JSON.stringify(state.settingsApiKeyProviders())}`);
        }
        if (!state.settingsNeedsApiKeyPanel()) {
          throw new Error('expected API key panel for OpenAI');
        }

        setProviders('openai', 'deepseek');
        if (JSON.stringify(state.settingsApiKeyProviders()) !== JSON.stringify(['openai', 'deepseek'])) {
          throw new Error(`expected primary + polish key rows, got ${JSON.stringify(state.settingsApiKeyProviders())}`);
        }

        setProviders('gemini', 'gemini');
        if (JSON.stringify(state.settingsApiKeyProviders()) !== JSON.stringify(['gemini'])) {
          throw new Error(`expected duplicate provider to show once, got ${JSON.stringify(state.settingsApiKeyProviders())}`);
        }

        setProviders('claude_cli', 'deepseek');
        if (JSON.stringify(state.settingsApiKeyProviders()) !== JSON.stringify(['deepseek'])) {
          throw new Error(`expected only polish API key row, got ${JSON.stringify(state.settingsApiKeyProviders())}`);
        }

        setProviders('claude_cli', '');
        if (state.settingsApiKeyProviders().length || state.settingsNeedsApiKeyPanel()) {
          throw new Error('expected no API key panel when only Claude CLI is selected');
        }

        setProviders('codex_cli', 'openai');
        if (JSON.stringify(state.settingsApiKeyProviders()) !== JSON.stringify(['openai'])) {
          throw new Error(`expected only OpenAI key row with Codex primary, got ${JSON.stringify(state.settingsApiKeyProviders())}`);
        }

        setProviders('codex_cli', '');
        if (state.settingsApiKeyProviders().length || state.settingsNeedsApiKeyPanel()) {
          throw new Error('expected no API key panel when only Codex CLI is selected');
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_save_settings_applies_workflow_language_defaults_to_project_actions():
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
          state.refreshSystemCheck = async () => {};
          state.checkClaudeCliStatus = async () => {};
          state.settings.asr = { language: 'en' };
          state.settings.translation = {
            primary_provider: 'openai',
            target_language: 'English',
          };
          state.api = async (url, method) => {
            if (url !== '/api/settings' || method !== 'POST') {
              throw new Error(`unexpected save URL ${method} ${url}`);
            }
            return {status: 'ok'};
          };

          await state.saveSettings();

          if (state.asrLanguage !== 'en') {
            throw new Error(`expected saved ASR default to sync, got ${state.asrLanguage}`);
          }
          if (state.targetLang !== 'English') {
            throw new Error(`expected saved target default to sync, got ${state.targetLang}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_tmdb_key_test_calls_endpoint_and_sets_status():
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
          const toasts = [];
          state.toast = (msg, type) => toasts.push({msg, type});
          state.settings.tmdb['api_' + 'key'] = ' tmdb-key ';
          state.settings.tmdb.language = 'en-US';
          state.api = async (url, method, body) => {
            if (url !== '/api/settings/test-tmdb-key' || method !== 'POST') {
              throw new Error(`unexpected API call ${method} ${url}`);
            }
            if (body.api_key !== 'tmdb-key' || body.language !== 'en-US') {
              throw new Error(`unexpected body ${JSON.stringify(body)}`);
            }
            return {success: true, message: '连接成功'};
          };
          await state.testTmdbKey();
          if (state.keyStatus.tmdb !== 'ok') {
            throw new Error(`expected tmdb ok status, got ${state.keyStatus.tmdb}`);
          }
          if (!toasts.some((t) => t.type === 'success' && t.msg === '连接成功')) {
            throw new Error(`expected success toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_settings_uses_canonical_provider_brand_labels():
    html = (ROOT / "app/static/index.html").read_text()

    assert 'x-text="translationProviderLabel(provider)"' in html
    assert "provider.charAt(0).toUpperCase() + provider.slice(1)" not in html


def test_frontend_provider_key_test_blocks_duplicate_submits_while_pending():
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
          let calls = 0;
          let releaseApi;
          state.toast = () => {};
          state.settings.api_keys.openai = 'sk-test';
          state.api = async (url, method, body) => {
            calls += 1;
            if (url !== '/api/settings/test-key' || method !== 'POST' || body.provider !== 'openai') {
              throw new Error(`unexpected key test call ${method} ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {success: true, message: 'ok'};
          };

          const first = state.testKey('openai');
          await Promise.resolve();
          if (state.keyStatus.openai !== 'testing') {
            throw new Error(`expected testing status, got ${state.keyStatus.openai}`);
          }

          const second = state.testKey('openai');
          await Promise.resolve();
          if (calls !== 1) throw new Error(`expected duplicate key test to be ignored, got ${calls} calls`);

          releaseApi();
          await first;
          await second;
          if (state.keyStatus.openai !== 'ok') {
            throw new Error(`expected ok status, got ${state.keyStatus.openai}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_tmdb_key_test_blocks_duplicate_submits_while_pending():
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
          let calls = 0;
          let releaseApi;
          state.toast = () => {};
          state.settings.tmdb['api_' + 'key'] = 'tmdb-key';
          state.api = async (url, method) => {
            calls += 1;
            if (url !== '/api/settings/test-tmdb-key' || method !== 'POST') {
              throw new Error(`unexpected TMDB test call ${method} ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {success: true, message: 'ok'};
          };

          const first = state.testTmdbKey();
          await Promise.resolve();
          if (state.keyStatus.tmdb !== 'testing') {
            throw new Error(`expected testing status, got ${state.keyStatus.tmdb}`);
          }

          const second = state.testTmdbKey();
          await Promise.resolve();
          if (calls !== 1) throw new Error(`expected duplicate TMDB test to be ignored, got ${calls} calls`);

          releaseApi();
          await first;
          await second;
          if (state.keyStatus.tmdb !== 'ok') {
            throw new Error(`expected ok status, got ${state.keyStatus.tmdb}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_paste_key_updates_tmdb_settings_section():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
          navigator: {
            clipboard: {
              readText: async () => ' tmdb-clipboard-key ',
            },
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.toast = () => {};
          await state.pasteKey('tmdb');
          if (state.settings.tmdb.api_key !== 'tmdb-clipboard-key') {
            throw new Error(`expected TMDB key in tmdb settings, got ${JSON.stringify(state.settings)}`);
          }
          if (state.settings.api_keys.tmdb) {
            throw new Error(`TMDB key should not be stored under translation api_keys`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_api_key_panel_stays_visible_for_online_polish_provider():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.settings.translation.primary_provider = 'claude_cli';
        state.settings.translation.polish_provider = 'openai';
        if (state.settingsNeedsApiKeyPanel() !== true) {
          throw new Error('API key panel should stay visible for OpenAI polish provider');
        }

        state.settings.translation.polish_provider = '';
        if (state.settingsNeedsApiKeyPanel() !== false) {
          throw new Error('API key panel should hide when only Claude CLI is enabled');
        }

        state.settings.translation.primary_provider = 'codex_cli';
        if (state.settingsNeedsApiKeyPanel() !== false) {
          throw new Error('API key panel should hide when only Codex CLI is enabled');
        }
        state.settings.translation.polish_provider = 'gemini';
        if (state.settingsNeedsApiKeyPanel() !== true) {
          throw new Error('API key panel should show for Gemini polish provider with Codex primary');
        }

        state.settings.translation.primary_provider = 'deepseek';
        state.settings.translation.polish_provider = '';
        if (state.settingsNeedsApiKeyPanel() !== true) {
          throw new Error('API key panel should show for DeepSeek primary provider');
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_claude_cli_panel_is_visible_for_primary_or_polish_provider():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.settings.translation.primary_provider = 'openai';
        state.settings.translation.polish_provider = '';
        if (state.settingsUsesClaudeCli() !== false) {
          throw new Error('Claude panel should hide when neither provider uses Claude CLI');
        }

        state.settings.translation.polish_provider = 'claude_cli';
        if (state.settingsUsesClaudeCli() !== true) {
          throw new Error('Claude panel should show when polish provider uses Claude CLI');
        }

        state.settings.translation.primary_provider = 'claude_cli';
        state.settings.translation.polish_provider = '';
        if (state.settingsUsesClaudeCli() !== true) {
          throw new Error('Claude panel should show when primary provider uses Claude CLI');
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_local_cli_panel_is_visible_for_claude_or_codex_provider():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.settings.translation.primary_provider = 'openai';
        state.settings.translation.polish_provider = '';
        if (state.settingsUsesLocalCli() !== false) {
          throw new Error('local CLI panel should hide when neither provider uses local CLI');
        }

        state.settings.translation.primary_provider = 'claude_cli';
        if (state.settingsUsesLocalCli() !== true) {
          throw new Error('local CLI panel should show for Claude CLI primary');
        }

        state.settings.translation.primary_provider = 'openai';
        state.settings.translation.polish_provider = 'codex_cli';
        if (state.settingsUsesLocalCli() !== true) {
          throw new Error('local CLI panel should show for Codex CLI polish');
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_codex_cli_panel_is_visible_for_primary_or_polish_provider():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.settings.translation.primary_provider = 'openai';
        state.settings.translation.polish_provider = '';
        if (state.settingsUsesCodexCli() !== false) {
          throw new Error('Codex panel should hide when neither provider uses Codex CLI');
        }

        state.settings.translation.polish_provider = 'codex_cli';
        if (state.settingsUsesCodexCli() !== true) {
          throw new Error('Codex panel should show when polish provider uses Codex CLI');
        }

        state.settings.translation.primary_provider = 'codex_cli';
        state.settings.translation.polish_provider = '';
        if (state.settingsUsesCodexCli() !== true) {
          throw new Error('Codex panel should show when primary provider uses Codex CLI');
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_model_loader_ignores_stale_provider_responses():
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
          state.settings.api_keys.openai = 'sk-openai';
          state.settings.api_keys.deepseek = 'sk-deepseek';
          let releaseOpenAI;
          state.api = async (url) => {
            if (url === '/api/models/openai') {
              await new Promise((resolve) => { releaseOpenAI = resolve; });
              return {models: ['openai-slow']};
            }
            if (url === '/api/models/deepseek') {
              return {models: ['deepseek-fast']};
            }
            throw new Error(`unexpected model URL ${url}`);
          };

          const slow = state.fetchModels('openai', 'primary');
          await Promise.resolve();
          const fast = state.fetchModels('deepseek', 'primary');
          await fast;
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(['deepseek-fast'])) {
            throw new Error(`expected fast provider models first, got ${JSON.stringify(state.primaryModels)}`);
          }

          releaseOpenAI();
          await slow;
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(['deepseek-fast'])) {
            throw new Error(`stale provider response overwrote models: ${JSON.stringify(state.primaryModels)}`);
          }
          if (state.modelLoading.primary) {
            throw new Error('primary model loading should be false after latest request completes');
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_model_loader_clears_loading_when_switching_to_static_provider():
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
          state.settings.api_keys.openai = 'sk-openai';
          let releaseOpenAI;
          state.api = async (url) => {
            if (url !== '/api/models/openai') throw new Error(`unexpected model URL ${url}`);
            await new Promise((resolve) => { releaseOpenAI = resolve; });
            return {models: ['openai-slow']};
          };

          const slow = state.fetchModels('openai', 'primary');
          await Promise.resolve();
          if (!state.modelLoading.primary) throw new Error('expected primary model loader to start');

          await state.fetchModels('claude_cli', 'primary');
          if (state.modelLoading.primary) {
            throw new Error('switching to a static provider should clear loading state');
          }
          const expected = ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5'];
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(expected)) {
            throw new Error(`expected Claude fallback models, got ${JSON.stringify(state.primaryModels)}`);
          }

          releaseOpenAI();
          await slow;
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(expected)) {
            throw new Error(`stale OpenAI response overwrote Claude models: ${JSON.stringify(state.primaryModels)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_model_loader_clears_loading_when_switching_to_codex_cli():
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
          state.settings.api_keys.openai = 'sk-openai';
          let releaseOpenAI;
          state.api = async (url) => {
            if (url !== '/api/models/openai') throw new Error(`unexpected model URL ${url}`);
            await new Promise((resolve) => { releaseOpenAI = resolve; });
            return {models: ['openai-slow']};
          };

          const slow = state.fetchModels('openai', 'primary');
          await Promise.resolve();
          if (!state.modelLoading.primary) throw new Error('expected primary model loader to start');

          await state.fetchModels('codex_cli', 'primary');
          if (state.modelLoading.primary) {
            throw new Error('switching to Codex CLI should clear loading state');
          }
          const expected = ['gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.3-codex-spark'];
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(expected)) {
            throw new Error(`expected Codex fallback models, got ${JSON.stringify(state.primaryModels)}`);
          }

          releaseOpenAI();
          await slow;
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(expected)) {
            throw new Error(`stale OpenAI response overwrote Codex models: ${JSON.stringify(state.primaryModels)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_model_loader_updates_selected_model_when_provider_changes():
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
          state.settings.translation.primary_model = 'gpt-4o';

          await state.fetchModels('deepseek', 'primary');

          const expectedModels = ['deepseek-chat', 'deepseek-reasoner'];
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(expectedModels)) {
            throw new Error(`expected DeepSeek fallback models, got ${JSON.stringify(state.primaryModels)}`);
          }
          if (state.settings.translation.primary_model !== 'deepseek-chat') {
            throw new Error(`expected primary model to follow provider, got ${state.settings.translation.primary_model}`);
          }

          state.settings.translation.primary_model = 'deepseek-reasoner';
          await state.fetchModels('deepseek', 'primary');
          if (state.settings.translation.primary_model !== 'deepseek-reasoner') {
            throw new Error(`expected valid model to be preserved, got ${state.settings.translation.primary_model}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_model_loader_updates_selection_from_live_models_and_clears_polish():
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
          state.settings.api_keys.openai = 'sk-openai';
          state.settings.translation.primary_model = 'gpt-4o';
          state.settings.translation.polish_model = 'gpt-4o-mini';
          state.api = async (url) => {
            if (url !== '/api/models/openai') throw new Error(`unexpected model URL ${url}`);
            return {models: ['provider-live']};
          };

          await state.fetchModels('openai', 'primary');
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(['provider-live'])) {
            throw new Error(`expected live models, got ${JSON.stringify(state.primaryModels)}`);
          }
          if (state.settings.translation.primary_model !== 'provider-live') {
            throw new Error(`expected selected model to update from live list, got ${state.settings.translation.primary_model}`);
          }

          await state.fetchModels('', 'polish');
          if (state.polishModels.length !== 0 || state.settings.translation.polish_model !== '') {
            throw new Error(`expected disabled polish provider to clear model, got ${JSON.stringify({models: state.polishModels, model: state.settings.translation.polish_model})}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_model_loader_surfaces_current_request_errors():
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
          state.settings.api_keys.openai = 'sk-openai';
          state.api = async (url) => {
            if (url !== '/api/models/openai') throw new Error(`unexpected model URL ${url}`);
            throw new Error('models offline');
          };

          await state.fetchModels('openai', 'primary');

          if (state.modelLoading.primary) {
            throw new Error('primary model loading should stop after failure');
          }
          if (!state.modelErrors.primary.includes('models offline')) {
            throw new Error(`expected visible model error, got ${JSON.stringify(state.modelErrors)}`);
          }
          if (!state.primaryModels.includes('gpt-4o')) {
            throw new Error(`expected fallback models to remain available, got ${JSON.stringify(state.primaryModels)}`);
          }

          state.api = async () => ({models: ['gpt-ok']});
          await state.fetchModels('openai', 'primary');
          if (state.modelErrors.primary !== '') {
            throw new Error(`expected model error to clear after success, got ${state.modelErrors.primary}`);
          }
          if (JSON.stringify(state.primaryModels) !== JSON.stringify(['gpt-ok'])) {
            throw new Error(`expected fetched models after recovery, got ${JSON.stringify(state.primaryModels)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_kb_category_labels_are_localized():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        const expected = {
          characters: '角色',
          places: '地点',
          brands: '品牌/机构',
          slang: '术语/俚语',
        };
        for (const [key, label] of Object.entries(expected)) {
          if (state.kbCategoryLabel(key) !== label) {
            throw new Error(`expected ${key} => ${label}, got ${state.kbCategoryLabel(key)}`);
          }
        }
        if (state.kbCategoryLabel('custom') !== 'custom') {
          throw new Error('unknown categories should fall back to the raw key');
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_api_helper_formats_fastapi_validation_errors():
    result = run_js(
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
                {loc: ['body', 'tmdb_id'], msg: 'Input should be greater than 0'},
              ],
            }),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          try {
            await state.api('/api/knowledge/projects/show', 'PUT', {});
          } catch (e) {
            if (!e.message.includes('tmdb_id: Input should be greater than 0')) {
              throw new Error(`expected readable validation message, got ${e.message}`);
            }
            return;
          }
          throw new Error('expected API helper to throw');
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_kb_crud_surfaces_backend_detail_errors():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const calls = [];
        const context = {
          console,
          setTimeout,
          clearTimeout,
          fetch: async (url, opts = {}) => {
            const method = opts.method || 'GET';
            calls.push(`${method} ${url}`);
            const details = {
              'GET /api/knowledge/projects': 'KB list exploded',
              'GET /api/knowledge/projects/missing': 'project KB not found',
              'PUT /api/knowledge/projects/duplicate': 'body key must match path key',
              'PUT /api/knowledge/projects/show': 'tmdb_id must be positive',
              'DELETE /api/knowledge/projects/show': 'not found',
            };
            return {
              ok: false,
              status: 400,
              statusText: 'Bad Request',
              json: async () => ({detail: details[`${method} ${url}`] || 'unexpected'}),
            };
          },
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const toasts = [];
          state.toast = (msg, type) => toasts.push({msg, type});

          await state.loadKbProjects();
          await state.selectKb('missing');

          state.kbNewKeyInput = 'duplicate';
          await state.confirmNewKb();

          state.kbSelectedKey = 'show';
          state.kbCurrent = {
            show_title: 'Show',
            tmdb_id: -1,
            characters: [],
            places: [],
            brands: [],
            slang: [],
            style_notes: {tone: '', perspective: '', rules: []},
          };
          state.kbRulesText = '';
          await state.saveKb();

          state.askConfirm = async () => true;
          await state.deleteKb();

          const joined = toasts.map((t) => t.msg).join('\\n');
          for (const detail of [
            'KB list exploded',
            'project KB not found',
            'body key must match path key',
            'tmdb_id must be positive',
            'not found',
          ]) {
            if (!joined.includes(detail)) {
              throw new Error(`expected ${detail} in toasts, got ${joined}`);
            }
          }
          if (joined.includes('HTTP 400')) {
            throw new Error(`expected backend details instead of generic HTTP codes, got ${joined}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_kb_list_ignores_stale_slow_response_after_refresh():
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
          let releaseOldList;
          let calls = 0;
          state.toast = () => {};
          state.api = async (url) => {
            if (url !== '/api/knowledge/projects') {
              throw new Error(`unexpected KB list URL ${url}`);
            }
            calls += 1;
            if (calls === 1) {
              await new Promise((resolve) => { releaseOldList = resolve; });
              return {projects: [{key: 'old', show_title: 'Old'}]};
            }
            return {projects: [{key: 'new', show_title: 'New'}]};
          };

          const oldLoad = state.loadKbProjects();
          await Promise.resolve();
          const newLoad = state.loadKbProjects();
          await newLoad;

          if (JSON.stringify(state.kbProjects.map((p) => p.key)) !== JSON.stringify(['new'])) {
            throw new Error(`expected refreshed KB list before stale response, got ${JSON.stringify(state.kbProjects)}`);
          }

          releaseOldList();
          await oldLoad;

          if (JSON.stringify(state.kbProjects.map((p) => p.key)) !== JSON.stringify(['new'])) {
            throw new Error(`stale KB list response overwrote refreshed list: ${JSON.stringify(state.kbProjects)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_select_kb_ignores_stale_slow_response_when_switching_keys():
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
          let releaseSlow;
          state.toast = () => {};
          state.api = async (url) => {
            if (url === '/api/knowledge/projects/slow') {
              await new Promise((resolve) => { releaseSlow = resolve; });
              return {
                key: 'slow',
                style_notes: {rules: ['slow rule']},
              };
            }
            if (url === '/api/knowledge/projects/fast') {
              return {
                key: 'fast',
                style_notes: {rules: ['fast rule']},
              };
            }
            throw new Error(`unexpected KB select call ${url}`);
          };

          const slow = state.selectKb('slow');
          await Promise.resolve();
          const fast = state.selectKb('fast');
          await fast;

          if (state.kbSelectedKey !== 'fast' || state.kbCurrent?.key !== 'fast' || state.kbRulesText !== 'fast rule') {
            throw new Error(`expected fast KB before slow resolves, got ${JSON.stringify({selected: state.kbSelectedKey, current: state.kbCurrent?.key, rules: state.kbRulesText})}`);
          }

          releaseSlow();
          await slow;

          if (state.kbSelectedKey !== 'fast' || state.kbCurrent?.key !== 'fast' || state.kbRulesText !== 'fast rule') {
            throw new Error(`stale slow KB response overwrote current editor: ${JSON.stringify({selected: state.kbSelectedKey, current: state.kbCurrent?.key, rules: state.kbRulesText})}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_select_kb_current_key_is_noop_even_when_dirty():
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
          let confirms = 0;
          let calls = 0;
          state.toast = () => {};
          state.askConfirm = async () => {
            confirms += 1;
            return true;
          };
          state.api = async () => {
            calls += 1;
            throw new Error('current KB should not reload');
          };
          state.kbSelectedKey = 'show';
          state.kbCurrent = {key: 'show', show_title: 'Unsaved Show'};
          state.kbRulesText = 'draft rule';
          state.kbDirty = true;

          await state.selectKb('show');

          if (confirms !== 0 || calls !== 0) {
            throw new Error(`current KB click should be a noop, got confirms=${confirms} calls=${calls}`);
          }
          if (!state.kbDirty || state.kbCurrent?.show_title !== 'Unsaved Show' || state.kbRulesText !== 'draft rule') {
            throw new Error(`current KB noop should preserve draft, got ${JSON.stringify({dirty: state.kbDirty, current: state.kbCurrent, rules: state.kbRulesText})}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_select_kb_confirmed_discard_clears_old_draft_when_load_fails():
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
          const toasts = [];
          let confirms = 0;
          let calls = 0;
          state.toast = (msg, type) => toasts.push({msg, type});
          state.askConfirm = async () => {
            confirms += 1;
            return true;
          };
          state.api = async (url) => {
            calls += 1;
            if (url !== '/api/knowledge/projects/missing') {
              throw new Error(`unexpected select URL ${url}`);
            }
            throw new Error('project KB not found');
          };
          state.kbSelectedKey = 'old_show';
          state.kbCurrent = {key: 'old_show', show_title: 'Unsaved'};
          state.kbRulesText = 'draft rule';
          state.kbDirty = true;

          await state.selectKb('missing');

          if (confirms !== 1 || calls !== 1) {
            throw new Error(`expected one confirmation and one load call, got confirms=${confirms} calls=${calls}`);
          }
          if (state.kbSelectedKey !== 'missing') {
            throw new Error(`expected attempted key to stay selected, got ${state.kbSelectedKey}`);
          }
          if (state.kbCurrent !== null || state.kbRulesText !== '' || state.kbDirty !== false) {
            throw new Error(`confirmed discard plus failed load should clear old draft, got ${JSON.stringify({current: state.kbCurrent, rules: state.kbRulesText, dirty: state.kbDirty})}`);
          }
          if (!toasts.some((t) => t.type === 'error' && t.msg.includes('project KB not found'))) {
            throw new Error(`expected visible load error, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_kb_save_blocks_duplicate_submits_while_pending():
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
          let calls = 0;
          let releaseApi;
          state.toast = () => {};
          state.loadKbProjects = async () => {};
          state.kbSelectedKey = 'show';
          state.kbDirty = true;
          state.kbRulesText = 'rule';
          state.kbCurrent = {
            key: 'show',
            show_title: 'Show',
            tmdb_id: null,
            characters: [],
            places: [],
            brands: [],
            slang: [],
            style_notes: {tone: '', perspective: '', rules: []},
          };
          state.api = async (url, method, body) => {
            calls += 1;
            if (url !== '/api/knowledge/projects/show' || method !== 'PUT' || body.key !== 'show') {
              throw new Error(`unexpected KB save call ${method} ${url} ${JSON.stringify(body)}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {ok: true};
          };

          const first = state.saveKb();
          await Promise.resolve();
          if (state.kbActionPending !== 'save') {
            throw new Error(`expected KB save pending state, got ${state.kbActionPending}`);
          }

          const second = state.saveKb();
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate KB save to be ignored, got ${calls} calls`);
          }

          releaseApi();
          await first;
          await second;
          if (state.kbActionPending !== '') {
            throw new Error(`expected KB save pending to clear, got ${state.kbActionPending}`);
          }
          if (state.kbDirty !== false) {
            throw new Error('successful KB save should clear dirty state');
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_kb_delete_blocks_duplicate_confirm_and_delete_while_pending():
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
          let confirms = 0;
          let calls = 0;
          let releaseConfirm;
          let releaseApi;
          state.toast = () => {};
          state.loadKbProjects = async () => {};
          state.kbSelectedKey = 'show';
          state.kbCurrent = {key: 'show', show_title: 'Show'};
          state.kbRulesText = 'rule';
          state.kbDirty = true;
          state.askConfirm = async () => {
            confirms += 1;
            await new Promise((resolve) => { releaseConfirm = resolve; });
            return true;
          };
          state.api = async (url, method) => {
            calls += 1;
            if (url !== '/api/knowledge/projects/show' || method !== 'DELETE') {
              throw new Error(`unexpected KB delete call ${method} ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {ok: true};
          };

          const first = state.deleteKb();
          await Promise.resolve();
          if (state.kbActionPending !== 'delete') {
            throw new Error(`expected KB delete pending state, got ${state.kbActionPending}`);
          }

          const second = state.deleteKb();
          await Promise.resolve();
          if (confirms !== 1) {
            throw new Error(`expected duplicate KB delete to avoid second confirmation, got ${confirms}`);
          }
          if (calls !== 0) {
            throw new Error(`expected no DELETE before confirmation, got ${calls}`);
          }

          releaseConfirm();
          await new Promise((resolve) => setTimeout(resolve, 0));
          if (calls !== 1) {
            throw new Error(`expected one KB DELETE after confirmation, got ${calls}`);
          }

          releaseApi();
          await first;
          await second;
          if (state.kbActionPending !== '') {
            throw new Error(`expected KB delete pending to clear, got ${state.kbActionPending}`);
          }
          if (state.kbSelectedKey !== null || state.kbCurrent !== null || state.kbDirty !== false) {
            throw new Error(`expected KB delete to clear editor state, got ${JSON.stringify({key: state.kbSelectedKey, current: state.kbCurrent, dirty: state.kbDirty})}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_new_kb_declined_discard_does_not_create_project():
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
          let calls = 0;
          state.toast = () => {};
          state.askConfirm = async () => false;
          state.api = async () => {
            calls += 1;
            throw new Error('create should not be called when discard is declined');
          };
          state.kbNewKeyPrompt = true;
          state.kbNewKeyInput = 'new_show';
          state.kbSelectedKey = 'old_show';
          state.kbCurrent = {key: 'old_show', show_title: 'Unsaved'};
          state.kbRulesText = 'draft rule';
          state.kbDirty = true;

          await state.confirmNewKb();

          if (calls !== 0) {
            throw new Error(`expected no create API call after declined discard, got ${calls}`);
          }
          if (!state.kbDirty || state.kbSelectedKey !== 'old_show' || state.kbCurrent?.key !== 'old_show' || state.kbRulesText !== 'draft rule') {
            throw new Error(`declined discard should keep existing KB draft, got ${JSON.stringify({dirty: state.kbDirty, selected: state.kbSelectedKey, current: state.kbCurrent, rules: state.kbRulesText})}`);
          }
          if (!state.kbNewKeyPrompt || state.kbNewKeyInput !== 'new_show') {
            throw new Error('declined discard should leave the new KB modal open with the typed key');
          }
          if (state.kbActionPending !== '') {
            throw new Error(`expected no pending action, got ${state.kbActionPending}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_new_kb_confirmed_discard_creates_and_selects_once():
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
          let confirms = 0;
          const calls = [];
          state.toast = () => {};
          state.askConfirm = async () => {
            confirms += 1;
            return true;
          };
          state.loadKbProjects = async () => {};
          state.api = async (url, method, body) => {
            calls.push({url, method, body});
            if (url === '/api/knowledge/projects/new_show' && method === 'PUT') {
              return {ok: true};
            }
            if (url === '/api/knowledge/projects/new_show' && (method === undefined || method === 'GET')) {
              return {key: 'new_show', show_title: 'New Show', style_notes: {rules: ['new rule']}};
            }
            throw new Error(`unexpected API call ${method} ${url}`);
          };
          state.kbNewKeyPrompt = true;
          state.kbNewKeyInput = 'new_show';
          state.kbSelectedKey = 'old_show';
          state.kbCurrent = {key: 'old_show', show_title: 'Unsaved'};
          state.kbRulesText = 'draft rule';
          state.kbDirty = true;

          await state.confirmNewKb();

          if (confirms !== 1) {
            throw new Error(`expected one discard confirmation, got ${confirms}`);
          }
          if (calls.length !== 2 || calls[0].method !== 'PUT' || calls[1].method !== undefined) {
            throw new Error(`expected create then select calls, got ${JSON.stringify(calls)}`);
          }
          if (state.kbSelectedKey !== 'new_show' || state.kbCurrent?.key !== 'new_show' || state.kbRulesText !== 'new rule') {
            throw new Error(`expected new KB selected, got ${JSON.stringify({selected: state.kbSelectedKey, current: state.kbCurrent, rules: state.kbRulesText})}`);
          }
          if (state.kbDirty || state.kbNewKeyPrompt || state.kbNewKeyInput) {
            throw new Error(`expected clean new KB editor, got ${JSON.stringify({dirty: state.kbDirty, prompt: state.kbNewKeyPrompt, input: state.kbNewKeyInput})}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_claude_cli_status_surfaces_backend_detail_error():
    result = run_js(
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
            status: 503,
            statusText: 'Service Unavailable',
            json: async () => ({detail: 'Claude CLI probe timed out'}),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          await state.checkClaudeCliStatus();
          if (!state.claudeCliStatus.error.includes('Claude CLI probe timed out')) {
            throw new Error(`expected backend detail in status error, got ${JSON.stringify(state.claudeCliStatus)}`);
          }
          if (state.claudeCliStatus.error.includes('HTTP 503')) {
            throw new Error(`expected no generic HTTP code, got ${state.claudeCliStatus.error}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_claude_cli_status_blocks_duplicate_checks_while_pending():
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
          let calls = 0;
          let releaseApi;
          state.api = async (url) => {
            calls += 1;
            if (url !== '/api/settings/claude-cli/status') {
              throw new Error(`unexpected Claude status call ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {installed: true, logged_in: true};
          };

          const first = state.checkClaudeCliStatus();
          await Promise.resolve();
          if (!state.claudeCliChecking) throw new Error('claudeCliChecking should be true while pending');

          const second = state.checkClaudeCliStatus();
          await Promise.resolve();
          if (calls !== 1) throw new Error(`expected duplicate Claude check to be ignored, got ${calls} calls`);

          releaseApi();
          await first;
          await second;
          if (state.claudeCliChecking || !state.claudeCliStatus?.logged_in) {
            throw new Error(`unexpected final status ${JSON.stringify(state.claudeCliStatus)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_codex_cli_status_surfaces_backend_detail_error():
    result = run_js(
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
            status: 503,
            statusText: 'Service Unavailable',
            json: async () => ({detail: 'Codex CLI probe timed out'}),
          }),
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          await state.checkCodexCliStatus();
          if (!state.codexCliStatus.error.includes('Codex CLI probe timed out')) {
            throw new Error(`expected backend detail in status error, got ${JSON.stringify(state.codexCliStatus)}`);
          }
          if (state.codexCliStatus.error.includes('HTTP 503')) {
            throw new Error(`expected no generic HTTP code, got ${state.codexCliStatus.error}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_codex_cli_status_blocks_duplicate_checks_while_pending():
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
          let calls = 0;
          let releaseApi;
          state.api = async (url) => {
            calls += 1;
            if (url !== '/api/settings/codex-cli/status') {
              throw new Error(`unexpected Codex status call ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {installed: true, logged_in: true};
          };

          const first = state.checkCodexCliStatus();
          await Promise.resolve();
          if (!state.codexCliChecking) throw new Error('codexCliChecking should be true while pending');

          const second = state.checkCodexCliStatus();
          await Promise.resolve();
          if (calls !== 1) throw new Error(`expected duplicate Codex check to be ignored, got ${calls} calls`);

          releaseApi();
          await first;
          await second;
          if (state.codexCliChecking || !state.codexCliStatus?.logged_in) {
            throw new Error(`unexpected final status ${JSON.stringify(state.codexCliStatus)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_save_settings_blocks_duplicate_submits_while_pending():
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
          const toasts = [];
          let calls = 0;
          let releaseApi;
          let refreshed = 0;
          state.toast = (msg, type) => toasts.push({msg, type});
          state.refreshSystemCheck = async () => { refreshed += 1; };
          state.settings.translation.primary_provider = 'openai';
          state.api = async (url, method, body) => {
            calls += 1;
            if (url !== '/api/settings' || method !== 'POST' || body !== state.settings) {
              throw new Error(`unexpected save call ${method} ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {ok: true};
          };

          const first = state.saveSettings();
          await Promise.resolve();
          if (!state.settingsSaving) throw new Error('settingsSaving should be true while save is pending');

          const second = state.saveSettings();
          await Promise.resolve();
          if (calls !== 1) throw new Error(`expected duplicate save to be ignored, got ${calls} calls`);

          releaseApi();
          await first;
          await second;

          if (state.settingsSaving) throw new Error('settingsSaving should reset after save finishes');
          if (calls !== 1 || refreshed !== 1) {
            throw new Error(`expected one save and one refresh, got calls=${calls} refreshed=${refreshed}`);
          }
          if (!toasts.some((t) => t.msg === '设置已保存')) {
            throw new Error(`expected saved toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_view_navigation_guards_unsaved_kb_changes():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = {
          console,
          setTimeout,
          clearTimeout,
        };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
        const state = context.app();
        state.view = 'knowledge';
        state.kbDirty = true;
        state.kbCurrent = {show_title: 'Unsaved'};
        state.kbSelectedKey = 'show';
        state.kbRulesText = 'draft';
        const blockedNavigation = state.setView('projects');
        await Promise.resolve();
        if (state.view !== 'knowledge' || !state.confirmPrompt) {
          throw new Error(`expected app confirm prompt before leaving, got view=${state.view} prompt=${state.confirmPrompt}`);
        }
        state.resolveConfirm(false);
        const blockedResult = await blockedNavigation;
        if (blockedResult !== false) throw new Error(`expected declined navigation to return false, got ${blockedResult}`);
        if (!state.kbDirty || !state.kbCurrent || state.kbSelectedKey !== 'show') {
          throw new Error('declined discard should keep the draft intact');
        }

        const allowedNavigation = state.setView('projects');
        await Promise.resolve();
        if (!state.confirmPrompt) throw new Error('expected confirm prompt on second navigation');
        state.resolveConfirm(true);
        const allowedResult = await allowedNavigation;
        if (allowedResult !== true) throw new Error(`expected confirmed navigation to return true, got ${allowedResult}`);
        if (state.view !== 'projects') {
          throw new Error(`expected navigation to projects after confirmation, got ${state.view}`);
        }
        if (state.kbDirty || state.kbCurrent || state.kbSelectedKey || state.kbRulesText) {
          throw new Error('confirmed discard should clear KB draft state');
        }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_project_rename_uses_modal_state_and_patches_trimmed_name():
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
          const toasts = [];
          state.toast = (msg, type) => toasts.push({msg, type});
          state.$nextTick = (fn) => fn();
          state.$refs = {};
          state.currentProject = {id: 'p1', name: 'Old'};
          state.projects = [{id: 'p1', name: 'Old'}];
          state.loadProjects = async () => {
            state.projects = [{id: 'p1', name: 'New'}];
          };
          state.api = async (url, method, body) => {
            if (url !== '/api/projects/p1' || method !== 'PATCH') {
              throw new Error(`unexpected API call ${method} ${url}`);
            }
            if (body.name !== 'New') {
              throw new Error(`expected trimmed name, got ${JSON.stringify(body)}`);
            }
            return {id: 'p1', name: 'New'};
          };

          state.renameProject(state.projects[0]);
          if (!state.projectRenamePrompt || state.projectRenameInput !== 'Old') {
            throw new Error('renameProject should open modal state with existing name');
          }
          state.projectRenameInput = '  New  ';
          await state.confirmRenameProject();
          if (state.projectRenamePrompt || state.projectRenameTarget || state.projectRenameInput) {
            throw new Error('successful rename should clear modal state');
          }
          if (state.currentProject.name !== 'New') {
            throw new Error(`expected current project to update, got ${JSON.stringify(state.currentProject)}`);
          }
          if (!toasts.some((t) => t.msg === '已重命名')) {
            throw new Error(`expected rename toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_project_rename_blocks_duplicate_save_while_pending():
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
          let calls = 0;
          let releaseApi;
          state.toast = () => {};
          state.loadProjects = async () => {};
          state.projectRenameTarget = {id: 'p1', name: 'Old'};
          state.projectRenameInput = 'New';
          state.api = async (url, method, body) => {
            calls += 1;
            if (url !== '/api/projects/p1' || method !== 'PATCH' || body.name !== 'New') {
              throw new Error(`unexpected rename call ${method} ${url} ${JSON.stringify(body)}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {id: 'p1', name: 'New'};
          };

          const first = state.confirmRenameProject();
          await Promise.resolve();
          if (!state.isProjectMutationPending('rename', 'p1')) {
            throw new Error('rename should be pending while PATCH is in flight');
          }

          const second = state.confirmRenameProject();
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate rename save to be ignored, got ${calls} calls`);
          }

          releaseApi();
          await first;
          await second;
          if (state.isProjectMutationPending('rename', 'p1')) {
            throw new Error('rename pending state should clear after PATCH finishes');
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_archive_project_blocks_duplicate_submits_while_pending():
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
          let calls = 0;
          let releaseApi;
          const project = {id: 'p1', name: 'Project', archived: false};
          state.toast = () => {};
          state.loadProjects = async () => {};
          state.api = async (url, method, body) => {
            calls += 1;
            if (url !== '/api/projects/p1' || method !== 'PATCH' || body.archived !== true) {
              throw new Error(`unexpected archive call ${method} ${url} ${JSON.stringify(body)}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {...project, archived: true};
          };

          const first = state.archiveProject(project, true);
          await Promise.resolve();
          if (!state.isProjectMutationPending('archive', 'p1')) {
            throw new Error('archive should be pending while PATCH is in flight');
          }

          const second = state.archiveProject(project, true);
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate archive to be ignored, got ${calls} calls`);
          }

          releaseApi();
          await first;
          await second;
          if (state.isProjectMutationPending('archive', 'p1')) {
            throw new Error('archive pending state should clear after PATCH finishes');
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_reveal_in_finder_blocks_duplicate_submits_while_pending():
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
          let calls = 0;
          let releaseApi;
          const toasts = [];
          state.toast = (message, type) => { toasts.push({message, type}); };
          state.api = async (url, method) => {
            calls += 1;
            if (url !== '/api/projects/p1/reveal' || method !== 'POST') {
              throw new Error(`unexpected reveal call ${method} ${url}`);
            }
            await new Promise((resolve) => { releaseApi = resolve; });
            return {status: 'ok'};
          };

          const first = state.revealInFinder('p1');
          await Promise.resolve();
          if (!state.isProjectMutationPending('reveal', 'p1')) {
            throw new Error('reveal should be pending while POST is in flight');
          }

          const second = state.revealInFinder('p1');
          await Promise.resolve();
          if (calls !== 1) {
            throw new Error(`expected duplicate reveal to be ignored, got ${calls} calls`);
          }

          releaseApi();
          await first;
          await second;
          if (state.isProjectMutationPending('reveal', 'p1')) {
            throw new Error('reveal pending state should clear after POST finishes');
          }
          if (!toasts.some((t) => t.message === '已打开项目位置')) {
            throw new Error(`expected success toast, got ${JSON.stringify(toasts)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_new_kb_modal_focuses_input_and_clears_on_cancel():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        let focused = false;
        state.$nextTick = (fn) => fn();
        state.$refs = {
          kbNewKeyInput: {
            focus: () => { focused = true; },
          },
        };

        state.kbNewKeyInput = 'stale';
        state.startNewKb();
        if (!state.kbNewKeyPrompt || state.kbNewKeyInput !== '') {
          throw new Error('startNewKb should open a clean modal');
        }
        if (!focused) {
          throw new Error('startNewKb should focus the key input');
        }

        state.kbNewKeyInput = 'draft_key';
        state.cancelNewKb();
        if (state.kbNewKeyPrompt || state.kbNewKeyInput) {
          throw new Error('cancelNewKb should close and clear modal state');
        }
        """
    )

    assert result.returncode == 0, result.stderr


def test_frontend_subtitle_delete_waits_for_app_confirmation():
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
          let persisted = 0;
          state.toast = () => {};
          state.currentProject = {id: 'p1'};
          state.subtitles = [{index: 1, start: '00:00:00,000', end: '00:00:01,000', text: 'a'}];
          state.persistSubtitles = async () => { persisted += 1; };

          const rejected = state.deleteSubtitle(0);
          await Promise.resolve();
          if (!state.confirmPrompt) throw new Error('expected subtitle delete confirmation');
          state.resolveConfirm(false);
          await rejected;
          if (state.subtitles.length !== 1 || persisted !== 0) {
            throw new Error('declined subtitle deletion should keep subtitles unchanged');
          }

          const accepted = state.deleteSubtitle(0);
          await Promise.resolve();
          state.resolveConfirm(true);
          await accepted;
          if (state.subtitles.length !== 0 || persisted !== 1) {
            throw new Error(`expected confirmed deletion to persist once, got len=${state.subtitles.length} persisted=${persisted}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr
