/* AI_Sub_Pro Alpine.js app data + methods.
 * Extracted from app/static/index.html inline <script>.
 */
function app() {
  return {
    view: 'home',
    projects: [],
    showArchived: false,
    currentProject: null,
    workflowState: null,
    workflowStateLoading: false,
    workflowStateError: '',
    workflowActionPending: '',
    subtitles: [],
    settings: {
      api_keys: {openai:'',deepseek:'',gemini:''},
      tmdb: {api_key:'', language:'zh-CN'},
      trailer: {max_video_height: 1080},
      asr: {mode: 'speed'},
      translation: {},
      providers: {
        claude_cli: { enabled: true, model: 'claude-opus-4-7', timeout_sec: 180 },
        codex_cli: { enabled: true, model: 'gpt-5.5', timeout_sec: 180 },
      },
    },
    // Knowledge-base editor state
    kbProjects: [],            // list from GET /api/knowledge/projects
    kbSelectedKey: null,       // which KB is being edited
    kbCurrent: null,           // full ProjectKb being edited
    kbCollapsed: { characters: false, places: false, brands: false, slang: false },
    kbRulesText: '',           // multi-line rules as single textarea string
    kbNewKeyPrompt: false,     // modal state for "+ 新建 KB"
    kbNewKeyInput: '',         // text entered for new KB key
    kbDirty: false,            // unsaved-changes indicator
    kbActionPending: '',
    kbListLoading: false,
    kbListError: '',
    kbSelectingKey: '',
    kbSelectError: '',
    kbListRequestSeq: 0,
    kbSelectRequestSeq: 0,
    kbSuggestions: [],
    kbSuggestionsLoading: false,
    kbSuggestionsError: '',
    kbSuggestionsRequestSeq: 0,
    kbUsageTrace: null,
    kbTraceLoading: false,
    kbTraceError: '',
    kbTraceRequestSeq: 0,
    projectRenamePrompt: false,
    projectRenameInput: '',
    projectRenameTarget: null,
    confirmPrompt: false,
    confirmTitle: '',
    confirmMessage: '',
    confirmConfirmText: '确认',
    confirmCancelText: '取消',
    confirmIntent: 'danger',
    confirmResolve: null,
    newVideoPath: '',
    fileImporting: false,
    projectCreating: false,
    projectActionPending: '',
    asrLanguage: 'auto',
    targetLang: '简体中文',
    editingIdx: -1,
    editText: '',
    subtitleActionPending: '',
    subtitleFindText: '',
    subtitleReplaceText: '',
    subtitleReplaceScope: 'translation',
    subtitleReplaceCaseSensitive: false,
    subtitleQualityOverride: '',
    progressPct: 0,
    progressMsg: '',
    toasts: [],
    toastSeq: 0,
    sysCheck: null,
    sysCheckError: '',
    sysCheckLoading: false,
    sysCheckRequestSeq: 0,
    settingsSaving: false,
    showKeys: { openai: false, deepseek: false, gemini: false, primary: false, polish: false, tmdb: false },
    claudeCliStatus: null,  // null | {installed, logged_in}
    claudeCliChecking: false,
    codexCliStatus: null,  // null | {installed, logged_in}
    codexCliChecking: false,
    keyStatus: {},
    providerKeyUrls: {
      openai: 'https://platform.openai.com/api-keys',
      deepseek: 'https://platform.deepseek.com/api_keys',
      gemini: 'https://aistudio.google.com/apikey',
    },
    primaryModels: [],
    polishModels: [],
    modelLoading: { primary: false, polish: false },
    modelErrors: { primary: '', polish: '' },
    modelCache: {},
    modelRequestSeq: { primary: 0, polish: 0 },
    ws: null,
    wsReconnectTimer: null,
    wsReconnectAttempts: 0,
    progressRefreshError: '',
    progressPollRequestSeq: 0,
    workflowStateRequestSeq: 0,
    initialized: false,
    refreshTimer: null,
    projectListRequestSeq: 0,
    openProjectRequestSeq: 0,
    projectMutationPending: {},

    // Trailer wizard state
    trailerStep: 1,
    trailerSearchMode: 'title',          // 'title' | 'tmdb_id'
    trailerSearchQuery: '',
    trailerSearchResults: [],
    trailerSelectedShow: null,
    trailerSeasons: [],
    trailerSelectedSeasons: [],
    trailerVideos: [],
    trailerSelectedVideos: [],
    trailerError: null,
    trailerCreatedCount: 0,
    trailerLoading: false,
    trailerSubmitting: false,
    trailerSearchRequestSeq: 0,
    trailerVideoRequestSeq: 0,

    async init() {
      if (this.initialized) return;
      this.initialized = true;
      await this.loadSettings();
      await this.loadProjects();
      await this.refreshSystemCheck();
      this.refreshTimer = setInterval(() => {
        if (this.view === 'projects' && this.shouldPollProjectList()) this.loadProjects();
        else if (this.view === 'detail' && this.currentProject) this.pollProgress();
      }, 3000);

      // Global drag-and-drop on home page
      document.addEventListener('dragover', (e) => e.preventDefault());
      document.addEventListener('drop', (e) => e.preventDefault());
    },

    clearKbDraft() {
      this.kbSelectRequestSeq += 1;
      this.kbSelectedKey = null;
      this.kbCurrent = null;
      this.kbRulesText = '';
      this.kbNewKeyPrompt = false;
      this.kbNewKeyInput = '';
      this.kbDirty = false;
      this.kbSelectingKey = '';
      this.kbSelectError = '';
    },

    askConfirm(options = {}) {
      if (this.confirmResolve) this.resolveConfirm(false);
      this.confirmTitle = options.title || '确认操作';
      this.confirmMessage = options.message || '';
      this.confirmConfirmText = options.confirmText || '确认';
      this.confirmCancelText = options.cancelText || '取消';
      this.confirmIntent = options.intent || 'danger';
      this.confirmPrompt = true;
      return new Promise((resolve) => {
        this.confirmResolve = resolve;
        if (typeof this.$nextTick === 'function') {
          this.$nextTick(() => this.$refs.confirmCancelButton?.focus?.());
        }
      });
    },

    resolveConfirm(result) {
      const resolve = this.confirmResolve;
      this.confirmPrompt = false;
      this.confirmTitle = '';
      this.confirmMessage = '';
      this.confirmConfirmText = '确认';
      this.confirmCancelText = '取消';
      this.confirmIntent = 'danger';
      this.confirmResolve = null;
      if (resolve) resolve(!!result);
    },

    async confirmLeaveKbEditor() {
      if (this.view !== 'knowledge' || !this.kbDirty) return true;
      const confirmed = await this.askConfirm({
        title: '丢弃知识库修改？',
        message: '当前知识库有未保存的修改。离开后这些改动会丢失。',
        confirmText: '丢弃并离开',
        intent: 'danger',
      });
      if (!confirmed) return false;
      this.clearKbDraft();
      return true;
    },

    async prepareToLeaveKnowledge() {
      if (this.view !== 'knowledge') return true;
      if (this.kbActionPending || this.kbSelectingKey) {
        this.toast('知识库操作进行中，请稍后再切换', 'error');
        return false;
      }
      if (!await this.confirmLeaveKbEditor()) return false;
      this.kbNewKeyPrompt = false;
      this.kbNewKeyInput = '';
      this.kbSelectError = '';
      return true;
    },

    async setView(nextView) {
      if (!nextView || nextView === this.view) return false;
      const leavingKnowledge = this.view === 'knowledge' && nextView !== 'knowledge';
      if (leavingKnowledge && !await this.prepareToLeaveKnowledge()) return false;
      this.view = nextView;
      if (nextView === 'projects') await this.loadProjects();
      if (nextView === 'knowledge') this.loadKbProjects();
      return true;
    },

    async openTrailerWizard() {
      if (!await this.setView('trailer')) return;
      this.resetTrailer();
    },

    previousTrailerStep() {
      this.trailerError = null;
      if (this.trailerStep <= 1 || this.trailerStep >= 5) return;
      if (this.trailerStep === 4) {
        this.trailerStep = this.trailerSelectedShow?.media_type === 'tv' ? 3 : 2;
        return;
      }
      this.trailerStep -= 1;
    },

    async showTrailerProjects() {
      if (!await this.setView('projects')) return;
      this.resetTrailer();
    },

    toast(msg, type='success') {
      const text = String(msg || '');
      const existing = this.toasts.find(t => t.msg === text && t.type === type);
      if (existing) return existing.id;
      const t = { id: ++this.toastSeq, msg: text, type };
      this.toasts.push(t);
      setTimeout(() => this.toasts = this.toasts.filter(x => x.id !== t.id), 3500);
      return t.id;
    },

    statusText(s) {
      return { created:'新建', processing:'处理中', asr_done:'识别完成', translated:'已翻译', completed:'已完成', error:'错误' }[s] || s;
    },

    statusColor(p) {
      // Returns {bg, text, hex} for badge + progress bar
      const stage = p.pipeline_stage;
      const status = p.status;
      if (status === 'error') return {bg: '#fee2e2', text: '#991b1b', hex: '#dc2626'};
      if (status === 'completed') return {bg: '#dcfce7', text: '#166534', hex: '#16a34a'};
      if (stage === 'download') return {bg: '#ffedd5', text: '#9a3412', hex: '#f97316'};
      if (stage === 'asr' || status === 'asr_done') return {bg: '#f3e8ff', text: '#6b21a8', hex: '#a855f7'};
      if (stage === 'translate' || status === 'translated') return {bg: '#dbeafe', text: '#1e40af', hex: '#3b82f6'};
      if (stage === 'burn') return {bg: '#dcfce7', text: '#166534', hex: '#22c55e'};
      // created / processing / default
      return {bg: '#ccfbf1', text: '#115e59', hex: '#0f766e'};
    },

    isProjectBusy(project) {
      return !!project && (project.status === 'processing' || !!project.pipeline_stage);
    },

    projectActionsDisabled(project) {
      return this.isProjectBusy(project) || !!this.projectActionPending || !!this.workflowActionPending;
    },

    shouldPollProjectList() {
      return Array.isArray(this.projects) && this.projects.some((project) => this.isProjectBusy(project));
    },

    workflowStageLabel(stage) {
      return {
        download: '下载',
        asr: '识别',
        translate: '翻译',
        burn: '烧录',
      }[stage] || stage;
    },

    workflowFailedStages() {
      const stages = this.isPlainObject(this.workflowState?.stages) ? this.workflowState.stages : {};
      return Object.entries(stages)
        .filter(([, item]) => this.isPlainObject(item) && item.status === 'failed')
        .map(([stage, item]) => ({ stage, ...item }));
    },

    subtitleActionKey(action, idx) {
      return `${action}:${idx}`;
    },

    isSubtitleActionPending(action, idx) {
      return this.subtitleActionPending === this.subtitleActionKey(action, idx);
    },

    subtitleActionsDisabled() {
      return !!this.subtitleActionPending;
    },

    exportActionKey(format) {
      return `export:${format || ''}`;
    },

    isExportingSrt(format) {
      return this.projectActionPending === this.exportActionKey(format);
    },

    hasExportableOriginalSubtitles() {
      return this.subtitles.some((item) =>
        this.isPlainObject(item) && !item.filtered && typeof item.text === 'string' && !!item.text.trim()
      );
    },

    hasExportableTranslatedSubtitles() {
      return this.subtitles.some((item) =>
        this.isPlainObject(item) && !item.filtered && typeof item.translation === 'string' && !!item.translation.trim()
      );
    },

    canExportSrt(format) {
      if (!this.currentProject || this.projectActionsDisabled(this.currentProject)) return false;
      if (format === 'original') return this.hasExportableOriginalSubtitles();
      if (format === 'translated' || format === 'bilingual') return this.hasExportableTranslatedSubtitles();
      return false;
    },

    exportSrtLabel(format) {
      const labels = {
        translated: '导出翻译字幕',
        bilingual: '导出双语字幕',
        original: '导出原文字幕',
      };
      return this.isExportingSrt(format) ? '导出中...' : (labels[format] || '导出字幕');
    },

    exportUnavailableMessage(format) {
      if (!this.currentProject) return '请先打开项目';
      if (this.isProjectBusy(this.currentProject)) return '项目处理中，完成后再导出';
      if (this.projectActionPending) return '当前操作未完成，请稍后再试';
      if (format === 'original') return '还没有可导出的原文字幕';
      if (format === 'translated' || format === 'bilingual') return '还没有可导出的翻译字幕';
      return '不支持的导出格式';
    },

    projectMutationKey(action, id) {
      return `${action}:${id || ''}`;
    },

    isProjectMutationPending(action, id) {
      return !!this.projectMutationPending[this.projectMutationKey(action, id)];
    },

    setProjectMutationPending(action, id, pending) {
      const key = this.projectMutationKey(action, id);
      const next = { ...this.projectMutationPending };
      if (pending) next[key] = true;
      else delete next[key];
      this.projectMutationPending = next;
    },

    statusLabel(p) {
      const stage = p.pipeline_stage;
      const status = p.status;
      if (status === 'error') return '失败';
      if (status === 'completed') return '已完成';
      if (stage === 'download') return '下载中';
      if (stage === 'asr') return '识别中';
      if (status === 'asr_done' && !stage) return '识别完成';
      if (stage === 'translate') return '翻译中';
      if (status === 'translated' && !stage) return '翻译完成';
      if (stage === 'burn') return '烧录中';
      if (status === 'processing') return '处理中';
      return '准备中';
    },

    formatDuration(s) {
      const seconds = Number(s);
      if (!Number.isFinite(seconds) || seconds <= 0) return '--:--';
      const m = Math.floor(seconds / 60), sec = Math.floor(seconds % 60);
      return `${m}:${String(sec).padStart(2,'0')}`;
    },

    normalizeProgress(value) {
      const progress = Number(value);
      if (!Number.isFinite(progress)) return 0;
      return Math.max(0, Math.min(100, Math.round(progress)));
    },

    formatDate(d) {
      if (!d) return '';
      // Backend writes UTC but legacy entries may be tz-naive (no 'Z' suffix). Treat missing tz as UTC.
      let iso = String(d);
      if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)) iso = iso + 'Z';
      const date = new Date(iso);
      if (Number.isNaN(date.getTime())) return '';
      return date.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
    },

    homeActiveProjects() {
      return Array.isArray(this.projects)
        ? this.projects.filter(p => this.isPlainObject(p) && !p.archived)
        : [];
    },

    homeProjectSummary() {
      const active = this.homeActiveProjects();
      return active.reduce((summary, project) => {
        const duration = Number(project.duration);
        summary.total += 1;
        if (this.isProjectBusy(project)) summary.running += 1;
        if (project.status === 'completed' || project.output_video) summary.completed += 1;
        if (project.status === 'error') summary.failed += 1;
        if (Number.isFinite(duration) && duration > 0) summary.totalDuration += duration;
        return summary;
      }, { total: 0, running: 0, completed: 0, failed: 0, totalDuration: 0 });
    },

    projectSortTimestamp(project) {
      if (!project || !project.created_at) return 0;
      let iso = String(project.created_at);
      if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)) iso = iso + 'Z';
      const time = new Date(iso).getTime();
      return Number.isFinite(time) ? time : 0;
    },

    recentHomeProjects(limit = 3) {
      return this.homeActiveProjects()
        .slice()
        .sort((a, b) => this.projectSortTimestamp(b) - this.projectSortTimestamp(a))
        .slice(0, limit);
    },

    async api(url, method='GET', body=null) {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch(url, opts);
      if (!r.ok) {
        throw new Error(await this.apiErrorMessage(r));
      }
      return r.json();
    },

    isPlainObject(value) {
      return value && typeof value === 'object' && !Array.isArray(value);
    },

    async apiErrorMessage(response, fallback = '') {
      const errorBody = await response.json().catch(() => ({}));
      return this.formatApiErrorDetail(errorBody.detail)
        || fallback
        || response.statusText
        || `HTTP ${response.status}`;
    },

    formatApiErrorDetail(detail) {
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((item) => {
            if (typeof item === 'string') return item;
            if (this.isPlainObject(item)) {
              const loc = Array.isArray(item.loc)
                ? item.loc.filter(part => part !== 'body' && part !== null && part !== undefined).join('.')
                : '';
              const msg = typeof item.msg === 'string' ? item.msg : '';
              const combined = [loc, msg].filter(Boolean).join(': ');
              return combined || JSON.stringify(item);
            }
            return String(item);
          })
          .filter(Boolean)
          .join('; ');
      }
      if (this.isPlainObject(detail)) return JSON.stringify(detail);
      return '';
    },

    normalizeSettings(data) {
      const incoming = this.isPlainObject(data) ? data : {};
      const current = this.settings || {};
      const mergeSection = (key) => ({
        ...(this.isPlainObject(current[key]) ? current[key] : {}),
        ...(this.isPlainObject(incoming[key]) ? incoming[key] : {}),
      });
      const normalized = {
        ...current,
        ...incoming,
        api_keys: mergeSection('api_keys'),
        tmdb: mergeSection('tmdb'),
        trailer: mergeSection('trailer'),
        asr: mergeSection('asr'),
        translation: mergeSection('translation'),
        providers: {
          ...mergeSection('providers'),
          claude_cli: {
            ...(this.isPlainObject(current.providers?.claude_cli) ? current.providers.claude_cli : {}),
            ...(this.isPlainObject(incoming.providers?.claude_cli) ? incoming.providers.claude_cli : {}),
          },
          codex_cli: {
            ...(this.isPlainObject(current.providers?.codex_cli) ? current.providers.codex_cli : {}),
            ...(this.isPlainObject(incoming.providers?.codex_cli) ? incoming.providers.codex_cli : {}),
          },
        },
      };
      const allowedProviders = ['openai', 'deepseek', 'gemini', 'claude_cli', 'codex_cli'];
      const normalizeProvider = (value, fallback, allowEmpty = true) => {
        if (typeof value !== 'string') return fallback;
        const trimmed = value.trim();
        if (!trimmed && allowEmpty) return '';
        return allowedProviders.includes(trimmed) ? trimmed : fallback;
      };
      normalized.translation.primary_provider = normalizeProvider(
        normalized.translation.primary_provider, 'openai', false
      );
      normalized.translation.polish_provider = normalizeProvider(
        normalized.translation.polish_provider, ''
      );
      const allowedAsrModes = ['speed', 'accuracy', 'offline'];
      const asrMode = typeof normalized.asr.mode === 'string'
        ? normalized.asr.mode.trim()
        : '';
      normalized.asr.mode = allowedAsrModes.includes(asrMode) ? asrMode : 'speed';
      return normalized;
    },

    applyWorkflowDefaultsFromSettings() {
      const asr = this.isPlainObject(this.settings?.asr) ? this.settings.asr : {};
      const translation = this.isPlainObject(this.settings?.translation) ? this.settings.translation : {};
      if (typeof asr.language === 'string' && asr.language.trim()) {
        this.asrLanguage = asr.language.trim();
      }
      if (typeof translation.target_language === 'string' && translation.target_language.trim()) {
        this.targetLang = translation.target_language.trim();
      }
    },

    applyWorkflowDefaultsFromProject(project) {
      if (!this.isPlainObject(project)) return;
      if (typeof project.asr_language === 'string' && project.asr_language.trim()) {
        this.asrLanguage = project.asr_language.trim();
      }
      if (typeof project.target_language === 'string' && project.target_language.trim()) {
        this.targetLang = project.target_language.trim();
      }
    },

    isVideoFile(file) {
      const name = String(file?.name || '').toLowerCase();
      const videoExts = ['.mp4','.mkv','.avi','.mov','.wmv','.flv','.webm','.ts','.m4v'];
      return videoExts.some(ext => name.endsWith(ext));
    },

    canStartProject() {
      return !!String(this.newVideoPath || '').trim()
        && !this.fileImporting
        && !this.projectCreating;
    },

    async uploadVideoFile(file) {
      const formData = new FormData();
      formData.append('file', file);
      const resp = await fetch('/api/projects/upload', { method: 'POST', body: formData });
      if (!resp.ok) {
        throw new Error(await this.apiErrorMessage(resp, '上传失败'));
      }
      const data = await resp.json().catch(() => ({}));
      if (!data.path) throw new Error('服务器未返回文件路径');
      return data.path;
    },

    async useSelectedVideoFile(file) {
      if (!file) return;
      if (!this.isVideoFile(file)) {
        this.toast('请拖入视频文件（MP4、MKV、AVI 等）', 'error');
        return;
      }
      if (this.fileImporting || this.projectCreating) return;
      this.fileImporting = true;
      try {
        if (file.path) {
          this.newVideoPath = file.path;
          await this.quickStart({ allowDuringImport: true });
          return;
        }
        this.toast('正在读取视频文件...');
        this.newVideoPath = await this.uploadVideoFile(file);
        await this.quickStart({ allowDuringImport: true });
      } catch(e) {
        this.toast('文件读取失败: ' + e.message, 'error');
      } finally {
        this.fileImporting = false;
      }
    },

    async loadProjects() {
      const includeArchived = !!this.showArchived;
      const requestId = ++this.projectListRequestSeq;
      try {
        const suffix = includeArchived ? '?include_archived=true' : '';
        const data = await this.api(`/api/projects${suffix}`);
        if (this.projectListRequestSeq !== requestId || !!this.showArchived !== includeArchived) return;
        this.projects = Array.isArray(data) ? data.filter(p => this.isPlainObject(p)) : [];
      } catch(e) {
        if (this.projectListRequestSeq === requestId && !!this.showArchived === includeArchived) {
          this.toast('加载项目失败: ' + e.message, 'error');
        }
      }
    },

    async loadWorkflowState() {
      if (!this.currentProject?.id) {
        this.workflowStateRequestSeq += 1;
        this.workflowState = null;
        this.workflowStateError = '';
        this.workflowStateLoading = false;
        return;
      }
      const projectId = String(this.currentProject.id);
      const requestId = ++this.workflowStateRequestSeq;
      this.workflowStateLoading = true;
      this.workflowStateError = '';
      try {
        const data = await this.api(`/api/projects/${projectId}/workflow-state`);
        if (this.workflowStateRequestSeq !== requestId || String(this.currentProject?.id || '') !== projectId) return;
        this.workflowState = this.isPlainObject(data) ? data : null;
      } catch(e) {
        if (this.workflowStateRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.workflowState = null;
          this.workflowStateError = e.message || '加载工作流状态失败';
        }
      } finally {
        if (this.workflowStateRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.workflowStateLoading = false;
        }
      }
    },

    async loadSettings() {
      try {
        const data = await this.api('/api/settings');
        this.settings = this.normalizeSettings(data);
        this.applyWorkflowDefaultsFromSettings();
        // Load models for configured providers
        this.fetchModels(this.settings.translation?.primary_provider || 'openai', 'primary');
        if (this.settings.translation?.polish_provider) this.fetchModels(this.settings.translation.polish_provider, 'polish');
      } catch(e) {
        this.toast('加载设置失败: ' + e.message, 'error');
      }
    },

    async refreshSystemCheck(options = {}) {
      const force = !!options.force;
      if (this.sysCheckLoading && !force) return;
      const requestId = ++this.sysCheckRequestSeq;
      this.sysCheckLoading = true;
      try {
        const result = await this.api('/api/system-check');
        if (this.sysCheckRequestSeq !== requestId) return;
        this.sysCheck = result;
        this.sysCheckError = '';
      } catch(e) {
        if (this.sysCheckRequestSeq === requestId) {
          this.sysCheckError = e.message || '系统检查失败';
        }
      } finally {
        if (this.sysCheckRequestSeq === requestId) this.sysCheckLoading = false;
      }
    },

    asrModeLabel(mode) {
      const normalized = typeof mode === 'string' ? mode.trim() : '';
      return {
        speed: '速度优先',
        accuracy: '准确优先',
        offline: '离线优先',
      }[normalized] || normalized || '速度优先';
    },

    asrRecommendationSummary() {
      const rec = this.isPlainObject(this.sysCheck?.asr_recommendation)
        ? this.sysCheck.asr_recommendation
        : {};
      if (!Object.keys(rec).length) return '暂无 ASR 推荐';
      const backend = typeof rec.backend === 'string' && rec.backend.trim()
        ? rec.backend.trim()
        : '未检测到后端';
      const model = typeof rec.model_size === 'string' && rec.model_size.trim()
        ? rec.model_size.trim()
        : '未选择模型';
      const hint = typeof rec.download_hint === 'string' ? rec.download_hint.trim() : '';
      const availability = rec.download_required
        ? (hint ? `需下载 ${hint}` : '需下载模型')
        : (rec.ready === false && !rec.backend && !rec.model_size ? '本地不可用' : '本地可用');
      return `${this.asrModeLabel(rec.mode)}：${backend} / ${model}，${availability}`;
    },

    translationProviderLabel(provider) {
      return {
        openai: 'OpenAI',
        deepseek: 'DeepSeek',
        gemini: 'Gemini',
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

    settingsUsesLocalCli() {
      return this.settingsUsesClaudeCli() || this.settingsUsesCodexCli();
    },

    systemTranslationReady() {
      if (!this.sysCheck) return false;
      return this.sysCheck.translation_ready ?? this.sysCheck.api_key;
    },

    systemTranslationHint() {
      return this.sysCheck?.translation_hint || '请配置翻译服务';
    },

    systemTranslationActionText() {
      if (this.sysCheck?.translation_provider === 'claude_cli') return '检查 Claude CLI 设置';
      if (this.sysCheck?.translation_provider === 'codex_cli') return '检查 Codex CLI 设置';
      return '去配置 API 密钥';
    },

    async ensureTranslationReadyForWorkflow() {
      if (!this.systemTranslationReady()) {
        await this.refreshSystemCheck({ force: true });
      }
      if (this.systemTranslationReady()) return true;
      this.toast(`请先完成翻译引擎配置：${this.systemTranslationHint()}`, 'error');
      await this.setView('settings');
      return false;
    },

    kbCategoryLabel(category) {
      return {
        characters: '角色',
        places: '地点',
        brands: '品牌/机构',
        slang: '术语/俚语',
      }[category] || category;
    },
    // ---------- KB management ----------
    async loadKbProjects() {
      const requestId = ++this.kbListRequestSeq;
      this.kbListLoading = true;
      this.kbListError = '';
      try {
        const data = await this.api('/api/knowledge/projects');
        if (this.kbListRequestSeq !== requestId) return;
        this.kbProjects = Array.isArray(data.projects)
          ? data.projects.filter(p => p && typeof p === 'object' && !Array.isArray(p))
          : [];
      } catch (e) {
        if (this.kbListRequestSeq === requestId) {
          this.kbListError = e.message || '加载 KB 列表失败';
          this.toast('加载 KB 列表失败: ' + e.message, 'error');
        }
      } finally {
        if (this.kbListRequestSeq === requestId) this.kbListLoading = false;
      }
    },

    clearKbSuggestions() {
      this.kbSuggestionsRequestSeq += 1;
      this.kbSuggestions = [];
      this.kbSuggestionsLoading = false;
      this.kbSuggestionsError = '';
    },

    clearKbUsageTrace() {
      this.kbTraceRequestSeq += 1;
      this.kbUsageTrace = null;
      this.kbTraceLoading = false;
      this.kbTraceError = '';
    },

    async loadKbSuggestions() {
      if (!this.currentProject?.id) {
        this.clearKbSuggestions();
        return;
      }
      const projectId = String(this.currentProject.id);
      const requestId = ++this.kbSuggestionsRequestSeq;
      this.kbSuggestionsLoading = true;
      this.kbSuggestionsError = '';
      try {
        const data = await this.api(`/api/knowledge/projects/${encodeURIComponent(projectId)}/suggestions`);
        if (this.kbSuggestionsRequestSeq !== requestId || String(this.currentProject?.id || '') !== projectId) return;
        const raw = Array.isArray(data?.suggestions)
          ? data.suggestions
          : (Array.isArray(data?.items) ? data.items : (Array.isArray(data) ? data : []));
        this.kbSuggestions = raw
          .filter(item => this.isPlainObject(item))
          .map(item => ({
            ...item,
            target: typeof item.target === 'string'
              ? item.target
              : (typeof item.suggested_target === 'string' ? item.suggested_target : ''),
            notes: typeof item.notes === 'string' ? item.notes : '',
            selected: item.collision === 'existing' ? false : !!(item.selected ?? true),
          }));
      } catch (e) {
        if (this.kbSuggestionsRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.kbSuggestionsError = e.message || '加载建议失败';
          this.toast('加载 KB 建议失败: ' + e.message, 'error');
        }
      } finally {
        if (this.kbSuggestionsRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.kbSuggestionsLoading = false;
        }
      }
    },

    normalizeKbUsageTrace(data) {
      const src = this.isPlainObject(data) ? data : {};
      const project = this.isPlainObject(src.project) ? src.project : {};
      const matches = Array.isArray(src.matches)
        ? src.matches.filter(item => this.isPlainObject(item))
        : [];
      return {
        ...src,
        project,
        matches,
      };
    },

    async loadKbUsageTrace() {
      if (!this.currentProject?.id) {
        this.clearKbUsageTrace();
        return;
      }
      const projectId = String(this.currentProject.id);
      const requestId = ++this.kbTraceRequestSeq;
      this.kbTraceLoading = true;
      this.kbTraceError = '';
      try {
        const data = await this.api(`/api/knowledge/projects/${encodeURIComponent(projectId)}/usage-trace`);
        if (this.kbTraceRequestSeq !== requestId || String(this.currentProject?.id || '') !== projectId) return;
        this.kbUsageTrace = this.normalizeKbUsageTrace(data);
      } catch (e) {
        if (this.kbTraceRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.kbTraceError = e.message || '加载命中追踪失败';
          this.toast('加载 KB 命中追踪失败: ' + e.message, 'error');
        }
      } finally {
        if (this.kbTraceRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.kbTraceLoading = false;
        }
      }
    },

    async acceptKbSuggestions() {
      if (this.kbActionPending || this.kbSuggestionsLoading) return;
      if (!this.currentProject?.id || !this.kbSelectedKey || !this.kbCurrent) return;
      if (this.kbDirty) {
        this.toast('请先保存当前知识库修改', 'error');
        return;
      }
      const entries = this.kbSuggestions
        .filter(item => this.isPlainObject(item) && item.selected)
        .map(item => {
          const entry = {
            source: typeof item.source === 'string' ? item.source.trim() : '',
            target: typeof item.target === 'string' ? item.target.trim() : '',
            notes: typeof item.notes === 'string' ? item.notes.trim() : '',
          };
          if (typeof item.category === 'string' && item.category.trim()) {
            entry.category = item.category.trim();
          }
          return entry;
        })
        .filter(entry => entry.source);
      if (entries.length === 0) {
        this.toast('请选择要接受的 KB 建议', 'error');
        return;
      }
      const key = this.kbSelectedKey;
      const payload = {
        key,
        show_title: this.kbCurrent.show_title || '',
        tmdb_id: this.kbCurrent.tmdb_id ?? null,
        entries,
      };
      this.kbActionPending = 'suggestions';
      this.kbSuggestionsError = '';
      try {
        await this.api(`/api/knowledge/projects/${encodeURIComponent(this.currentProject.id)}/suggestions/accept`, 'POST', payload);
        this.toast('已接受 KB 建议', 'success');
        if (this.kbSelectedKey === key) this.kbCurrent = null;
        await this.selectKb(this.kbSelectedKey, {allowDuringPending:true});
        await this.loadKbSuggestions();
      } catch (e) {
        this.kbSuggestionsError = e.message || '接受建议失败';
        this.toast('接受 KB 建议失败: ' + e.message, 'error');
      } finally {
        this.kbActionPending = '';
      }
    },

    async rejectKbSuggestion(suggestion) {
      if (this.kbActionPending || this.kbSuggestionsLoading) return;
      const projectId = String(this.currentProject?.id || '');
      const source = this.isPlainObject(suggestion) && typeof suggestion.source === 'string'
        ? suggestion.source.trim()
        : '';
      if (!projectId || !source) return;
      const pendingKey = `reject:${source}`;
      this.kbActionPending = pendingKey;
      this.kbSuggestionsError = '';
      try {
        await this.api(
          `/api/knowledge/projects/${encodeURIComponent(projectId)}/suggestions/reject`,
          'POST',
          { sources: [source] },
        );
        if (String(this.currentProject?.id || '') !== projectId) return;
        this.toast('已拒绝 KB 建议', 'success');
        await this.loadKbSuggestions();
      } catch (e) {
        if (String(this.currentProject?.id || '') === projectId) {
          this.kbSuggestionsError = e.message || '拒绝建议失败';
          this.toast('拒绝 KB 建议失败: ' + e.message, 'error');
        }
      } finally {
        if (this.kbActionPending === pendingKey) this.kbActionPending = '';
      }
    },

    normalizeKb(data) {
      const src = data && typeof data === 'object' && !Array.isArray(data) ? data : {};
      const style = src.style_notes && typeof src.style_notes === 'object' && !Array.isArray(src.style_notes)
        ? src.style_notes
        : {};
      const normalizeEntries = (entries) => Array.isArray(entries)
        ? entries
          .filter(row => row && typeof row === 'object' && !Array.isArray(row))
          .map(row => ({
            source: typeof row.source === 'string' ? row.source : '',
            target: typeof row.target === 'string' ? row.target : '',
            notes: typeof row.notes === 'string' ? row.notes : '',
          }))
        : [];
      return {
        key: typeof src.key === 'string' ? src.key : (this.kbSelectedKey || ''),
        show_title: typeof src.show_title === 'string' ? src.show_title : '',
        tmdb_id: (typeof src.tmdb_id === 'number' || typeof src.tmdb_id === 'string') ? src.tmdb_id : null,
        characters: normalizeEntries(src.characters),
        places: normalizeEntries(src.places),
        brands: normalizeEntries(src.brands),
        slang: normalizeEntries(src.slang),
        style_notes: {
          tone: typeof style.tone === 'string' ? style.tone : '',
          perspective: typeof style.perspective === 'string' ? style.perspective : '',
          rules: Array.isArray(style.rules) ? style.rules.filter(rule => typeof rule === 'string') : [],
        },
      };
    },

    ensureKbCategory(category) {
      const allowed = ['characters', 'places', 'brands', 'slang'];
      if (!this.kbCurrent || !allowed.includes(category)) return null;
      if (!Array.isArray(this.kbCurrent[category])) this.kbCurrent[category] = [];
      return this.kbCurrent[category];
    },

    async selectKb(key, options = {}) {
      const allowDuringPending = this.isPlainObject(options) && !!options.allowDuringPending;
      if (this.kbActionPending && !allowDuringPending) return;
      if (key === this.kbSelectedKey && this.kbCurrent) return;
      if (this.kbDirty) {
        const confirmed = await this.askConfirm({
          title: '切换知识库？',
          message: '当前知识库有未保存的修改。切换后这些改动会丢失。',
          confirmText: '丢弃并切换',
          intent: 'danger',
        });
        if (!confirmed) return;
      }
      const requestId = ++this.kbSelectRequestSeq;
      this.kbSelectedKey = key;
      this.kbCurrent = null;
      this.kbRulesText = '';
      this.kbDirty = false;
      this.kbSelectingKey = key;
      this.kbSelectError = '';
      try {
        const data = await this.api(`/api/knowledge/projects/${encodeURIComponent(key)}`);
        if (this.kbSelectRequestSeq !== requestId || this.kbSelectedKey !== key) return;
        this.kbCurrent = this.normalizeKb(data);
        const rules = this.kbCurrent.style_notes.rules;
        this.kbRulesText = rules.join('\n');
        this.kbDirty = false;
      } catch (e) {
        if (this.kbSelectRequestSeq !== requestId || this.kbSelectedKey !== key) return;
        this.kbSelectError = e.message || '加载知识库失败';
        this.toast('加载 KB 失败: ' + e.message, 'error');
        this.kbCurrent = null;
      } finally {
        if (this.kbSelectRequestSeq === requestId && this.kbSelectedKey === key) {
          this.kbSelectingKey = '';
        }
      }
    },

    startNewKb() {
      if (this.kbActionPending) return;
      this.kbNewKeyPrompt = true;
      this.kbNewKeyInput = '';
      if (typeof this.$nextTick === 'function') {
        this.$nextTick(() => this.$refs.kbNewKeyInput?.focus?.());
      }
    },

    cancelNewKb() {
      if (this.kbActionPending === 'create') return;
      this.kbNewKeyPrompt = false;
      this.kbNewKeyInput = '';
    },

    async confirmNewKb() {
      if (this.kbActionPending) return;
      const key = this.kbNewKeyInput.trim();
      if (!key) return;
      this.kbActionPending = 'create';
      const shouldDiscardDraft = this.kbDirty;
      if (shouldDiscardDraft) {
        const confirmed = await this.askConfirm({
          title: '丢弃知识库修改？',
          message: '当前知识库有未保存的修改。新建并切换后这些改动会丢失。',
          confirmText: '丢弃并新建',
          intent: 'danger',
        });
        if (!confirmed) {
          this.kbActionPending = '';
          return;
        }
      }
      const empty = {
        key, show_title: key, tmdb_id: null,
        characters: [], places: [], brands: [], slang: [],
        style_notes: { tone: '', perspective: '', rules: [] },
      };
      try {
        await this.api(`/api/knowledge/projects/${encodeURIComponent(key)}`, 'PUT', empty);
        if (shouldDiscardDraft && this.kbDirty) this.clearKbDraft();
        this.kbNewKeyPrompt = false;
        this.kbNewKeyInput = '';
        await this.loadKbProjects();
        await this.selectKb(key, { allowDuringPending: true });
        this.toast('新建成功', 'success');
      } catch (e) {
        this.toast('新建失败: ' + e.message, 'error');
      } finally {
        this.kbActionPending = '';
      }
    },

    addKbEntry(category) {
      const entries = this.ensureKbCategory(category);
      if (!entries) return;
      entries.push({ source: '', target: '', notes: '' });
      this.kbDirty = true;
    },

    removeKbEntry(category, index) {
      const entries = this.ensureKbCategory(category);
      if (!entries) return;
      entries.splice(index, 1);
      this.kbDirty = true;
    },

    async saveKb() {
      if (!this.kbCurrent || !this.kbSelectedKey || this.kbActionPending) return;
      const key = this.kbSelectedKey;
      const rules = this.kbRulesText.split('\n').map(s => s.trim()).filter(Boolean);
      this.kbCurrent = this.normalizeKb(this.kbCurrent);
      const payload = {
        key,
        show_title: this.kbCurrent.show_title || '',
        tmdb_id: this.kbCurrent.tmdb_id || null,
        characters: Array.isArray(this.kbCurrent.characters) ? this.kbCurrent.characters : [],
        places: Array.isArray(this.kbCurrent.places) ? this.kbCurrent.places : [],
        brands: Array.isArray(this.kbCurrent.brands) ? this.kbCurrent.brands : [],
        slang: Array.isArray(this.kbCurrent.slang) ? this.kbCurrent.slang : [],
        style_notes: {
          tone: this.kbCurrent.style_notes?.tone || '',
          perspective: this.kbCurrent.style_notes?.perspective || '',
          rules,
        },
      };
      this.kbActionPending = 'save';
      try {
        await this.api(`/api/knowledge/projects/${encodeURIComponent(key)}`, 'PUT', payload);
        if (this.kbSelectedKey === key) this.kbDirty = false;
        this.toast('已保存', 'success');
        await this.loadKbProjects();
      } catch (e) {
        this.toast('保存失败: ' + e.message, 'error');
      } finally {
        this.kbActionPending = '';
      }
    },

    async deleteKb() {
      if (!this.kbSelectedKey || this.kbActionPending) return;
      const key = this.kbSelectedKey;
      this.kbActionPending = 'delete';
      const confirmed = await this.askConfirm({
        title: '删除知识库？',
        message: `确定删除知识库“${key}”？此操作不可撤销。`,
        confirmText: '删除',
        intent: 'danger',
      });
      if (!confirmed) {
        this.kbActionPending = '';
        return;
      }
      try {
        await this.api(`/api/knowledge/projects/${encodeURIComponent(key)}`, 'DELETE');
        if (this.kbSelectedKey === key) {
          this.kbSelectedKey = null;
          this.kbCurrent = null;
          this.kbRulesText = '';
          this.kbDirty = false;
        }
        await this.loadKbProjects();
        this.toast('已删除', 'success');
      } catch (e) {
        this.toast('删除失败: ' + e.message, 'error');
      } finally {
        this.kbActionPending = '';
      }
    },

    toggleKbCategory(cat) { this.kbCollapsed[cat] = !this.kbCollapsed[cat]; },

    // Drag & Drop
    async handleDrop(event) {
      const files = event.dataTransfer?.files;
      if (!files || files.length === 0) return;
      const file = files[0];
      await this.useSelectedVideoFile(file);
    },

    async openFilePicker() {
      if (this.fileImporting || this.projectCreating) return;
      // Try pywebview native API first, then Electron, then browser fallback
      try {
        if (window.pywebview && window.pywebview.api) {
          const p = await window.pywebview.api.select_video();
          if (p) { this.newVideoPath = p; await this.quickStart(); return; }
        } else if (window.electronAPI) {
          const p = await window.electronAPI.selectVideo();
          if (p) { this.newVideoPath = p; await this.quickStart(); return; }
        }
      } catch(e) {
        console.warn('native file picker failed', e);
      }
      this.$refs.fileInput?.click();
    },

    async handleFileSelect(event) {
      const file = event.target?.files?.[0];
      try {
        await this.useSelectedVideoFile(file);
      } finally {
        if (event.target) event.target.value = '';
      }
    },

    async quickStart(options = {}) {
      const allowDuringImport = this.isPlainObject(options) && !!options.allowDuringImport;
      if (this.projectCreating || (this.fileImporting && !allowDuringImport)) return;
      const originalPath = this.newVideoPath;
      const videoPath = String(originalPath || '').trim();
      if (!videoPath) return;
      this.projectCreating = true;
      try {
        if (!await this.ensureTranslationReadyForWorkflow()) return;
        const p = await this.api('/api/projects', 'POST', {
          video_path: videoPath,
          asr_language: this.asrLanguage,
          target_language: this.targetLang,
        });
        if (this.newVideoPath === originalPath) this.newVideoPath = '';
        this.toast('项目已创建，开始处理...');
        this.clearKbSuggestions();
        this.clearKbUsageTrace();
        this.currentProject = p;
        this.workflowState = null;
        this.workflowStateError = '';
        this.applyWorkflowDefaultsFromProject(p);
        await this.setView('detail');
        this.connectWS(p.id);
        // Auto-start full pipeline
        await this.api(`/api/projects/${p.id}/start-full`, 'POST', { language: this.asrLanguage, target_language: this.targetLang });
        this.currentProject.status = 'processing';
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.projectCreating = false;
      }
    },

    async deleteProject(id) {
      if (this.isProjectMutationPending('delete', id)) return;
      this.setProjectMutationPending('delete', id, true);
      const project = this.projects.find((p) => p.id === id) || (this.currentProject?.id === id ? this.currentProject : null);
      const name = project?.name || id;
      const confirmed = await this.askConfirm({
        title: '删除项目？',
        message: `确定删除“${name}”？相关字幕、进度和输出文件都会被移除。`,
        confirmText: '删除',
        intent: 'danger',
      });
      if (!confirmed) {
        this.setProjectMutationPending('delete', id, false);
        return;
      }
      try {
        await this.api(`/api/projects/${id}`, 'DELETE');
        let projectsRefreshed = false;
        if (this.currentProject?.id === id) {
          if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
            this.wsReconnectTimer = null;
          }
          if (this.ws) {
            this.ws.onclose = null;
            this.ws.close();
            this.ws = null;
          }
          this.currentProject = null;
          this.workflowState = null;
          this.workflowStateError = '';
          this.workflowActionPending = '';
          this.clearKbSuggestions();
          this.clearKbUsageTrace();
          this.subtitles = [];
          this.progressPct = 0;
          this.progressMsg = '';
          projectsRefreshed = await this.setView('projects');
        }
        this.toast('已删除');
        if (!projectsRefreshed) await this.loadProjects();
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('delete', id, false);
      }
    },

    async renameProject(project) {
      if (!project) return;
      this.projectRenameTarget = project;
      this.projectRenameInput = String(project.name || '');
      this.projectRenamePrompt = true;
      if (typeof this.$nextTick === 'function') {
        this.$nextTick(() => this.$refs.renameProjectInput?.focus?.());
      }
    },

    cancelRenameProject() {
      this.projectRenamePrompt = false;
      this.projectRenameInput = '';
      this.projectRenameTarget = null;
    },

    async confirmRenameProject() {
      const project = this.projectRenameTarget;
      if (!project?.id) {
        this.cancelRenameProject();
        return;
      }
      const trimmed = this.projectRenameInput.trim();
      if (!trimmed) {
        this.toast('项目名称不能为空', 'error');
        return;
      }
      if (trimmed === String(project.name || '').trim()) {
        this.cancelRenameProject();
        return;
      }
      if (this.isProjectMutationPending('rename', project.id)) return;
      this.setProjectMutationPending('rename', project.id, true);
      try {
        const updated = await this.api(`/api/projects/${project.id}`, 'PATCH', { name: trimmed });
        if (this.currentProject?.id === project.id) this.currentProject = updated;
        await this.loadProjects();
        this.cancelRenameProject();
        this.toast('已重命名');
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('rename', project.id, false);
      }
    },

    async archiveProject(project, archived = true) {
      if (!project) return;
      if (this.isProjectMutationPending('archive', project.id)) return;
      this.setProjectMutationPending('archive', project.id, true);
      try {
        const updated = await this.api(`/api/projects/${project.id}`, 'PATCH', { archived });
        if (this.currentProject?.id === project.id) this.currentProject = updated;
        await this.loadProjects();
        this.toast(archived ? '已归档' : '已恢复');
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('archive', project.id, false);
      }
    },

    async revealInFinder(id) {
      if (!id || this.isProjectMutationPending('reveal', id)) return;
      this.setProjectMutationPending('reveal', id, true);
      try {
        const r = await this.api(`/api/projects/${id}/reveal`, 'POST');
        if (r.status === 'ok') this.toast('已打开项目位置');
        else this.toast(r.message || '打开失败', 'error');
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('reveal', id, false);
      }
    },

    async openProject(id) {
      if (!await this.prepareToLeaveKnowledge()) return;
      const requestId = ++this.openProjectRequestSeq;
      try {
        const project = await this.api(`/api/projects/${id}`);
        if (this.openProjectRequestSeq !== requestId) return;
        const data = await this.api(`/api/projects/${id}/subtitles`);
        if (this.openProjectRequestSeq !== requestId) return;
        if (this.currentProject?.id !== project.id) {
          this.clearKbSuggestions();
          this.clearKbUsageTrace();
        }
        this.currentProject = project;
        await this.loadWorkflowState();
        if (this.openProjectRequestSeq !== requestId || this.currentProject?.id !== project.id) return;
        this.loadKbUsageTrace();
        this.applyWorkflowDefaultsFromProject(project);
        this.subtitles = Array.isArray(data.blocks) ? data.blocks.filter(b => this.isPlainObject(b)) : [];
        await this.setView('detail');
        if (this.openProjectRequestSeq !== requestId) return;
        this.connectWS(id);
      } catch(e) {
        if (this.openProjectRequestSeq === requestId) this.toast(e.message, 'error');
      }
    },

    describeSubtitleTrack(project) {
      if (!project) return '';
      const idx = project.selected_subtitle_track;
      if (idx === null || idx === undefined) return '';
      // Backend _pick_subtitle_track returns an index into the UNFILTERED
      // subtitle_tracks list (matches ffmpeg -map 0:s:N). Do NOT pre-filter
      // to text codecs before indexing — that misaligns the index when the
      // input has image-based tracks (PGS/DVD/DVB) ahead of text tracks.
      const tracks = project.subtitle_tracks || [];
      const t = tracks[idx];
      if (!t) return '';
      const parts = [];
      if (t.codec) parts.push(t.codec);
      if (t.lang && t.lang !== 'und') parts.push(t.lang);
      if (t.title) parts.push(t.title);
      return parts.join(' · ');
    },

    async toggleEmbeddedSubtitle() {
      if (!this.currentProject) return;
      const projectId = this.currentProject.id;
      if (this.isProjectMutationPending('embedded-subtitle', projectId)) return;
      const next = !this.currentProject.prefer_embedded_subtitle;
      this.setProjectMutationPending('embedded-subtitle', projectId, true);
      try {
        const updated = await this.api(
          `/api/projects/${projectId}`, 'PATCH',
          { prefer_embedded_subtitle: next }
        );
        if (this.currentProject?.id === projectId) this.currentProject = updated;
        this.toast(next ? '将使用内嵌字幕' : '将重新听写');
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('embedded-subtitle', projectId, false);
      }
    },

    async pickTmdbCandidate(c) {
      if (!this.currentProject || !c) return;
      const projectId = this.currentProject.id;
      if (this.isProjectMutationPending('tmdb', projectId)) return;
      this.setProjectMutationPending('tmdb', projectId, true);
      try {
        const updated = await this.api(
          `/api/projects/${projectId}`, 'PATCH', {
            tmdb_id: c.tmdb_id,
            tmdb_type: c.tmdb_type,
            show_title: c.title,
            poster_path: c.poster_path,
            original_language: c.original_language,
            clear: ['tmdb_candidates'],
          }
        );
        if (this.currentProject?.id === projectId) this.currentProject = updated;
        this.toast(`已关联 TMDB: ${c.title}`);
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('tmdb', projectId, false);
      }
    },

    async dismissTmdbCandidates() {
      if (!this.currentProject) return;
      const projectId = this.currentProject.id;
      if (this.isProjectMutationPending('tmdb', projectId)) return;
      this.setProjectMutationPending('tmdb', projectId, true);
      try {
        const updated = await this.api(
          `/api/projects/${projectId}`, 'PATCH',
          { clear: ['tmdb_candidates'] }
        );
        if (this.currentProject?.id === projectId) this.currentProject = updated;
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('tmdb', projectId, false);
      }
    },

    async unlinkTmdb() {
      if (!this.currentProject) return;
      const projectId = this.currentProject.id;
      if (this.isProjectMutationPending('tmdb', projectId)) return;
      this.setProjectMutationPending('tmdb', projectId, true);
      try {
        const updated = await this.api(
          `/api/projects/${projectId}`, 'PATCH', {
            clear: ['tmdb_id', 'tmdb_type', 'season_number',
                    'show_title', 'poster_path', 'original_language'],
          }
        );
        if (this.currentProject?.id === projectId) this.currentProject = updated;
        this.toast('已解除 TMDB 关联');
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('tmdb', projectId, false);
      }
    },

    connectWS(id) {
      if (this.wsReconnectTimer) {
        clearTimeout(this.wsReconnectTimer);
        this.wsReconnectTimer = null;
      }
      if (this.ws) {
        this.ws.onclose = null;
        this.ws.close();
        this.ws = null;
      }
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const safeId = encodeURIComponent(id);
      const socket = new WebSocket(`${proto}//${location.host}/ws/progress/${safeId}`);
      this.ws = socket;
      socket.onopen = () => {
        this.wsReconnectAttempts = 0;
        this.progressRefreshError = '';
      };
      socket.onmessage = (e) => {
        let d;
        try {
          d = JSON.parse(e.data);
        } catch (err) {
          console.warn('progress WS: bad JSON frame, ignoring', err);
          return;
        }
        if (!d || typeof d !== 'object') return;
        const progress = this.normalizeProgress(d.progress);
        const message = typeof d.message === 'string' ? d.message : '';
        this.progressPct = progress;
        this.progressMsg = message;
        if (this.currentProject) {
          this.currentProject.progress = progress;
          this.currentProject.progress_msg = message;
        }
      };
      socket.onerror = (err) => {
        console.warn('progress WS error', err);
        this.progressRefreshError = '实时进度连接异常，正在重试...';
      };
      socket.onclose = () => {
        if (this.ws === socket) this.ws = null;
        if (!this.currentProject || this.currentProject.id !== id || this.view !== 'detail') return;
        if (this.wsReconnectAttempts >= 5) {
          this.progressRefreshError = '实时进度连接中断，正在使用轮询刷新。';
          return;
        }
        const delay = Math.min(1000 * Math.pow(2, this.wsReconnectAttempts), 10000);
        this.wsReconnectAttempts += 1;
        this.wsReconnectTimer = setTimeout(() => this.connectWS(id), delay);
      };
    },

    async pollProgress() {
      if (!this.currentProject) return;
      const projectId = this.currentProject.id;
      const oldBusy = this.isProjectBusy(this.currentProject);
      const requestId = ++this.progressPollRequestSeq;
      try {
        const p = await this.api(`/api/projects/${projectId}`);
        if (this.progressPollRequestSeq !== requestId || this.currentProject?.id !== projectId) return;
        this.currentProject = p;
        this.progressRefreshError = '';
        if (oldBusy && !this.isProjectBusy(p)) {
          const data = await this.api(`/api/projects/${p.id}/subtitles`);
          if (this.progressPollRequestSeq !== requestId || this.currentProject?.id !== projectId) return;
          this.subtitles = Array.isArray(data.blocks) ? data.blocks.filter(b => this.isPlainObject(b)) : [];
          if (p.status === 'error') this.toast(p.error || '处理失败', 'error');
          else if (p.status === 'completed') this.toast('带字幕的视频已就绪！');
          else this.toast('处理完成');
          await this.loadWorkflowState();
        }
      } catch(e) {
        if (this.progressPollRequestSeq !== requestId || this.currentProject?.id !== projectId) return;
        this.progressRefreshError = e.message || '无法刷新处理进度';
        if (!this.progressMsg) this.progressMsg = '进度连接中断，正在重试...';
      }
    },

    async retryWorkflowStage(stage) {
      const normalizedStage = String(stage || '').trim();
      if (!normalizedStage || !this.currentProject?.id || this.projectActionsDisabled(this.currentProject)) return;
      const projectId = String(this.currentProject.id);
      const action = `retry:${normalizedStage}`;
      this.workflowActionPending = action;
      try {
        await this.api(`/api/projects/${projectId}/retry`, 'POST', { stage: normalizedStage });
        if (String(this.currentProject?.id || '') === projectId) {
          this.currentProject.status = 'processing';
          this.currentProject.pipeline_stage = normalizedStage;
          this.currentProject.error = '';
        }
        this.toast('已重新启动失败阶段');
        await this.loadWorkflowState();
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        if (this.workflowActionPending === action) this.workflowActionPending = '';
      }
    },

    async resumeWorkflow() {
      if (!this.currentProject?.id || this.projectActionsDisabled(this.currentProject)) return;
      const projectId = String(this.currentProject.id);
      this.workflowActionPending = 'resume';
      try {
        const result = await this.api(`/api/projects/${projectId}/resume`, 'POST');
        if (String(this.currentProject?.id || '') === projectId) {
          const stage = typeof result?.stage === 'string' ? result.stage.trim() : '';
          this.currentProject.status = 'processing';
          if (['asr', 'translate', 'burn'].includes(stage)) {
            this.currentProject.pipeline_stage = stage;
          }
          this.currentProject.error = '';
        }
        this.toast('已恢复工作流');
        await this.loadWorkflowState();
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        if (this.workflowActionPending === 'resume') this.workflowActionPending = '';
      }
    },

    async runProjectAction(action, endpoint, body, message, options = {}) {
      if (!this.currentProject || this.projectActionsDisabled(this.currentProject)) return;
      this.projectActionPending = action;
      try {
        if (options.requiresTranslation && !await this.ensureTranslationReadyForWorkflow()) return;
        await this.api(endpoint, 'POST', body);
        this.currentProject.status = 'processing';
        this.toast(message);
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        if (this.projectActionPending === action) this.projectActionPending = '';
      }
    },

    async startASR() {
      if (!this.currentProject) return;
      await this.runProjectAction(
        'start-asr',
        `/api/projects/${this.currentProject.id}/start-asr`,
        { language: this.asrLanguage },
        '开始语音识别...'
      );
    },

    async startTranslate() {
      if (!this.currentProject) return;
      await this.runProjectAction(
        'start-translate',
        `/api/projects/${this.currentProject.id}/start-translate`,
        { target_language: this.targetLang },
        '开始翻译...',
        { requiresTranslation: true }
      );
    },

    async startFull() {
      if (!this.currentProject) return;
      await this.runProjectAction(
        'start-full',
        `/api/projects/${this.currentProject.id}/start-full`,
        { language: this.asrLanguage, target_language: this.targetLang },
        '开始一键处理...',
        { requiresTranslation: true }
      );
    },

    async startBurn() {
      if (!this.currentProject) return;
      await this.runProjectAction(
        'burn',
        `/api/projects/${this.currentProject.id}/burn`,
        null,
        '正在烧录字幕到视频...'
      );
    },

    async cancelTask() {
      if (!this.currentProject || this.projectActionPending) return;
      this.projectActionPending = 'cancel';
      try {
        const result = await this.api(`/api/projects/${this.currentProject.id}/cancel`, 'POST');
        if (result.status === 'cancelled') {
          this.toast('已取消');
          this.currentProject.status = 'error';
          this.currentProject.pipeline_stage = null;
          this.currentProject.error = 'Cancelled by user';
        } else {
          this.toast('没有正在运行的任务', 'error');
        }
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        if (this.projectActionPending === 'cancel') this.projectActionPending = '';
      }
    },

    startEdit(idx, text) {
      this.editingIdx = idx;
      this.editText = text || '';
      this.$nextTick(() => { if (this.$refs.editArea) this.$refs.editArea.focus(); });
    },

    async saveEdit(idx) {
      if (this.subtitleActionsDisabled()) return;
      if (this.editingIdx < 0) return;
      if (!this.isValidSubtitleIndex(idx)) {
        this.editingIdx = -1;
        return;
      }
      const actionKey = this.subtitleActionKey('save', idx);
      this.subtitleActionPending = actionKey;
      const before = this.subtitleSnapshot();
      const previousEditingIdx = this.editingIdx;
      this.subtitles[idx].translation = this.editText;
      this.editingIdx = -1;
      try {
        await this.persistSubtitles();
      } catch(e) {
        this.restoreSubtitles(before);
        this.editingIdx = previousEditingIdx;
        this.toast('保存失败', 'error');
      } finally {
        if (this.subtitleActionPending === actionKey) this.subtitleActionPending = '';
      }
    },

    parseSrtTime(value) {
      const m = String(value || '00:00:00,000').match(/^(\d+):(\d{2}):(\d{2})[,.](\d{3})$/);
      if (!m) return 0;
      const h = Number(m[1]);
      const minutes = Number(m[2]);
      const seconds = Number(m[3]);
      const millis = Number(m[4]);
      if (![h, minutes, seconds, millis].every(Number.isFinite) || minutes >= 60 || seconds >= 60) return 0;
      return (((h * 60) + minutes) * 60 + seconds) * 1000 + millis;
    },

    formatSrtTime(ms) {
      const value = Number(ms);
      const safe = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
      const h = Math.floor(safe / 3600000);
      const m = Math.floor((safe % 3600000) / 60000);
      const s = Math.floor((safe % 60000) / 1000);
      const milli = safe % 1000;
      return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(milli).padStart(3, '0')}`;
    },

    splitTextAtMiddle(text) {
      const value = String(text || '').trim();
      if (!value) return ['', ''];
      const midpoint = Math.floor(value.length / 2);
      const rightSpace = value.indexOf(' ', midpoint);
      const leftSpace = value.lastIndexOf(' ', midpoint);
      let cut = midpoint;
      if (leftSpace > 0 && (rightSpace < 0 || midpoint - leftSpace <= rightSpace - midpoint)) cut = leftSpace;
      else if (rightSpace > 0) cut = rightSpace;
      return [value.slice(0, cut).trim(), value.slice(cut).trim()];
    },

    subtitleDurationMs(item) {
      if (!this.isPlainObject(item)) return 0;
      return this.parseSrtTime(item.end) - this.parseSrtTime(item.start);
    },

    joinSubtitleText(left, right) {
      return [left, right]
        .map((value) => String(value || '').trim())
        .filter(Boolean)
        .join('\n');
    },

    subtitleQualityIssues() {
      const issues = [];
      const lineLimit = 42;
      const readingSpeedLimit = 22;
      let previous = null;
      const addIssue = (item, idx, code, severity, message) => {
        issues.push({
          code,
          severity,
          index: Number.isInteger(item?.index) ? item.index : idx + 1,
          message,
        });
      };

      this.subtitles.forEach((item, idx) => {
        if (!this.isPlainObject(item) || item.filtered) return;
        const hasTiming = typeof item.start === 'string' && typeof item.end === 'string';
        const startMs = hasTiming ? this.parseSrtTime(item.start) : 0;
        const endMs = hasTiming ? this.parseSrtTime(item.end) : 0;
        const durationMs = endMs - startMs;
        const sourceText = typeof item.text === 'string' ? item.text.trim() : '';
        const translationText = typeof item.translation === 'string' ? item.translation.trim() : '';

        if (hasTiming && previous && startMs < previous.endMs) {
          addIssue(item, idx, 'overlap', 'severe', `第 ${idx + 1} 行与上一行时间重叠`);
        }
        if (hasTiming && durationMs <= 0) {
          addIssue(item, idx, 'non_positive_duration', 'severe', `第 ${idx + 1} 行时长无效`);
        }
        if (!sourceText) {
          addIssue(item, idx, 'empty_source', 'severe', `第 ${idx + 1} 行缺少原文`);
        }
        if (sourceText && !translationText) {
          addIssue(item, idx, 'missing_translation', 'severe', `第 ${idx + 1} 行缺少译文`);
        }

        const lines = `${sourceText}\n${translationText}`.split(/\r?\n/);
        if (lines.some((line) => line.trim().length > lineLimit)) {
          addIssue(item, idx, 'long_line', 'warning', `第 ${idx + 1} 行过长`);
        }
        const readableChars = Math.max(sourceText.length, translationText.length);
        const seconds = durationMs / 1000;
        if (hasTiming && readableChars > 0 && (seconds <= 0 || readableChars / seconds > readingSpeedLimit)) {
          addIssue(item, idx, 'reading_speed', 'warning', `第 ${idx + 1} 行阅读速度过快`);
        }

        if (hasTiming) previous = { endMs };
      });

      return issues;
    },

    subtitleQualitySummary() {
      const issues = this.subtitleQualityIssues();
      return issues.reduce((summary, issue) => {
        summary.total += 1;
        if (issue.severity === 'severe') summary.severe += 1;
        else summary.warning += 1;
        return summary;
      }, { total: 0, severe: 0, warning: 0, issues });
    },

    hasSevereSubtitleIssues() {
      return this.subtitleQualitySummary().severe > 0;
    },

    subtitleReplaceFields() {
      const scope = this.subtitleReplaceScope || 'translation';
      if (scope === 'source' || scope === 'text') return ['text'];
      if (scope === 'all') return ['text', 'translation'];
      return ['translation'];
    },

    escapeRegExp(value) {
      return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    },

    replaceInSubtitleField(value, find, replacement, caseSensitive = false) {
      const source = String(value || '');
      const needle = String(find || '');
      if (!needle) return { value: source, count: 0 };
      const flags = caseSensitive ? 'g' : 'gi';
      const pattern = new RegExp(this.escapeRegExp(needle), flags);
      let count = 0;
      const next = source.replace(pattern, () => {
        count += 1;
        return String(replacement || '');
      });
      return { value: next, count };
    },

    subtitleReplacePreview() {
      const find = String(this.subtitleFindText || '');
      const replacement = String(this.subtitleReplaceText || '');
      const rows = [];
      let count = 0;
      if (!find) return { count, rows, scope: this.subtitleReplaceScope || 'translation' };
      const fields = this.subtitleReplaceFields();
      this.subtitles.forEach((item, idx) => {
        if (!this.isPlainObject(item) || item.filtered) return;
        let rowCount = 0;
        fields.forEach((field) => {
          rowCount += this.replaceInSubtitleField(
            item[field],
            find,
            replacement,
            !!this.subtitleReplaceCaseSensitive
          ).count;
        });
        if (rowCount > 0) {
          count += rowCount;
          rows.push({
            index: Number.isInteger(item.index) ? item.index : idx + 1,
            count: rowCount,
          });
        }
      });
      return { count, rows, scope: this.subtitleReplaceScope || 'translation' };
    },

    async applySubtitleReplace() {
      if (this.subtitleActionsDisabled()) return;
      const preview = this.subtitleReplacePreview();
      if (!preview.count) {
        this.toast('没有找到可替换的字幕文本', 'error');
        return;
      }
      const actionKey = this.subtitleActionKey('replace', 0);
      this.subtitleActionPending = actionKey;
      const before = this.subtitleSnapshot();
      const fields = this.subtitleReplaceFields();
      this.subtitles.forEach((item) => {
        if (!this.isPlainObject(item) || item.filtered) return;
        fields.forEach((field) => {
          const replaced = this.replaceInSubtitleField(
            item[field],
            this.subtitleFindText,
            this.subtitleReplaceText,
            !!this.subtitleReplaceCaseSensitive
          );
          item[field] = replaced.value;
        });
      });
      try {
        await this.persistSubtitles();
        this.toast(`已替换 ${preview.count} 处`);
      } catch(e) {
        this.restoreSubtitles(before);
        this.toast('保存失败', 'error');
      } finally {
        if (this.subtitleActionPending === actionKey) this.subtitleActionPending = '';
      }
    },

    subtitleExportWarningMessage(format) {
      const summary = this.subtitleQualitySummary();
      if (!summary.total) return '';
      const firstSevere = summary.issues.find((issue) => issue.severity === 'severe');
      const issueText = firstSevere?.message || summary.issues[0]?.message || '字幕存在质量提示';
      const formatLabel = {
        translated: '翻译字幕',
        bilingual: '双语字幕',
        original: '原文字幕',
      }[format] || '字幕';
      if (summary.severe > 0) {
        return `${formatLabel}仍有 ${summary.severe} 个严重问题、${summary.warning} 个提醒。${issueText}。是否继续导出？`;
      }
      return `${formatLabel}仍有 ${summary.warning} 个质量提醒。${issueText}。是否继续导出？`;
    },

    renumberSubtitles() {
      this.subtitles.forEach((s, i) => { s.index = i + 1; });
    },

    subtitleSnapshot() {
      return this.subtitles.map((s) => ({ ...s }));
    },

    restoreSubtitles(snapshot) {
      this.subtitles = snapshot.map((s) => ({ ...s }));
    },

    isValidSubtitleIndex(idx) {
      return Number.isInteger(idx) && idx >= 0 && idx < this.subtitles.length;
    },

    async persistSubtitles() {
      this.renumberSubtitles();
      await this.api(`/api/projects/${this.currentProject.id}/subtitles`, 'PUT', { blocks: this.subtitles });
    },

    async addSubtitleAfter(idx) {
      if (this.subtitleActionsDisabled()) return;
      if (!this.isValidSubtitleIndex(idx)) return;
      const actionKey = this.subtitleActionKey('add', idx);
      this.subtitleActionPending = actionKey;
      const before = this.subtitleSnapshot();
      const current = this.subtitles[idx] || {};
      const next = this.subtitles[idx + 1];
      const start = current.end || current.start || '00:00:00,000';
      const startMs = this.parseSrtTime(start);
      const nextStartMs = next?.start ? this.parseSrtTime(next.start) : 0;
      const end = nextStartMs > startMs + 500
        ? next.start
        : this.formatSrtTime(startMs + 2000);
      this.subtitles.splice(idx + 1, 0, {
        index: idx + 2,
        start,
        end,
        text: '',
        translation: '',
        filtered: false,
        filter_reason: '',
      });
      try {
        await this.persistSubtitles();
        this.toast('已新增字幕行');
      } catch(e) {
        this.restoreSubtitles(before);
        this.toast('保存失败', 'error');
      } finally {
        if (this.subtitleActionPending === actionKey) this.subtitleActionPending = '';
      }
    },

    async deleteSubtitle(idx) {
      if (this.subtitleActionsDisabled()) return;
      if (!this.isValidSubtitleIndex(idx)) return;
      const actionKey = this.subtitleActionKey('delete', idx);
      this.subtitleActionPending = actionKey;
      const confirmed = await this.askConfirm({
        title: '删除字幕行？',
        message: `确定删除第 ${idx + 1} 行字幕？`,
        confirmText: '删除',
        intent: 'danger',
      });
      if (!confirmed) {
        if (this.subtitleActionPending === actionKey) this.subtitleActionPending = '';
        return;
      }
      const before = this.subtitleSnapshot();
      this.subtitles.splice(idx, 1);
      try {
        await this.persistSubtitles();
        this.toast('已删除字幕行');
      } catch(e) {
        this.restoreSubtitles(before);
        this.toast('保存失败', 'error');
      } finally {
        if (this.subtitleActionPending === actionKey) this.subtitleActionPending = '';
      }
    },

    async splitSubtitle(idx) {
      if (this.subtitleActionsDisabled()) return;
      if (!this.isValidSubtitleIndex(idx)) return;
      const item = this.subtitles[idx];
      const startMs = this.parseSrtTime(item.start);
      const endMs = this.parseSrtTime(item.end);
      if (endMs <= startMs + 500) {
        this.toast('这一行字幕太短，无法分割', 'error');
        return;
      }
      const actionKey = this.subtitleActionKey('split', idx);
      this.subtitleActionPending = actionKey;
      const before = this.subtitleSnapshot();
      const mid = this.formatSrtTime(Math.floor((startMs + endMs) / 2));
      const oldEnd = item.end;
      const [textA, textB] = this.splitTextAtMiddle(item.text);
      const [transA, transB] = this.splitTextAtMiddle(item.translation);
      item.end = mid;
      item.text = textA || item.text || '';
      item.translation = transA || item.translation || '';
      this.subtitles.splice(idx + 1, 0, {
        ...item,
        index: idx + 2,
        start: mid,
        end: oldEnd,
        text: textB,
        translation: transB,
      });
      try {
        await this.persistSubtitles();
        this.toast('已分割字幕行');
      } catch(e) {
        this.restoreSubtitles(before);
        this.toast('保存失败', 'error');
      } finally {
        if (this.subtitleActionPending === actionKey) this.subtitleActionPending = '';
      }
    },

    async mergeSubtitleWithNext(idx) {
      if (this.subtitleActionsDisabled()) return;
      if (!this.isValidSubtitleIndex(idx) || idx >= this.subtitles.length - 1) return;
      const item = this.subtitles[idx];
      const next = this.subtitles[idx + 1];
      const startMs = this.parseSrtTime(item.start);
      const nextEndMs = this.parseSrtTime(next?.end);
      if (nextEndMs <= startMs) {
        this.toast('相邻字幕时间无效，无法合并', 'error');
        return;
      }
      const actionKey = this.subtitleActionKey('merge', idx);
      this.subtitleActionPending = actionKey;
      const before = this.subtitleSnapshot();
      item.end = next.end || item.end;
      item.text = this.joinSubtitleText(item.text, next.text);
      item.translation = this.joinSubtitleText(item.translation, next.translation);
      item.filtered = !!item.filtered && !!next.filtered;
      item.filter_reason = this.joinSubtitleText(item.filter_reason, next.filter_reason);
      this.subtitles.splice(idx + 1, 1);
      try {
        await this.persistSubtitles();
        this.toast('已合并字幕行');
      } catch(e) {
        this.restoreSubtitles(before);
        this.toast('保存失败', 'error');
      } finally {
        if (this.subtitleActionPending === actionKey) this.subtitleActionPending = '';
      }
    },

    async exportSrt(format) {
      if (!this.canExportSrt(format)) {
        this.toast(this.exportUnavailableMessage(format), 'error');
        return;
      }
      const warningMessage = this.subtitleExportWarningMessage(format);
      if (this.hasSevereSubtitleIssues() && warningMessage) {
        const confirmed = await this.askConfirm({
          title: '继续导出字幕？',
          message: warningMessage,
          confirmText: '继续导出',
          intent: 'warning',
        });
        if (!confirmed) return;
      }
      const actionKey = this.exportActionKey(format);
      this.projectActionPending = actionKey;
      try {
        const data = await this.api(`/api/projects/${this.currentProject.id}/export?format=${format}`, 'POST');
        const blob = new Blob([data.content], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = data.filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 0);
        this.toast('导出成功');
      } catch(e) { this.toast(e.message, 'error'); }
      finally {
        if (this.projectActionPending === actionKey) this.projectActionPending = '';
      }
    },

    async saveSettings() {
      if (this.settingsSaving) return;
      this.settingsSaving = true;
      try {
        await this.api('/api/settings', 'POST', this.settings);
        this.applyWorkflowDefaultsFromSettings();
        this.toast('设置已保存');
        await this.refreshSystemCheck({ force: true });
        if (this.settingsUsesClaudeCli()) {
          await this.checkClaudeCliStatus();
        }
        if (this.settingsUsesCodexCli()) {
          await this.checkCodexCliStatus();
        }
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.settingsSaving = false;
      }
    },

    openProviderPage(provider) {
      const url = this.providerKeyUrls[provider];
      if (!url) {
        this.toast('未知服务商', 'error');
        return;
      }
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_url) {
        window.pywebview.api.open_url(url);
      } else {
        window.open(url, '_blank', 'noopener,noreferrer');
      }
      this.toast('已在浏览器中打开，登录后复制密钥回来粘贴', 'success');
    },

    async pasteKey(provider) {
      try {
        const text = await navigator.clipboard.readText();
        if (text && text.trim().length > 10) {
          if (provider === 'tmdb') {
            if (!this.isPlainObject(this.settings.tmdb)) this.settings.tmdb = {};
            this.settings.tmdb.api_key = text.trim();
          } else {
            if (!this.isPlainObject(this.settings.api_keys)) this.settings.api_keys = {};
            this.settings.api_keys[provider] = text.trim();
          }
          this.toast('已粘贴密钥');
        } else {
          this.toast('剪贴板内容为空或太短', 'error');
        }
      } catch(e) {
        this.toast('无法读取剪贴板，请手动粘贴 (Cmd+V)', 'error');
      }
    },

    setModelOptions(targetKey, models) {
      const safeModels = Array.isArray(models)
        ? models.filter(m => typeof m === 'string' && m.trim()).map(m => m.trim())
        : [];
      if (targetKey === 'primary') this.primaryModels = safeModels;
      else this.polishModels = safeModels;
      this.ensureSelectedModel(targetKey, safeModels);
    },

    ensureSelectedModel(targetKey, models) {
      if (!this.isPlainObject(this.settings.translation)) this.settings.translation = {};
      const field = targetKey === 'primary' ? 'primary_model' : 'polish_model';
      const current = typeof this.settings.translation[field] === 'string'
        ? this.settings.translation[field].trim()
        : '';
      if (targetKey === 'polish' && models.length === 0) {
        this.settings.translation.polish_model = '';
        return;
      }
      if (models.length > 0 && !models.includes(current)) {
        this.settings.translation[field] = models[0];
      }
    },

    async fetchModels(provider, target) {
      const targetKey = target === 'primary' ? 'primary' : 'polish';
      const requestId = ++this.modelRequestSeq[targetKey];
      this.modelErrors[targetKey] = '';
      if (!provider) {
        if (targetKey === 'polish') this.setModelOptions(targetKey, []);
        this.modelLoading[targetKey] = false;
        return;
      }
      // Use cache if available
      if (this.modelCache[provider]) {
        this.setModelOptions(targetKey, this.modelCache[provider]);
        this.modelLoading[targetKey] = false;
        return;
      }
      // Static fallback (used while loading or if no key)
      const fallback = {
        openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'o3-mini', 'o4-mini'],
        deepseek: ['deepseek-chat', 'deepseek-reasoner'],
        gemini: ['gemini-3.1-pro-preview', 'gemini-3.1-flash-lite-preview', 'gemini-3-pro-preview', 'gemini-3-flash-preview', 'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.0-flash', 'gemini-2.0-flash-lite'],
        claude_cli: ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5'],
        codex_cli: ['gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.3-codex-spark'],
      };
      const fb = fallback[provider] || [];
      this.setModelOptions(targetKey, fb);
      if (provider === 'claude_cli' || provider === 'codex_cli') {
        this.modelLoading[targetKey] = false;
        return;
      }
      // Try fetching from API
      const apiKeys = this.isPlainObject(this.settings.api_keys) ? this.settings.api_keys : {};
      if (!apiKeys[provider]) {
        this.modelLoading[targetKey] = false;
        return;
      }
      this.modelLoading[targetKey] = true;
      try {
        const r = await this.api(`/api/models/${provider}`);
        if (this.modelRequestSeq[targetKey] !== requestId) return;
        const models = Array.isArray(r.models)
          ? r.models.filter(m => typeof m === 'string' && m.trim()).map(m => m.trim())
          : [];
        if (models.length > 0) {
          this.modelCache[provider] = models;
          this.setModelOptions(targetKey, models);
        }
      } catch(e) {
        console.warn('fetchModels failed:', e);
        if (this.modelRequestSeq[targetKey] === requestId) {
          this.modelErrors[targetKey] = `模型列表加载失败：${e.message || '请稍后重试'}`;
        }
      }
      if (this.modelRequestSeq[targetKey] === requestId) this.modelLoading[targetKey] = false;
    },

    async testKey(provider) {
      if (this.keyStatus[provider] === 'testing') return;
      this.keyStatus[provider] = 'testing';
      try {
        const testModel = {
          openai: 'gpt-4o-mini',
          deepseek: 'deepseek-chat',
          gemini: 'gemini-2.5-flash',
          claude_cli: this.settings.providers?.claude_cli?.model || 'claude-opus-4-7',
          codex_cli: this.settings.providers?.codex_cli?.model || 'gpt-5.5',
        };
        const apiKeys = this.isPlainObject(this.settings.api_keys) ? this.settings.api_keys : {};
        const r = await this.api('/api/settings/test-key', 'POST', {
          provider, api_key: apiKeys[provider] || '', model: testModel[provider]
        });
        this.keyStatus[provider] = r.success ? 'ok' : 'fail';
        this.toast(r.message, r.success ? 'success' : 'error');
        // On success, refresh model cache for this provider
        if (r.success) {
          delete this.modelCache[provider];
          if (this.settings.translation.primary_provider === provider) this.fetchModels(provider, 'primary');
          if (this.settings.translation.polish_provider === provider) this.fetchModels(provider, 'polish');
        }
      } catch(e) { this.keyStatus[provider] = 'fail'; this.toast(e.message, 'error'); }
    },

    async testTmdbKey() {
      if (this.keyStatus.tmdb === 'testing') return;
      const tmdb = this.isPlainObject(this.settings.tmdb) ? this.settings.tmdb : {};
      const apiKey = typeof tmdb.api_key === 'string' ? tmdb.api_key.trim() : '';
      const language = typeof tmdb.language === 'string' && tmdb.language.trim() ? tmdb.language.trim() : 'zh-CN';
      if (!apiKey) {
        this.keyStatus.tmdb = 'fail';
        this.toast('请先填写 TMDB API 密钥', 'error');
        return;
      }
      this.keyStatus.tmdb = 'testing';
      try {
        const r = await this.api('/api/settings/test-tmdb-key', 'POST', {
          api_key: apiKey,
          language,
        });
        this.keyStatus.tmdb = r.success ? 'ok' : 'fail';
        this.toast(r.message, r.success ? 'success' : 'error');
      } catch(e) {
        this.keyStatus.tmdb = 'fail';
        this.toast(e.message, 'error');
      }
    },

    // ===== Trailer wizard methods =====
    async searchTrailers() {
      this.trailerError = null;
      const q = this.trailerSearchQuery.trim();
      if (!q) return;
      const mode = this.trailerSearchMode;
      const requestId = ++this.trailerSearchRequestSeq;
      const isSameSearchRequestOwner = () => this.trailerSearchRequestSeq === requestId;
      const isCurrentSearchRequest = () => (
        isSameSearchRequestOwner()
        && this.trailerSearchMode === mode
        && this.trailerSearchQuery.trim() === q
      );
      this.trailerSearchResults = [];
      if (mode === 'tmdb_id' && !/^\d+$/.test(q)) {
        this.trailerError = 'TMDB ID 必须是数字';
        this.trailerLoading = false;
        return;
      }
      this.trailerLoading = true;
      try {
        let r;
        if (mode === 'tmdb_id') {
          r = await fetch(`/api/trailer/resolve/${encodeURIComponent(q)}`);
        } else {
          r = await fetch('/api/trailer/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query: q}),
          });
        }
        if (!isCurrentSearchRequest()) return;
        if (!r.ok) {
          this.trailerError = await this.apiErrorMessage(r, `搜索失败 (${r.status})`);
          return;
        }
        const data = await r.json();
        if (!isCurrentSearchRequest()) return;
        const results = Array.isArray(data.results) ? data.results : [];
        this.trailerSearchResults = results.map(x => this.normalizeTrailerResult(x)).filter(Boolean);
        this.trailerStep = 2;
      } catch (e) {
        if (isCurrentSearchRequest()) {
          this.trailerError = `网络错误: ${e.message}`;
        }
      } finally {
        if (isSameSearchRequestOwner()) this.trailerLoading = false;
      }
    },

    normalizeTrailerResult(item) {
      if (!this.isPlainObject(item) || !['tv', 'movie'].includes(item.media_type)) return null;
      const id = Number(item.id);
      if (!Number.isInteger(id) || id < 1) return null;
      const str = (value) => typeof value === 'string' ? value : '';
      const seasonCount = Number(item.number_of_seasons);
      return {
        ...item,
        id,
        name: str(item.name),
        title: str(item.title),
        original_name: str(item.original_name),
        original_title: str(item.original_title),
        overview: str(item.overview),
        poster_path: str(item.poster_path) || null,
        original_language: str(item.original_language),
        number_of_seasons: Number.isFinite(seasonCount) && seasonCount > 0 ? seasonCount : 0,
        seasons: Array.isArray(item.seasons) ? item.seasons : [],
      };
    },

    selectShow(show) {
      this.trailerError = null;
      show = this.normalizeTrailerResult(show);
      if (!show) {
        this.trailerError = '无效的 TMDB 条目';
        return;
      }
      this.trailerVideoRequestSeq += 1;
      this.trailerSelectedShow = show;
      this.trailerSelectedSeasons = [];
      this.trailerVideos = [];
      this.trailerSelectedVideos = [];
      if (show.media_type === 'tv') {
        const rawSeasonCount = Number(show.number_of_seasons);
        const fallbackCount = Array.isArray(show.seasons) ? show.seasons.length : 0;
        const baseCount = Number.isFinite(rawSeasonCount) && rawSeasonCount > 0
          ? rawSeasonCount
          : fallbackCount || 10;
        const n = Math.max(1, Math.min(100, Math.floor(baseCount)));
        this.trailerSeasons = Array.from({length: n}, (_, i) => i + 1);
        this.trailerStep = 3;
      } else {
        this.trailerStep = 4;
        this.fetchTrailerVideos();
      }
    },

    normalizedTrailerSelectedSeasons() {
      if (!Array.isArray(this.trailerSelectedSeasons)) return [];
      const allowed = new Set(
        (Array.isArray(this.trailerSeasons) ? this.trailerSeasons : [])
          .map((season) => Number(season))
          .filter((season) => Number.isInteger(season) && season > 0)
      );
      const seen = new Set();
      const normalized = [];
      for (const value of this.trailerSelectedSeasons) {
        if (typeof value === 'boolean') continue;
        const season = Number(value);
        if (!Number.isInteger(season) || season < 1) continue;
        if (allowed.size > 0 && !allowed.has(season)) continue;
        if (seen.has(season)) continue;
        seen.add(season);
        normalized.push(season);
      }
      return normalized;
    },

    commitTrailerSelectedSeasons() {
      const normalized = this.normalizedTrailerSelectedSeasons();
      if (JSON.stringify(normalized) !== JSON.stringify(this.trailerSelectedSeasons)) {
        this.trailerSelectedSeasons = normalized;
      }
      return normalized;
    },

    canFetchTrailerVideos() {
      return !!this.trailerSelectedShow && !this.trailerLoading;
    },

    advanceTrailerVideoStep() {
      if (!this.canFetchTrailerVideos()) return;
      this.trailerStep = 4;
      this.fetchTrailerVideos();
    },

    async fetchTrailerVideos() {
      this.trailerError = null;
      this.trailerVideos = [];
      this.trailerSelectedVideos = [];
      const show = this.trailerSelectedShow;
      if (!show) return;
      const selectedSeasons = show.media_type === 'tv'
        ? this.commitTrailerSelectedSeasons()
        : [];
      const requestId = ++this.trailerVideoRequestSeq;
      const requestedSeasons = JSON.stringify(selectedSeasons);
      this.trailerLoading = true;
      const isSameVideoRequestOwner = () => (
        this.trailerVideoRequestSeq === requestId
        && this.trailerSelectedShow === show
      );
      const isCurrentVideoRequest = () => (
        isSameVideoRequestOwner()
        && JSON.stringify(this.normalizedTrailerSelectedSeasons()) === requestedSeasons
      );
      try {
        const urls = [];
        if (show.media_type === 'tv') {
          if (selectedSeasons.length === 0) {
            urls.push(`/api/trailer/videos/${show.id}?type=tv`);
          } else {
            for (const s of selectedSeasons) {
              urls.push(`/api/trailer/videos/${show.id}?type=tv&season=${s}`);
            }
          }
        } else {
          urls.push(`/api/trailer/videos/${show.id}?type=movie`);
        }
        const fetchTrailerVideoList = async (u) => {
          const r = await fetch(u);
          if (!r.ok) {
            throw new Error(await this.apiErrorMessage(r, `HTTP ${r.status}`));
          }
          return r.json();
        };
        const results = await Promise.all(urls.map(fetchTrailerVideoList));
        if (!isCurrentVideoRequest()) return;
        const merged = [];
        const seen = new Set();
        for (const r of results) {
          const videos = Array.isArray(r.videos) ? r.videos : [];
          for (const v of videos) {
            if (!v || typeof v.key !== 'string' || !v.key.trim()) continue;
            const key = v.key.trim();
            if (!seen.has(key)) {
              seen.add(key);
              v.key = key;
              merged.push(v);
            }
          }
        }
        this.trailerVideos = merged;
      } catch (e) {
        if (isCurrentVideoRequest()) this.trailerError = `加载失败: ${e.message}`;
      } finally {
        if (isSameVideoRequestOwner()) this.trailerLoading = false;
      }
    },

    toggleVideo(key) {
      const i = this.trailerSelectedVideos.indexOf(key);
      if (i >= 0) this.trailerSelectedVideos.splice(i, 1);
      else this.trailerSelectedVideos.push(key);
    },

    trailerErrorNeedsSettings() {
      if (!this.trailerError) return false;
      const message = String(this.trailerError);
      return message.includes('TMDB')
        || message.includes('tmdb')
        || message.includes('翻译引擎')
        || message.includes('API 密钥')
        || message.includes('Claude CLI')
        || message.includes('Codex CLI')
        || message.includes('claude')
        || message.includes('codex');
    },

    async startTrailerJobs() {
      if (this.trailerSubmitting) return;
      if (this.trailerSelectedVideos.length === 0) return;
      const show = this.trailerSelectedShow;
      if (!show) return;
      this.trailerError = null;
      this.trailerSubmitting = true;
      const singleSeason = this.trailerSelectedSeasons.length === 1 ? this.trailerSelectedSeasons[0] : null;
      const payload = {
        tmdb_id: show.id,
        tmdb_type: show.media_type,
        season: singleSeason,
        video_keys: this.trailerSelectedVideos,
        original_language: show.original_language || 'en',
        name: show.name || show.title || '未命名',
        target_language: this.targetLang,
      };
      try {
        if (!await this.ensureTranslationReadyForWorkflow()) {
          this.trailerError = `请先完成翻译引擎配置：${this.systemTranslationHint()}`;
          return;
        }
        const r = await fetch('/api/trailer/start', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          this.trailerError = await this.apiErrorMessage(r, `创建失败 (${r.status})`);
          return;
        }
        const data = await r.json();
        const pids = Array.isArray(data.pids) ? data.pids : [];
        this.trailerCreatedCount = pids.length;
        this.trailerStep = 5;
        setTimeout(() => {
          this.showTrailerProjects();
        }, 2000);
      } catch (e) {
        this.trailerError = `网络错误: ${e.message}`;
      } finally {
        this.trailerSubmitting = false;
      }
    },

    resetTrailer() {
      this.trailerSearchRequestSeq += 1;
      this.trailerVideoRequestSeq += 1;
      this.trailerStep = 1;
      this.trailerSearchQuery = '';
      this.trailerSearchResults = [];
      this.trailerSelectedShow = null;
      this.trailerSeasons = [];
      this.trailerSelectedSeasons = [];
      this.trailerVideos = [];
      this.trailerSelectedVideos = [];
      this.trailerError = null;
      this.trailerCreatedCount = 0;
      this.trailerLoading = false;
      this.trailerSubmitting = false;
    },

    // ===== Claude CLI provider status =====
    async checkClaudeCliStatus() {
      if (this.claudeCliChecking) return;
      this.claudeCliChecking = true;
      try {
        this.claudeCliStatus = await this.api('/api/settings/claude-cli/status');
      } catch (e) {
        this.claudeCliStatus = {installed: false, logged_in: false, error: e.message};
      } finally {
        this.claudeCliChecking = false;
      }
    },

    async checkCodexCliStatus() {
      if (this.codexCliChecking) return;
      this.codexCliChecking = true;
      try {
        this.codexCliStatus = await this.api('/api/settings/codex-cli/status');
      } catch (e) {
        this.codexCliStatus = {installed: false, logged_in: false, error: e.message};
      } finally {
        this.codexCliChecking = false;
      }
    },
  };
}
