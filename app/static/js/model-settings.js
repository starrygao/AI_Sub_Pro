/* Shared model settings state and behavior for the Alpine application. */
globalThis.AISubProModelSettings = function () {
  return {
    modelLoading: { primary: false, polish: false },
    modelErrors: { primary: '', polish: '' },
    modelCache: {},
    modelCatalog: globalThis.AISUBPRO_MODEL_CATALOG || {providers: {}},
    modelCatalogStates: {},
    modelProviders: {},
    modelFetches: {},
    modelRequestSeq: { primary: 0, polish: 0 },
    translationProviderLabel(provider) {
      return {
        openai: 'OpenAI',
        deepseek: 'DeepSeek',
        gemini: 'Gemini',
        omp_cli: 'OMP CLI',
        claude_cli: 'Claude CLI',
        codex_cli: 'Codex CLI',
      }[provider] || provider || '翻译服务';
    },

    providerNeedsApiKey(provider) {
      return ['openai', 'deepseek', 'gemini'].includes(provider);
    },

    settingsApiKeyProviders() {
      const translation = this.isPlainObject(this.settings.translation) ? this.settings.translation : {};
      const providers = [];
      const addProvider = (provider) => {
        if (this.providerNeedsApiKey(provider) && !providers.includes(provider)) {
          providers.push(provider);
        }
      };
      addProvider(translation.primary_provider);
      addProvider(translation.polish_provider);
      return providers;
    },

    settingsNeedsApiKeyPanel() {
      return this.settingsApiKeyProviders().length > 0;
    },

    settingsUsesClaudeCli() {
      const translation = this.isPlainObject(this.settings.translation) ? this.settings.translation : {};
      return translation.primary_provider === 'claude_cli'
        || translation.polish_provider === 'claude_cli';
    },

    settingsUsesCodexCli() {
      const translation = this.isPlainObject(this.settings.translation) ? this.settings.translation : {};
      return translation.primary_provider === 'codex_cli'
        || translation.polish_provider === 'codex_cli';
    },

    settingsUsesOmpCli() {
      const translation = this.settings.translation || {};
      return translation.primary_provider === 'omp_cli' || translation.polish_provider === 'omp_cli';
    },

    selectedOmpModels() {
      const translation = this.settings.translation || {};
      return [...new Set(['primary', 'polish']
        .filter(target => translation[`${target}_provider`] === 'omp_cli')
        .map(target => translation[`${target}_model`] || 'openai-codex/gpt-6-astra'))];
    },

    settingsUsesLocalCli() {
      return this.settingsUsesOmpCli() || this.settingsUsesClaudeCli() || this.settingsUsesCodexCli();
    },

    isLocalCliProvider(provider) {
      return ['omp_cli', 'claude_cli', 'codex_cli'].includes(provider);
    },

    translationModelForProvider(provider, fallback) {
      const translation = this.isPlainObject(this.settings.translation) ? this.settings.translation : {};
      if (translation.primary_provider === provider && typeof translation.primary_model === 'string') {
        return translation.primary_model.trim() || fallback;
      }
      if (translation.polish_provider === provider && typeof translation.polish_model === 'string') {
        return translation.polish_model.trim() || fallback;
      }
      return fallback;
    },

    reasoningEffortOptions(provider, model) {
      const labels = {
        auto: '自动（模型默认）',
        off: '关闭',
        minimal: '最低',
        low: '低',
        medium: '中',
        high: '高',
        xhigh: '超高',
        max: '最大',
        ultra: '极限（多代理）',
      };
      const capability = this.modelCapability(provider, model);
      const translation = this.settings.translation || {};
      // Keep saved efforts selectable while a dynamic CLI model's metadata is unavailable.
      const levels = capability?.reasoning_efforts || ['primary', 'polish']
        .filter(target => translation[`${target}_provider`] === provider && translation[`${target}_model`] === model)
        .map(target => translation[`${target}_effort`])
        .filter(value => value && labels[value]);
      return [...new Set(['auto', ...levels])].map(value => ({ value, label: labels[value] || value }));
    },

    normalizeReasoningEffort(targetKey) {
      if (!this.isPlainObject(this.settings.translation)) this.settings.translation = {};
      const isPrimary = targetKey === 'primary';
      const provider = this.settings.translation[isPrimary ? 'primary_provider' : 'polish_provider'];
      const model = this.settings.translation[isPrimary ? 'primary_model' : 'polish_model'];
      if (!this.modelCapability(provider, model)) return;
      const effortField = isPrimary ? 'primary_effort' : 'polish_effort';
      const current = typeof this.settings.translation[effortField] === 'string'
        ? this.settings.translation[effortField].trim().toLowerCase()
        : 'auto';
      const allowed = this.reasoningEffortOptions(provider, model).map(option => option.value);
      this.settings.translation[effortField] = allowed.includes(current) ? current : 'auto';
    },

    modelCapability(provider, model) {
      const remote = this.modelCatalogStates[provider]?.capabilities?.[model];
      if (remote) return remote;
      const entries = this.modelCatalog.providers?.[provider]?.models || {};
      if (entries[model]) return entries[model];
      if (provider === 'openai' && typeof model === 'string') {
        return entries[model.replace(/-\d{4}-\d{2}-\d{2}$/, '')] || null;
      }
      return null;
    },

    setModelOptions(targetKey, models) {
      const safeModels = [...new Set(Array.isArray(models)
        ? models.filter(m => typeof m === 'string' && m.trim()).map(m => m.trim()) : [])];
      this.ensureSelectedModel(targetKey, safeModels);
      if (targetKey === 'primary') this.primaryModels = safeModels;
      else this.polishModels = safeModels;
    },

    providerModelFallback(provider) {
      return Object.keys(this.modelCatalog.providers?.[provider]?.models || {});
    },

    cliProviderModelOptions(provider) {
      return this.modelCache[provider] || this.providerModelFallback(provider);
    },

    async refreshCliProviderModelCatalog(provider) {
      try {
        const response = await this.api(`/api/models/${provider}`);
        this.cacheModelResponse(provider, response);
      } catch (error) {
        console.warn(`refreshCliProviderModelCatalog failed for ${provider}:`, error);
      }
      return this.cliProviderModelOptions(provider);
    },

    cacheModelResponse(provider, response) {
      const models = [...new Set(Array.isArray(response.models)
        ? response.models.filter(m => typeof m === 'string' && m.trim()).map(m => m.trim()) : [])];
      const source = response.source || (response.fallback ? 'fallback' : 'remote');
      this.modelCatalogStates[provider] = {...response, models, source};
      // Fallbacks must remain retryable when credentials or connectivity recover.
      if (models.length && source !== 'fallback') this.modelCache[provider] = models;
      else delete this.modelCache[provider];
      return models;
    },

    ensureSelectedModel(targetKey, models) {
      if (!this.isPlainObject(this.settings.translation)) this.settings.translation = {};
      const field = targetKey === 'primary' ? 'primary_model' : 'polish_model';
      const current = typeof this.settings.translation[field] === 'string'
        ? this.settings.translation[field].trim() : '';
      if (current) {
        if (!models.includes(current)) models.unshift(current);
      } else if (models.length) {
        this.settings.translation[field] = models[0];
      }
      this.normalizeReasoningEffort(targetKey);
    },

    modelSelectionStatus(target) {
      const provider = this.settings.translation?.[`${target}_provider`];
      const model = this.settings.translation?.[`${target}_model`];
      if (!provider || !model) return '';
      const state = this.modelCatalogStates[provider];
      let status = '内置目录；账号可用性待确认';
      if (state?.source === 'remote') {
        status = state.models.includes(model)
          ? '服务端已列出；实际调用权限待验证'
          : '服务端未列出当前型号；已保留选择，请确认权限或更换型号';
      } else if (state?.reason === 'missing_key') {
        status = '内置目录；填写并保存密钥后可刷新';
      } else if (state?.source === 'fallback') {
        status = '暂未获取在线目录；已保留当前选择';
      }
      const tokens = this.modelCapability(provider, model)?.context_window_tokens;
      return status + (tokens
        ? ` · 上下文 ${tokens.toLocaleString()} tokens`
        : ' · 上下文待确认，暂按 32,000 tokens 处理');
    },

    async fetchModels(provider, target, options = {}) {
      const targetKey = target === 'primary' ? 'primary' : 'polish';
      const requestId = ++this.modelRequestSeq[targetKey];
      const previousProvider = this.modelProviders[targetKey]
        ?? this.settings.translation?.[`${targetKey}_provider`];
      this.modelProviders[targetKey] = provider;
      this.modelErrors[targetKey] = '';
      if (options.providerChanged || (previousProvider && previousProvider !== provider)) {
        this.settings.translation[`${targetKey}_model`] = '';
        this.settings.translation[`${targetKey}_effort`] = 'auto';
      }
      if (!provider) {
        this.settings.translation[`${targetKey}_model`] = '';
        this.setModelOptions(targetKey, []);
        this.modelLoading[targetKey] = false;
        return;
      }
      if (options.force) delete this.modelCache[provider];
      if (this.modelCache[provider]) {
        this.setModelOptions(targetKey, this.modelCache[provider]);
        this.modelLoading[targetKey] = false;
        return;
      }
      const automaticSelection = !this.settings.translation[`${targetKey}_model`];
      this.setModelOptions(targetKey, this.providerModelFallback(provider));
      const loadingSelection = this.settings.translation[`${targetKey}_model`];
      const apiKeys = this.isPlainObject(this.settings.api_keys) ? this.settings.api_keys : {};
      if (!this.isLocalCliProvider(provider) && !apiKeys[provider] && !this.credentialConfigured(provider)) {
        this.modelCatalogStates[provider] = {source: 'fallback', reason: 'missing_key'};
        this.modelLoading[targetKey] = false;
        return;
      }
      this.modelLoading[targetKey] = true;
      try {
        // Share a provider request between translation and polishing, while each
        // stage keeps its own sequence guard and selection.
        if (!this.modelFetches[provider]) {
          this.modelFetches[provider] = this.api(`/api/models/${provider}${options.force ? '?refresh=true' : ''}`)
            .finally(() => { delete this.modelFetches[provider]; });
        }
        const response = await this.modelFetches[provider];
        if (this.modelRequestSeq[targetKey] !== requestId) return;
        const models = this.cacheModelResponse(provider, response);
        if (automaticSelection && this.settings.translation[`${targetKey}_model`] === loadingSelection) {
          this.settings.translation[`${targetKey}_model`] = '';
        }
        this.setModelOptions(targetKey, models.length ? models : this.providerModelFallback(provider));
      } catch (error) {
        if (this.modelRequestSeq[targetKey] === requestId) {
          this.modelCatalogStates[provider] = {source: 'fallback', reason: 'unreachable'};
          this.modelErrors[targetKey] = `模型列表加载失败：${error.message || '请稍后重试'}`;
        }
      } finally {
        if (this.modelRequestSeq[targetKey] === requestId) this.modelLoading[targetKey] = false;
      }
    },

  };
};
