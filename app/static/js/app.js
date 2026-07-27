/* AI_Sub_Pro Alpine.js app data + methods.
 * Extracted from app/static/index.html inline <script>.
 */
function app() {
  return {
    view: 'home',
    projects: [],
    showArchived: false,
    projectSearch: '',
    projectStatusFilter: 'all',
    projectSortMode: 'recent',
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
      asr: {mode: 'speed', backend: 'auto'},
      translation: {
        quality_mode: 'professional',
        primary_effort: 'auto',
        polish_effort: 'auto',
        use_translation_memory: true,
        use_phrase_library: true,
        qa_auto_repair: true,
      },
      providers: {
        claude_cli: { enabled: true, timeout_sec: 180 },
        codex_cli: { enabled: true, timeout_sec: 180 },
      },
      app_info: { name: 'AI Sub Pro', version: '' },
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
    kbSuggestionLoading: false,
    kbSuggestionError: '',
    kbSuggestionActionPending: '',
    qaReport: null,
    qaReportLoading: false,
    qaReportError: '',
    qaReportRequestSeq: 0,
    translationStrategy: null,
    translationStrategyLoading: false,
    translationStrategyError: '',
    translationStrategyRequestSeq: 0,
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
    taskSettingsPrompt: false,
    taskSettingsTitle: '任务设置',
    taskSettingsMessage: '',
    taskSettingsCanBurn: true,
    taskSettingsWorkflowMode: 'translate_burn',
    taskSettingsAsrLanguage: 'auto',
    taskSettingsTargetLanguage: '简体中文',
    taskSettingsResolve: null,
    homeSourceMode: 'local',
    newVideoPath: '',
    fileImporting: false,
    dropClickSuppressUntil: 0,
    nativeDropFallbackTimer: null,
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
    asrInstallPromptToastKeys: {},
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
    sidebarAutoCollapsed: false,
    sidebarAutoCollapseThreshold: 120,
    sidebarAutoExpandThreshold: 24,
    sidebarAutoCollapseMinWidth: 768,

    // Trailer wizard state
    trailerStep: 1,
    trailerSearchMode: 'title',          // 'title' | 'tmdb_id'
    trailerSearchQuery: '',
    trailerUrlInput: '',
    trailerNameInput: '',
    trailerOriginalLanguage: 'auto',
    trailerSearchResults: [],
    trailerSelectedShow: null,
    trailerSeasons: [],
    trailerSelectedSeasons: [],
    trailerVideos: [],
    trailerSelectedVideos: [],
    trailerError: null,
    trailerCreatedCount: 0,
    trailerCreatedProjects: [],
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
      if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
        window.addEventListener('aisubpro:native-file-drop', (e) => this.handleNativeFileDrop(e?.detail?.paths));
      }
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

    normalizeWorkflowMode(value, canBurn = true) {
      if (!canBurn) return 'translate_only';
      return value === 'translate_only' ? 'translate_only' : 'translate_burn';
    },

    taskSettingsResultFromState() {
      const targetLanguage = String(this.taskSettingsTargetLanguage || this.targetLang || '简体中文').trim() || '简体中文';
      const asrLanguage = String(this.taskSettingsAsrLanguage || this.asrLanguage || 'auto').trim() || 'auto';
      return {
        workflow_mode: this.normalizeWorkflowMode(this.taskSettingsWorkflowMode, this.taskSettingsCanBurn),
        asr_language: asrLanguage,
        target_language: targetLanguage,
      };
    },

    openTaskSettings(options = {}) {
      const canBurn = options.canBurn !== false;
      const resultDefaults = {
        workflow_mode: this.normalizeWorkflowMode(options.workflow_mode, canBurn),
        asr_language: String(options.asr_language || this.asrLanguage || 'auto').trim() || 'auto',
        target_language: String(options.target_language || this.targetLang || '简体中文').trim() || '简体中文',
      };
      if (typeof document === 'undefined') {
        return Promise.resolve(resultDefaults);
      }
      if (this.taskSettingsResolve) this.cancelTaskSettings();
      this.taskSettingsTitle = options.title || '任务设置';
      this.taskSettingsMessage = options.message || '';
      this.taskSettingsCanBurn = canBurn;
      this.taskSettingsWorkflowMode = resultDefaults.workflow_mode;
      this.taskSettingsAsrLanguage = resultDefaults.asr_language;
      this.taskSettingsTargetLanguage = resultDefaults.target_language;
      this.taskSettingsPrompt = true;
      return new Promise((resolve) => {
        this.taskSettingsResolve = resolve;
        if (typeof this.$nextTick === 'function') {
          this.$nextTick(() => this.$refs.taskSettingsConfirmButton?.focus?.());
        }
      });
    },

    projectTaskSettingsDefaults(project, canBurn = this.canBurnVideo(project)) {
      const asrLanguage = String(
        project?.asr_language
        || project?.original_language
        || project?.source_language
        || this.asrLanguage
        || 'auto'
      ).trim() || 'auto';
      const targetLanguage = String(project?.target_language || this.targetLang || '简体中文').trim() || '简体中文';
      return {
        workflow_mode: this.normalizeWorkflowMode(project?.workflow_mode, canBurn),
        asr_language: asrLanguage,
        target_language: targetLanguage,
      };
    },

    openProjectTaskSettings(project, options = {}) {
      const canBurn = options.canBurn !== undefined ? !!options.canBurn : this.canBurnVideo(project);
      const defaults = this.projectTaskSettingsDefaults(project, canBurn);
      return this.openTaskSettings({
        title: options.title || '任务设置',
        message: options.message || '选择输出方式和本次任务语言。仅翻译会生成字幕文件，不烧录到视频。',
        canBurn,
        ...defaults,
      });
    },

    applyTaskSettingsToCurrentProject(settings, project = this.currentProject) {
      const canBurn = this.canBurnVideo(project);
      const asrLanguage = String(settings?.asr_language || this.asrLanguage || 'auto').trim() || 'auto';
      const targetLanguage = String(settings?.target_language || this.targetLang || '简体中文').trim() || '简体中文';
      const workflowMode = this.normalizeWorkflowMode(settings?.workflow_mode, canBurn);
      this.asrLanguage = asrLanguage;
      this.targetLang = targetLanguage;
      if (this.isPlainObject(project)) {
        project.asr_language = asrLanguage;
        project.target_language = targetLanguage;
        project.workflow_mode = workflowMode;
      }
      return {
        language: asrLanguage,
        target_language: targetLanguage,
        workflow_mode: workflowMode,
      };
    },

    cancelTaskSettings() {
      const resolve = this.taskSettingsResolve;
      this.taskSettingsPrompt = false;
      this.taskSettingsResolve = null;
      if (resolve) resolve(null);
    },

    confirmTaskSettings() {
      const resolve = this.taskSettingsResolve;
      const result = this.taskSettingsResultFromState();
      this.taskSettingsPrompt = false;
      this.taskSettingsResolve = null;
      if (resolve) resolve(result);
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
      this.sidebarAutoCollapsed = false;
      if (nextView === 'projects') await this.loadProjects();
      if (nextView === 'knowledge') this.loadKbProjects();
      if (nextView === 'settings' && this.settingsUsesLocalCli()) {
        await Promise.all([
          this.refreshCliProviderModelCatalog('claude_cli'),
          this.refreshCliProviderModelCatalog('codex_cli'),
          this.checkClaudeCliStatus(),
          this.checkCodexCliStatus(),
        ]);
      }
      return true;
    },

    shouldAutoCollapseSidebar() {
      const minWidth = Number(this.sidebarAutoCollapseMinWidth) || 0;
      const width = typeof window !== 'undefined' && Number(window.innerWidth)
        ? Number(window.innerWidth)
        : minWidth;
      return width >= minWidth;
    },

    handleAppMainScroll(event) {
      const scrollTop = Number(event?.target?.scrollTop) || 0;
      if (!this.shouldAutoCollapseSidebar()) {
        this.sidebarAutoCollapsed = false;
        return;
      }
      if (scrollTop >= this.sidebarAutoCollapseThreshold) {
        this.sidebarAutoCollapsed = true;
      } else if (scrollTop <= this.sidebarAutoExpandThreshold) {
        this.sidebarAutoCollapsed = false;
      }
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
      return { created:'新建', processing:'处理中', asr_done:'识别完成', translated:'已翻译', completed:'已完成', cancelled:'已取消', error:'错误' }[s] || s;
    },

    statusColor(p) {
      // Returns {bg, text, hex} for badge + progress bar
      const stage = p.pipeline_stage;
      const status = p.status;
      const qualityStatus = typeof p.translation_quality_status === 'string'
        ? p.translation_quality_status.trim()
        : '';
      if (status === 'cancelled') return {bg: '#f1f5f9', text: '#475569', hex: '#64748b'};
      if (status === 'error') return {bg: '#fee2e2', text: '#991b1b', hex: '#dc2626'};
      if (status === 'completed') return {bg: '#dcfce7', text: '#166534', hex: '#16a34a'};
      if (stage === 'download') return {bg: '#ffedd5', text: '#9a3412', hex: '#f97316'};
      if (stage === 'asr' || status === 'asr_done') return {bg: '#f3e8ff', text: '#6b21a8', hex: '#a855f7'};
      if (stage === 'burn') return {bg: '#dcfce7', text: '#166534', hex: '#22c55e'};
      if (status === 'translated' && !stage && ['needs_review', 'failed'].includes(qualityStatus)) return {bg: '#fef3c7', text: '#92400e', hex: '#d97706'};
      if (stage === 'translate' || status === 'translated') return {bg: '#dbeafe', text: '#1e40af', hex: '#3b82f6'};
      // created / processing / default
      return {bg: '#ccfbf1', text: '#115e59', hex: '#0f766e'};
    },

    isProjectBusy(project) {
      return !!project && (project.status === 'processing' || !!project.pipeline_stage);
    },

    projectActionsDisabled(project) {
      return this.isProjectBusy(project) || !!this.projectActionPending || !!this.workflowActionPending;
    },

    projectSourceType(project) {
      return String(project?.source_type || 'upload').trim() || 'upload';
    },

    isSubtitleOnlyProject(project) {
      return this.projectSourceType(project) === 'subtitle';
    },

    isAudioOnlyProject(project) {
      return this.projectSourceType(project) === 'audio';
    },

    canRunAsr(project) {
      return !!project && !this.isSubtitleOnlyProject(project);
    },

    canTranslateProject(project) {
      return !!project;
    },

    canBurnVideo(project) {
      return !!project && !this.isAudioOnlyProject(project) && !this.isSubtitleOnlyProject(project);
    },

    projectPrimaryActionLabel(project) {
      if (this.projectActionPending === 'start-full') return '启动中...';
      if (project?.status === 'error') return '重试';
      if (this.isSubtitleOnlyProject(project)) return '翻译字幕';
      if (this.isAudioOnlyProject(project)) return '转写并翻译';
      return '一键处理';
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

    exportActionKey(format, container = 'srt') {
      const normalizedContainer = container === 'vtt' ? 'vtt' : 'srt';
      const suffix = normalizedContainer === 'srt' ? '' : `:${normalizedContainer}`;
      return `export:${format || ''}${suffix}`;
    },

    isExportingSrt(format) {
      return this.isExportingSubtitle(format, 'srt');
    },

    isExportingSubtitle(format, container = 'srt') {
      return this.projectActionPending === this.exportActionKey(format, container);
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

    canExportSubtitle(format) {
      return this.canExportSrt(format);
    },

    exportSrtLabel(format) {
      return this.exportSubtitleLabel(format, 'srt');
    },

    exportSubtitleLabel(format, container = 'srt') {
      const normalizedContainer = container === 'vtt' ? 'vtt' : 'srt';
      const labels = {
        translated: '导出翻译字幕',
        bilingual: '导出双语字幕',
        original: '导出原文字幕',
      };
      const base = labels[format] || '导出字幕';
      const label = normalizedContainer === 'vtt' ? `${base.replace('字幕', '').trim()} VTT` : base;
      return this.isExportingSubtitle(format, normalizedContainer) ? '导出中...' : label;
    },

    exportUnavailableMessage(format) {
      if (!this.currentProject) return '请先打开项目';
      if (this.isProjectBusy(this.currentProject)) return '项目处理中，完成后再导出';
      if (this.projectActionPending) return '当前操作未完成，请稍后再试';
      if (format === 'original') return '还没有可导出的原文字幕';
      if (format === 'translated' || format === 'bilingual') return '还没有可导出的翻译字幕';
      return '不支持的导出格式';
    },

    safeDownloadFilename(value, fallback = 'download') {
      const raw = String(value || fallback).split(/[\\/]+/).pop() || fallback;
      const cleaned = raw
        .replace(/^\.+/, '')
        .replace(/[<>:"/\\|?*\x00-\x1F]+/g, '_')
        .trim();
      return cleaned || fallback;
    },

    nativeSaveApi() {
      return (typeof window !== 'undefined' && window.pywebview?.api)
        ? window.pywebview.api
        : null;
    },

    canSaveVideo() {
      if (!this.currentProject || this.projectActionsDisabled(this.currentProject)) return false;
      if (!this.canBurnVideo(this.currentProject)) return false;
      return !!String(this.currentProject.output_video || '').trim()
        && this.currentProject.status === 'completed';
    },

    canRevealProjectLocation(project) {
      if (!project || !String(project.id || '').trim()) return false;
      return !!(
        String(project.output_video || '').trim()
        || String(project.video_path || '').trim()
        || project.source_type === 'trailer'
      );
    },

    isSavingVideo() {
      return this.projectActionPending === 'save-video';
    },

    saveVideoLabel() {
      return this.isSavingVideo() ? '保存中...' : '保存视频';
    },

    saveVideoUnavailableMessage() {
      if (!this.currentProject) return '请先打开项目';
      if (!this.canBurnVideo(this.currentProject)) return '当前项目没有视频烧录输出';
      if (this.isProjectBusy(this.currentProject)) return '项目处理中，完成后再保存';
      if (this.projectActionPending) return '当前操作未完成，请稍后再试';
      return '视频尚未完成，暂时不能保存';
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
      const qualityStatus = typeof p.translation_quality_status === 'string'
        ? p.translation_quality_status.trim()
        : '';
      if (status === 'cancelled') return '已取消';
      if (status === 'error') return '失败';
      if (status === 'completed') return '已完成';
      if (stage === 'download') return '下载中';
      if (stage === 'asr') return '识别中';
      if (status === 'asr_done' && !stage) return '识别完成';
      if (stage === 'translate') return '翻译中';
      if (status === 'translated' && !stage && ['needs_review', 'failed'].includes(qualityStatus)) return '待自动重试';
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

    filteredProjects() {
      const query = String(this.projectSearch || '').trim().toLowerCase();
      const statusFilter = this.projectStatusFilter || 'all';
      const statusMatches = (project) => {
        if (statusFilter === 'all') return true;
        if (statusFilter === 'running') return this.isProjectBusy(project);
        if (statusFilter === 'completed') return project.status === 'completed' || !!project.output_video;
        if (statusFilter === 'error') return project.status === 'error';
        if (statusFilter === 'translated') return project.status === 'translated';
        return project.status === statusFilter;
      };
      const queryMatches = (project) => {
        if (!query) return true;
        return [project.name, project.id, project.status, project.error, project.progress_msg]
          .some((value) => String(value || '').toLowerCase().includes(query));
      };
      const sorted = (Array.isArray(this.projects) ? this.projects : [])
        .filter((project) => this.isPlainObject(project))
        .filter((project) => this.showArchived || !project.archived)
        .filter(statusMatches)
        .filter(queryMatches)
        .slice();
      if (this.projectSortMode === 'name') {
        sorted.sort((a, b) => String(a.name || a.id || '').localeCompare(String(b.name || b.id || ''), 'zh-CN'));
      } else if (this.projectSortMode === 'status') {
        sorted.sort((a, b) => this.statusLabel(a).localeCompare(this.statusLabel(b), 'zh-CN')
          || this.projectSortTimestamp(b) - this.projectSortTimestamp(a));
      } else {
        sorted.sort((a, b) => this.projectSortTimestamp(b) - this.projectSortTimestamp(a));
      }
      return sorted;
    },

    recentTaskProjects(limit = 5) {
      const priority = (project) => {
        if (this.isProjectBusy(project)) return 0;
        if (project.status === 'error') return 1;
        return 2;
      };
      return (Array.isArray(this.projects) ? this.projects : [])
        .filter((project) => this.isPlainObject(project) && !project.archived)
        .filter((project) => this.isProjectBusy(project) || project.status === 'error' || project.status === 'cancelled' || project.status === 'translated' || project.status === 'completed' || project.output_video)
        .slice()
        .sort((a, b) => priority(a) - priority(b) || this.projectSortTimestamp(b) - this.projectSortTimestamp(a))
        .slice(0, limit);
    },

    redactSecretText(value) {
      return String(value || '')
        .replace(/sk-[A-Za-z0-9_-]+/g, '[redacted]')
        .replace(/(api[_ -]?key|token|secret)[=: ]+[A-Za-z0-9._-]+/gi, '$1 [redacted]');
    },

    projectErrorNextAction(projectOrMessage) {
      const raw = this.isPlainObject(projectOrMessage)
        ? (projectOrMessage.error || projectOrMessage.progress_msg || '')
        : projectOrMessage;
      const message = this.redactSecretText(raw);
      const lower = message.toLowerCase();
      if (/api|key|provider|openai|deepseek|gemini|claude|codex/.test(lower)) {
        return '打开设置页检查翻译 provider、登录状态和 API 密钥。';
      }
      if (/ffmpeg|ffprobe|subtitles filter/.test(lower)) {
        return '安装带 subtitles filter 的 ffmpeg 后重试导出或烧录。';
      }
      if (/asr|whisper|model|mlx|faster/.test(lower)) {
        return '检查 ASR 设置、模型缓存和离线依赖后重试识别。';
      }
      if (/network|timeout|connection|dns|http/.test(lower)) {
        return '检查网络连接或代理设置，然后重试当前任务。';
      }
      return message ? `查看工作流日志并重试。错误摘要：${message}` : '查看工作流日志并重试。';
    },

    async api(url, method='GET', body=null) {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch(url, opts);
      if (!r.ok) {
        const error = await this.buildApiError(r);
        throw error;
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

    async buildApiError(response, fallback = '') {
      const errorBody = await response.json().catch(() => ({}));
      const message = this.formatApiErrorDetail(errorBody.detail)
        || fallback
        || response.statusText
        || `HTTP ${response.status}`;
      const error = new Error(message);
      error.status = response.status;
      if (this.isPlainObject(errorBody.detail)) error.detail = errorBody.detail;
      return error;
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
      if (this.isPlainObject(detail)) {
        if (typeof detail.message === 'string' && detail.message.trim()) {
          return detail.message.trim();
        }
        return JSON.stringify(detail);
      }
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
        app_info: mergeSection('app_info'),
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
      const allowedEfforts = ['auto', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'];
      for (const field of ['primary_effort', 'polish_effort']) {
        const effort = typeof normalized.translation[field] === 'string'
          ? normalized.translation[field].trim().toLowerCase()
          : '';
        normalized.translation[field] = allowedEfforts.includes(effort) ? effort : 'auto';
      }
      delete normalized.providers.claude_cli.model;
      delete normalized.providers.codex_cli.model;
      const allowedAsrModes = ['speed', 'accuracy', 'offline'];
      const asrMode = typeof normalized.asr.mode === 'string'
        ? normalized.asr.mode.trim()
        : '';
      normalized.asr.mode = allowedAsrModes.includes(asrMode) ? asrMode : 'speed';
      const allowedAsrBackends = ['auto', 'mlx_whisper', 'faster_whisper', 'openai_whisper'];
      const asrBackend = typeof normalized.asr.backend === 'string'
        ? normalized.asr.backend.trim()
        : '';
      normalized.asr.backend = allowedAsrBackends.includes(asrBackend) ? asrBackend : 'auto';
      const appVersion = typeof normalized.app_info.version === 'string'
        ? normalized.app_info.version.trim()
        : '';
      normalized.app_info.version = appVersion;
      normalized.app_info.name = typeof normalized.app_info.name === 'string' && normalized.app_info.name.trim()
        ? normalized.app_info.name.trim()
        : 'AI Sub Pro';
      return normalized;
    },

    settingsVersionLabel() {
      const version = typeof this.settings?.app_info?.version === 'string'
        ? this.settings.app_info.version.trim()
        : '';
      return version ? `v${version}` : '未知';
    },

    settingsPayload() {
      const payload = JSON.parse(JSON.stringify(this.settings || {}));
      if (payload && typeof payload === 'object') delete payload.app_info;
      if (this.isPlainObject(payload?.providers?.claude_cli)) delete payload.providers.claude_cli.model;
      if (this.isPlainObject(payload?.providers?.codex_cli)) delete payload.providers.codex_cli.model;
      return payload;
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

    videoFileExtensions() {
      return ['.mp4','.mkv','.avi','.mov','.wmv','.flv','.webm','.ts','.m4v'];
    },

    isVideoPath(path) {
      const name = String(path || '').toLowerCase();
      return this.videoFileExtensions().some(ext => name.endsWith(ext));
    },

    isVideoFile(file) {
      return this.isVideoPath(file?.name) || this.isVideoPath(this.localPathForFile(file));
    },

    isDesktopShell() {
      if (typeof window === 'undefined') return false;
      return !!(window.pywebview?.api || window.electronAPI);
    },

    normalizeDroppedPath(raw) {
      let value = String(raw || '').trim();
      if (!value || value.startsWith('#')) return '';
      if (value.startsWith('file://')) {
        value = value.replace(/^file:\/\/(?:localhost)?/i, '');
        const suffixIndex = value.search(/[?#]/);
        if (suffixIndex >= 0) value = value.slice(0, suffixIndex);
        try {
          value = decodeURIComponent(value);
        } catch(e) {
          // Keep the raw path when the drag payload is not valid URI encoding.
        }
      }
      return value.startsWith('/') ? value.trim() : '';
    },

    localPathForFile(file) {
      if (!file || typeof file !== 'object') return '';
      if (typeof file.path === 'string' && file.path.trim()) return file.path.trim();
      const resolver = typeof window !== 'undefined' ? window.electronAPI?.getPathForFile : null;
      if (typeof resolver === 'function') {
        try {
          const path = resolver(file);
          if (typeof path === 'string' && path.trim()) return path.trim();
        } catch(e) {}
      }
      return '';
    },

    droppedLocalPaths(event) {
      const dataTransfer = event?.dataTransfer;
      const rawPaths = [];
      const files = Array.from(dataTransfer?.files || []);
      for (const file of files) {
        const filePath = this.localPathForFile(file);
        if (filePath) rawPaths.push(filePath);
      }
      if (typeof dataTransfer?.getData === 'function') {
        for (const type of ['text/uri-list', 'text/plain']) {
          const payload = dataTransfer.getData(type);
          if (!payload) continue;
          rawPaths.push(...String(payload).split(/\r?\n/));
        }
      }
      const seen = new Set();
      const paths = [];
      for (const rawPath of rawPaths) {
        const path = this.normalizeDroppedPath(rawPath);
        if (!path || seen.has(path)) continue;
        seen.add(path);
        paths.push(path);
      }
      return paths;
    },

    async handleNativeFileDrop(paths) {
      if (this.nativeDropFallbackTimer) {
        clearTimeout(this.nativeDropFallbackTimer);
        this.nativeDropFallbackTimer = null;
      }
      const localPaths = Array.isArray(paths)
        ? paths.map((path) => String(path || '').trim()).filter(Boolean)
        : [];
      if (localPaths.length === 0) return;
      await this.handleDrop({
        preventDefault() {},
        stopPropagation() {},
        dataTransfer: {
          files: localPaths.map((path) => ({
            name: path.split('/').filter(Boolean).pop() || path,
            path,
          })),
          getData(type) {
            if (type !== 'text/uri-list' && type !== 'text/plain') return '';
            return localPaths.map((path) => `file://${encodeURI(path)}`).join('\n');
          },
        },
      });
    },

    scheduleMissingNativeDropPathToast() {
      if (this.nativeDropFallbackTimer) clearTimeout(this.nativeDropFallbackTimer);
      this.nativeDropFallbackTimer = setTimeout(() => {
        this.nativeDropFallbackTimer = null;
        this.toast('拖拽未获得视频本地路径，请点击“选择视频文件”导入，避免复制大视频。', 'error');
      }, 900);
    },

    homeSourceOptions() {
      return [
        {
          mode: 'local',
          label: '本地视频',
          helper: '视频文件',
          strategy: '优先读取内嵌字幕和同名外挂字幕；没有可用字幕时再进入 ASR 听写。',
          capabilities: ['内嵌字幕/外挂字幕优先', '无字幕时 ASR 听写', '完成后可烧录视频'],
          actionLabel: '选择视频文件',
          disabled: false,
        },
        {
          mode: 'batch',
          label: '批量文件夹',
          helper: 'Folder',
          strategy: '扫描文件夹内的视频文件，用一次任务设置批量创建项目并自动启动；默认仅翻译生成字幕，可在弹窗中改为烧录。',
          capabilities: ['递归扫描视频文件', '共用一次任务设置', '自动创建并启动任务'],
          actionLabel: '选择文件夹',
          disabled: false,
        },
        {
          mode: 'network',
          label: '网络视频',
          helper: 'URL',
          strategy: '下载到项目文件夹，优先获取平台原生字幕；没有字幕再进入 ASR 听写。',
          capabilities: ['YouTube 或直接视频地址', '平台字幕优先翻译', '自动识别标题和内容类型'],
          actionLabel: '下载并翻译',
          disabled: false,
        },
        {
          mode: 'subtitle',
          label: '字幕文件',
          helper: 'SRT / VTT / ASS',
          strategy: '直接读取 SRT、VTT、ASS/SSA 时间轴，创建字幕项目后马上翻译；ASS 样式会转为可编辑文本。',
          capabilities: ['无需 ASR', '保留时间轴', '支持 SRT / VTT / ASS / SSA'],
          actionLabel: '选择字幕文件',
          disabled: false,
        },
        {
          mode: 'audio',
          label: '音频文件',
          helper: 'MP3 / WAV / M4A',
          strategy: '上传纯音频后进入 ASR 听写和翻译，完成后可导出 SRT / VTT 字幕；不执行视频烧录。',
          capabilities: ['ASR 听写后翻译', '适合访谈/课程/播客', '可导出 SRT / VTT'],
          actionLabel: '选择音频文件',
          disabled: false,
        },
      ];
    },

    homeSourceOption(mode = this.homeSourceMode) {
      const value = typeof mode === 'string' ? mode.trim() : '';
      return this.homeSourceOptions().find((option) => option.mode === value)
        || this.homeSourceOptions()[0];
    },

    setHomeSourceMode(mode) {
      const option = this.homeSourceOption(mode);
      if (!option) return;
      this.homeSourceMode = option.mode;
      this.trailerError = null;
    },

    homeSourceStrategy() {
      return this.homeSourceOption().strategy || '';
    },

    homeSourceCapabilities(option = this.homeSourceOption()) {
      const resolved = Array.isArray(option?.capabilities)
        ? option
        : this.homeSourceOption(option?.mode || this.homeSourceMode);
      const capabilities = Array.isArray(resolved?.capabilities) ? resolved.capabilities : [];
      return capabilities
        .filter((item) => typeof item === 'string' && item.trim())
        .map((item) => item.trim());
    },

    homeSourceReadiness(option = this.homeSourceOption()) {
      const resolved = this.homeSourceOption(option?.mode || this.homeSourceMode);
      if (!this.sysCheck) {
        return {tone: '', message: '', action: '', actionText: ''};
      }
      if (!this.systemTranslationReady()) {
        return {
          tone: 'error',
          message: `翻译引擎未就绪：${this.systemTranslationHint()}`,
          action: 'settings',
          actionText: '去设置',
        };
      }
      if (resolved.mode === 'network' && this.sysCheck?.network_downloader_ready === false) {
        const hint = typeof this.sysCheck?.network_downloader_hint === 'string' && this.sysCheck.network_downloader_hint.trim()
          ? this.sysCheck.network_downloader_hint.trim()
          : '请安装 yt-dlp 以启用网络视频下载。';
        return {
          tone: 'error',
          message: `网络视频下载器未就绪：${hint}`,
          action: 'settings',
          actionText: '去设置',
        };
      }

      const prompts = this.asrInstallPrompts();
      let asrMessage = '';
      if (prompts.length) {
        const firstPrompt = prompts[0] || {};
        asrMessage = typeof firstPrompt.message === 'string' && firstPrompt.message.trim()
          ? firstPrompt.message.trim()
          : '请先安装或配置 ASR 依赖。';
      } else {
        const rec = this.asrRecommendation();
        if (rec.download_required) {
          const model = typeof rec.model_size === 'string' && rec.model_size.trim()
            ? rec.model_size.trim()
            : '当前模型';
          const hint = typeof rec.download_hint === 'string' && rec.download_hint.trim()
            ? `（${rec.download_hint.trim()}）`
            : '';
          asrMessage = `ASR 模型未下载：${model}${hint}`;
        }
      }
      if (!asrMessage) return {tone: '', message: '', action: '', actionText: ''};
      if (resolved.mode === 'audio') {
        return {
          tone: 'warn',
          message: `音频入口需要 ASR：${asrMessage}`,
          action: 'settings',
          actionText: '去设置',
        };
      }
      if (resolved.mode === 'local' || resolved.mode === 'batch' || resolved.mode === 'network') {
        const prefix = resolved.mode === 'network'
          ? '无平台字幕时需要 ASR'
          : resolved.mode === 'batch'
            ? '文件夹内无字幕视频需要 ASR'
          : '无内嵌/外挂字幕时需要 ASR';
        return {
          tone: 'warn',
          message: `${prefix}：${asrMessage}`,
          action: 'settings',
          actionText: '去设置',
        };
      }
      return {tone: '', message: '', action: '', actionText: ''};
    },

    async handleHomeSourceReadinessAction(readiness) {
      if (readiness?.action === 'settings') {
        await this.setView('settings');
      }
    },

    homeSourceActionLabel() {
      const option = this.homeSourceOption();
      if (option.mode === 'local' || option.mode === 'batch') {
        if (this.fileImporting) return '读取中...';
        if (this.projectCreating) return option.mode === 'batch' ? '批量创建中...' : '创建中...';
      }
      if (option.mode === 'network' && this.trailerSubmitting) return '提交中...';
      if (option.mode === 'subtitle') {
        if (this.fileImporting) return '读取中...';
        if (this.projectCreating) return '创建中...';
      }
      if (option.mode === 'audio') {
        if (this.fileImporting) return '读取中...';
        if (this.projectCreating) return '创建中...';
      }
      return option.actionLabel || '开始';
    },

    homeSourceActionDisabled() {
      const option = this.homeSourceOption();
      if (option.disabled) return true;
      if (option.mode === 'local' || option.mode === 'batch') return this.fileImporting || this.projectCreating;
      if (option.mode === 'network') {
        return !String(this.trailerUrlInput || '').trim() || this.trailerSubmitting;
      }
      if (option.mode === 'subtitle') return this.fileImporting || this.projectCreating;
      if (option.mode === 'audio') return this.fileImporting || this.projectCreating;
      return true;
    },

    async startHomeSourceAction() {
      const option = this.homeSourceOption();
      if (option.disabled) {
        this.toast(`${option.label}即将支持`, 'error');
        return;
      }
      if (option.mode === 'network') {
        await this.startTrailerUrlJob();
        return;
      }
      if (option.mode === 'subtitle') {
        await this.openSubtitleFilePicker();
        return;
      }
      if (option.mode === 'audio') {
        await this.openAudioFilePicker();
        return;
      }
      if (option.mode === 'batch') {
        await this.openFolderPicker();
        return;
      }
      await this.openFilePicker();
    },

    canStartProject() {
      return !!String(this.newVideoPath || '').trim()
        && !this.fileImporting
        && !this.projectCreating;
    },

    homeDropTitle() {
      if (this.fileImporting) return '正在读取文件...';
      if (this.projectCreating) {
        return this.homeSourceMode === 'batch' ? '正在创建批量任务...' : '正在创建项目...';
      }
      return this.homeSourceMode === 'batch' ? '点击选择或拖入视频文件夹' : '点击选择或拖入视频文件';
    },

    homeDropHint() {
      if (this.fileImporting || this.projectCreating) return '请稍候，不要重复提交';
      return this.homeSourceMode === 'batch'
        ? '支持拖入文件夹，也支持一次拖入多个视频文件'
        : '支持 MP4、MKV、AVI、MOV 等格式';
    },

    homeManualPathPlaceholder() {
      return this.homeSourceMode === 'batch'
        ? '或粘贴视频文件夹路径...'
        : '或粘贴视频文件路径...';
    },

    homeManualPathAriaLabel() {
      return this.homeSourceMode === 'batch' ? '视频文件夹路径' : '视频文件路径';
    },

    homeManualSubmitLabel() {
      if (this.fileImporting) return '读取中...';
      if (this.projectCreating) return this.homeSourceMode === 'batch' ? '批量创建中...' : '创建中...';
      return this.homeSourceMode === 'batch' ? '批量开始' : '开始';
    },

    async openPrimaryPicker() {
      if (this.homeSourceMode === 'batch') {
        await this.openFolderPicker();
        return;
      }
      await this.openFilePicker();
    },

    async handleDropZoneClick() {
      if (Date.now() < Number(this.dropClickSuppressUntil || 0)) return;
      await this.openPrimaryPicker();
    },

    async quickStartPrimary() {
      if (this.homeSourceMode === 'batch') {
        await this.quickStartBatch();
        return;
      }
      await this.quickStart();
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

    isSubtitleFile(file) {
      const name = String(file?.name || '').toLowerCase();
      return ['.srt', '.vtt', '.ass', '.ssa'].some((ext) => name.endsWith(ext));
    },

    isAudioFile(file) {
      const name = String(file?.name || '').toLowerCase();
      return ['.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.webm'].some((ext) => name.endsWith(ext));
    },

    async uploadSubtitleFile(file) {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('target_language', this.targetLang || '简体中文');
      if (this.asrLanguage && this.asrLanguage !== 'auto') {
        formData.append('original_language', this.asrLanguage);
      }
      const resp = await fetch('/api/projects/import-subtitle', { method: 'POST', body: formData });
      if (!resp.ok) {
        throw new Error(await this.apiErrorMessage(resp, '字幕导入失败'));
      }
      const data = await resp.json().catch(() => ({}));
      if (!data.id) throw new Error('服务器未返回项目 ID');
      return data;
    },

    async uploadAudioFile(file) {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('target_language', this.targetLang || '简体中文');
      if (this.asrLanguage && this.asrLanguage !== 'auto') {
        formData.append('original_language', this.asrLanguage);
      }
      const resp = await fetch('/api/projects/import-audio', { method: 'POST', body: formData });
      if (!resp.ok) {
        throw new Error(await this.apiErrorMessage(resp, '音频导入失败'));
      }
      const data = await resp.json().catch(() => ({}));
      if (!data.id) throw new Error('服务器未返回项目 ID');
      return data;
    },

    async useSelectedSubtitleFile(file) {
      if (!file) return;
      if (!this.isSubtitleFile(file)) {
        this.toast('请选择 SRT、VTT、ASS 或 SSA 字幕文件', 'error');
        return;
      }
      if (this.fileImporting || this.projectCreating) return;
      this.fileImporting = true;
      this.projectCreating = true;
      try {
        if (!await this.ensureTranslationReadyForWorkflow()) return;
        const p = await this.uploadSubtitleFile(file);
        this.toast('字幕项目已创建，开始翻译...');
        this.clearKbSuggestions();
        this.clearKbUsageTrace();
        this.clearQualityReport();
        this.clearTranslationStrategy();
        this.currentProject = p;
        this.workflowState = null;
        this.workflowStateError = '';
        this.applyWorkflowDefaultsFromProject(p);
        await this.setView('detail');
        this.connectWS(p.id);
        await this.api(`/api/projects/${p.id}/start-translate`, 'POST', { target_language: this.targetLang });
        this.currentProject.status = 'processing';
      } catch(e) {
        this.toast('字幕导入失败: ' + e.message, 'error');
      } finally {
        this.fileImporting = false;
        this.projectCreating = false;
      }
    },

    async useSelectedAudioFile(file) {
      if (!file) return;
      if (!this.isAudioFile(file)) {
        this.toast('请选择音频文件（MP3、WAV、M4A、AAC、FLAC、OGG、OPUS）', 'error');
        return;
      }
      if (this.fileImporting || this.projectCreating) return;
      this.fileImporting = true;
      this.projectCreating = true;
      try {
        if (!await this.ensureTranslationReadyForWorkflow()) return;
        const p = await this.uploadAudioFile(file);
        this.toast('音频项目已创建，开始转写并翻译...');
        this.clearKbSuggestions();
        this.clearKbUsageTrace();
        this.clearQualityReport();
        this.clearTranslationStrategy();
        this.currentProject = p;
        this.workflowState = null;
        this.workflowStateError = '';
        this.applyWorkflowDefaultsFromProject(p);
        await this.setView('detail');
        this.connectWS(p.id);
        await this.api(`/api/projects/${p.id}/start-transcribe-translate`, 'POST', {
          language: this.asrLanguage,
          target_language: this.targetLang,
        });
        this.currentProject.status = 'processing';
      } catch(e) {
        this.toast('音频导入失败: ' + e.message, 'error');
      } finally {
        this.fileImporting = false;
        this.projectCreating = false;
      }
    },

    async useSelectedVideoPath(path) {
      const localPath = String(path || '').trim();
      if (!localPath || !this.isVideoPath(localPath)) {
        this.toast('请拖入视频文件（MP4、MKV、AVI 等）', 'error');
        return;
      }
      if (this.fileImporting || this.projectCreating) return;
      this.fileImporting = true;
      try {
        this.newVideoPath = localPath;
        await this.quickStart({ allowDuringImport: true });
      } catch(e) {
        this.toast('文件读取失败: ' + e.message, 'error');
      } finally {
        this.fileImporting = false;
      }
    },

    async useSelectedVideoFile(file) {
      if (!file) return;
      if (!this.isVideoFile(file)) {
        this.toast('请拖入视频文件（MP4、MKV、AVI 等）', 'error');
        return;
      }
      const localPath = this.localPathForFile(file);
      if (localPath) {
        await this.useSelectedVideoPath(localPath);
        return;
      }
      if (this.isDesktopShell()) {
        this.toast('拖拽未获得视频本地路径，请点击“选择视频文件”导入，避免复制大视频。', 'error');
        return;
      }
      if (this.fileImporting || this.projectCreating) return;
      this.fileImporting = true;
      try {
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
        this.notifyAsrInstallPrompts(result);
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

    asrModelOptions() {
      const fallback = [
        { model_size: 'tiny', label: 'tiny (最快)', download_hint: '~150MB' },
        { model_size: 'base', label: 'base', download_hint: '~300MB' },
        { model_size: 'small', label: 'small', download_hint: '~900MB' },
        { model_size: 'medium', label: 'medium', download_hint: '~1.5GB' },
        { model_size: 'large-v3-turbo', label: 'large-v3-turbo (推荐)', download_hint: '~1.6GB' },
        { model_size: 'large-v3', label: 'large-v3 (最准)', download_hint: '~3GB' },
      ];
      const rawOptions = Array.isArray(this.sysCheck?.asr_model_options)
        ? this.sysCheck.asr_model_options
        : fallback;
      const seen = new Set();
      const options = rawOptions
        .map((option) => {
          const model = typeof option?.model_size === 'string' ? option.model_size.trim() : '';
          if (!model || seen.has(model)) return null;
          seen.add(model);
          const label = typeof option?.label === 'string' && option.label.trim()
            ? option.label.trim()
            : model;
          const downloadHint = typeof option?.download_hint === 'string'
            ? option.download_hint.trim()
            : '';
          const normalized = { model_size: model, label, download_hint: downloadHint };
          if (typeof option?.available === 'boolean') normalized.available = option.available;
          if (typeof option?.source === 'string' && option.source.trim()) {
            normalized.source = option.source.trim();
          }
          if (typeof option?.selected === 'boolean') normalized.selected = option.selected;
          return normalized;
        })
        .filter(Boolean);
      const selected = typeof this.settings?.asr?.model_size === 'string'
        ? this.settings.asr.model_size.trim()
        : '';
      if (selected && !seen.has(selected)) {
        options.push({ model_size: selected, label: selected, download_hint: '' });
      }
      return options.length ? options : fallback;
    },

    asrInstallPrompts() {
      const prompts = Array.isArray(this.sysCheck?.asr_install_prompts)
        ? this.sysCheck.asr_install_prompts
        : [];
      return prompts.filter((prompt) => this.isPlainObject(prompt));
    },

    asrRecommendation() {
      return this.isPlainObject(this.sysCheck?.asr_recommendation)
        ? this.sysCheck.asr_recommendation
        : {};
    },

    asrSetupActionPills() {
      const prompts = this.asrInstallPrompts();
      const rec = this.asrRecommendation();
      const pills = [];
      if (prompts.length) {
        pills.push({ label: '缺少 ASR 依赖', tone: 'error' });
      }
      if (rec.download_required) {
        pills.push({ label: '需下载模型', tone: 'warn' });
      }
      if (!pills.length && rec.ready === true) {
        pills.push({ label: 'ASR 就绪', tone: 'success' });
      } else if (!prompts.length && rec.ready === false) {
        pills.push({ label: 'ASR 未就绪', tone: 'warn' });
      }
      return pills;
    },

    asrSetupPillClass(pill) {
      const tone = typeof pill?.tone === 'string' ? pill.tone : '';
      if (tone === 'success') return 'asr-setup-pill--success';
      if (tone === 'error') return 'asr-setup-pill--error';
      return 'asr-setup-pill--warn';
    },

    selectedAsrModelSyncText() {
      const selected = typeof this.settings?.asr?.model_size === 'string'
        ? this.settings.asr.model_size.trim()
        : '';
      if (!selected) return '';
      const option = this.asrModelOptions().find((item) => item.model_size === selected);
      if (!option) return '';
      const source = typeof option.source === 'string' && option.source.trim()
        ? option.source.trim()
        : '';
      if (option.available === true) {
        return source ? `模型已同步：${source}` : '模型已同步';
      }
      if (option.available === false) {
        return option.download_hint ? `模型未下载：${option.download_hint}` : '模型未下载';
      }
      return option.download_hint ? `模型下载提示：${option.download_hint}` : '';
    },

    canApplyAsrRecommendation() {
      const rec = this.asrRecommendation();
      const allowedModes = ['speed', 'accuracy', 'offline'];
      const allowedBackends = ['auto', 'mlx_whisper', 'faster_whisper', 'openai_whisper'];
      const mode = typeof rec.mode === 'string' ? rec.mode.trim() : '';
      const backend = typeof rec.backend === 'string' ? rec.backend.trim() : '';
      const model = typeof rec.model_size === 'string' ? rec.model_size.trim() : '';
      return allowedModes.includes(mode) || allowedBackends.includes(backend) || !!model;
    },

    applyAsrRecommendation() {
      if (!this.canApplyAsrRecommendation()) {
        this.toast('暂无可应用的 ASR 推荐', 'error');
        return;
      }
      const rec = this.asrRecommendation();
      const allowedModes = ['speed', 'accuracy', 'offline'];
      const allowedBackends = ['auto', 'mlx_whisper', 'faster_whisper', 'openai_whisper'];
      const mode = typeof rec.mode === 'string' ? rec.mode.trim() : '';
      const backend = typeof rec.backend === 'string' ? rec.backend.trim() : '';
      const model = typeof rec.model_size === 'string' ? rec.model_size.trim() : '';
      if (!this.isPlainObject(this.settings.asr)) this.settings.asr = {};
      if (allowedModes.includes(mode)) this.settings.asr.mode = mode;
      if (allowedBackends.includes(backend)) this.settings.asr.backend = backend;
      if (model) this.settings.asr.model_size = model;
      this.toast('已应用推荐 ASR 设置，保存设置后生效', 'success');
    },

    async copyAsrInstallCommand(prompt) {
      const command = typeof prompt?.install_command === 'string'
        ? prompt.install_command.trim()
        : '';
      if (!command) {
        this.toast('没有可复制的 ASR 安装命令', 'error');
        return;
      }
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
          throw new Error('clipboard unavailable');
        }
        await navigator.clipboard.writeText(command);
        this.toast('已复制 ASR 安装命令', 'success');
      } catch (e) {
        this.toast('复制 ASR 安装命令失败，请手动复制', 'error');
      }
    },

    notifyAsrInstallPrompts(result) {
      const prompts = Array.isArray(result?.asr_install_prompts)
        ? result.asr_install_prompts
        : [];
      prompts.forEach((prompt) => {
        if (!this.isPlainObject(prompt)) return;
        const severity = typeof prompt.severity === 'string' ? prompt.severity.trim() : '';
        if (severity !== 'warning' && severity !== 'error') return;
        const message = typeof prompt.message === 'string' ? prompt.message.trim() : '';
        if (!message) return;
        const key = typeof prompt.id === 'string' && prompt.id.trim()
          ? prompt.id.trim()
          : message;
        if (this.asrInstallPromptToastKeys[key]) return;
        this.asrInstallPromptToastKeys[key] = true;
        this.toast(message, 'error');
      });
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

    networkDownloaderStatus() {
      return this.isPlainObject(this.sysCheck) ? this.sysCheck : {};
    },

    networkDownloaderReady() {
      return this.networkDownloaderStatus().network_downloader_ready === true;
    },

    networkDownloaderNeedsInstall() {
      return this.networkDownloaderStatus().network_downloader_ready === false;
    },

    networkDownloaderStatusTitle() {
      if (this.networkDownloaderReady()) return '网络视频下载器可用';
      if (this.networkDownloaderNeedsInstall()) return '网络视频下载器需要安装';
      return '网络视频下载器状态待检查';
    },

    networkDownloaderStatusClass() {
      if (this.networkDownloaderReady()) return 'border-success/30 text-success';
      if (this.networkDownloaderNeedsInstall()) return 'border-warn/30 text-warn';
      return 'border-surface-200 text-surface-600';
    },

    networkDownloaderSummary() {
      const status = this.networkDownloaderStatus();
      const hint = typeof status.network_downloader_hint === 'string' && status.network_downloader_hint.trim()
        ? status.network_downloader_hint.trim()
        : '';
      if (status.network_downloader_ready === true) {
        return hint || 'yt-dlp 可用，网络视频可直接下载到项目文件夹。';
      }
      if (status.network_downloader_ready === false) {
        return hint || '未检测到 yt-dlp。请安装后重试。';
      }
      return hint || '系统检查完成后会显示 yt-dlp 是否可用。';
    },

    networkDownloaderVersionLabel() {
      if (!this.networkDownloaderReady()) return '';
      const version = typeof this.networkDownloaderStatus().network_downloader_version === 'string'
        ? this.networkDownloaderStatus().network_downloader_version.trim()
        : '';
      return version ? `yt-dlp ${version}` : '';
    },

    networkDownloaderInstallCommand() {
      return 'python3 -m pip install -U yt-dlp';
    },

    async copyNetworkDownloaderInstallCommand() {
      const command = this.networkDownloaderInstallCommand();
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
          throw new Error('clipboard unavailable');
        }
        await navigator.clipboard.writeText(command);
        this.toast('已复制网络下载器安装命令', 'success');
      } catch (e) {
        this.toast('复制网络下载器安装命令失败，请手动复制', 'error');
      }
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

    isLocalCliProvider(provider) {
      return provider === 'claude_cli' || provider === 'codex_cli';
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
        low: '低',
        medium: '中',
        high: '高',
        xhigh: '超高',
        max: '最大',
        ultra: '极限（多代理）',
      };
      let levels = [];
      if (provider === 'claude_cli') {
        if (model === 'claude-fable-5' || model === 'claude-opus-4-7') {
          levels = ['low', 'medium', 'high', 'xhigh', 'max'];
        } else if (model === 'claude-sonnet-4-6') {
          levels = ['low', 'medium', 'high', 'max'];
        }
      } else if (provider === 'codex_cli') {
        if (model === 'gpt-5.6-sol' || model === 'gpt-5.6-terra') {
          levels = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'];
        } else if (model === 'gpt-5.6-luna') {
          levels = ['low', 'medium', 'high', 'xhigh', 'max'];
        } else {
          levels = ['low', 'medium', 'high', 'xhigh'];
        }
      }
      return ['auto', ...levels].map(value => ({ value, label: labels[value] }));
    },

    normalizeReasoningEffort(targetKey) {
      if (!this.isPlainObject(this.settings.translation)) this.settings.translation = {};
      const isPrimary = targetKey === 'primary';
      const provider = this.settings.translation[isPrimary ? 'primary_provider' : 'polish_provider'];
      const model = this.settings.translation[isPrimary ? 'primary_model' : 'polish_model'];
      const effortField = isPrimary ? 'primary_effort' : 'polish_effort';
      const current = typeof this.settings.translation[effortField] === 'string'
        ? this.settings.translation[effortField].trim().toLowerCase()
        : 'auto';
      const allowed = this.reasoningEffortOptions(provider, model).map(option => option.value);
      this.settings.translation[effortField] = allowed.includes(current) ? current : 'auto';
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
      this.kbSuggestionLoading = false;
      this.kbSuggestionError = '';
      this.kbSuggestionActionPending = '';
    },

    clearKbUsageTrace() {
      this.kbTraceRequestSeq += 1;
      this.kbUsageTrace = null;
      this.kbTraceLoading = false;
      this.kbTraceError = '';
    },

    clearQualityReport() {
      this.qaReportRequestSeq += 1;
      this.qaReport = null;
      this.qaReportLoading = false;
      this.qaReportError = '';
    },

    clearTranslationStrategy() {
      this.translationStrategyRequestSeq += 1;
      this.translationStrategy = null;
      this.translationStrategyLoading = false;
      this.translationStrategyError = '';
    },

    async loadKbSuggestions() {
      if (!this.currentProject?.id) {
        this.clearKbSuggestions();
        return;
      }
      const projectId = String(this.currentProject.id);
      const requestId = ++this.kbSuggestionsRequestSeq;
      this.kbSuggestionsLoading = true;
      this.kbSuggestionLoading = true;
      this.kbSuggestionsError = '';
      this.kbSuggestionError = '';
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
          this.kbSuggestionError = this.kbSuggestionsError;
          this.toast('加载 KB 建议失败: ' + e.message, 'error');
        }
      } finally {
        if (this.kbSuggestionsRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.kbSuggestionsLoading = false;
          this.kbSuggestionLoading = false;
        }
      }
    },

    async generateKbSuggestions() {
      if (!this.currentProject?.id || this.kbSuggestionActionPending) return;
      const projectId = String(this.currentProject.id);
      this.kbSuggestionActionPending = 'generate';
      this.kbSuggestionLoading = true;
      this.kbSuggestionsLoading = true;
      this.kbSuggestionError = '';
      this.kbSuggestionsError = '';
      try {
        const data = await this.api(`/api/knowledge/projects/${encodeURIComponent(projectId)}/suggestions/generate`, 'POST');
        if (String(this.currentProject?.id || '') !== projectId) return;
        const raw = Array.isArray(data?.suggestions) ? data.suggestions : [];
        this.kbSuggestions = raw
          .filter(item => this.isPlainObject(item))
          .map(item => ({
            ...item,
            target: typeof item.target === 'string' ? item.target : '',
            notes: typeof item.notes === 'string' ? item.notes : '',
            selected: item.status === 'accepted' ? false : !!(item.selected ?? true),
          }));
      } catch (e) {
        if (String(this.currentProject?.id || '') === projectId) {
          this.kbSuggestionError = e.message || '生成建议失败';
          this.kbSuggestionsError = this.kbSuggestionError;
          this.toast('生成 KB 建议失败: ' + e.message, 'error');
        }
      } finally {
        if (this.kbSuggestionActionPending === 'generate') this.kbSuggestionActionPending = '';
        if (String(this.currentProject?.id || '') === projectId) {
          this.kbSuggestionLoading = false;
          this.kbSuggestionsLoading = false;
        }
      }
    },

    async setKbSuggestionStatus(item, status) {
      const suggestionId = typeof item === 'string' ? item : String(item?.id || '');
      if (!this.currentProject?.id || !suggestionId || this.kbSuggestionActionPending) return;
      const localSuggestion = this.kbSuggestions.find(suggestion => suggestion?.id === suggestionId);
      const body = {status};
      if (status === 'accepted' && this.isPlainObject(localSuggestion)) {
        const target = typeof localSuggestion.target === 'string' ? localSuggestion.target.trim() : '';
        if (!target) {
          this.kbSuggestionError = '接受 KB 建议前需要填写译文';
          this.toast(this.kbSuggestionError, 'error');
          return;
        }
        body.target = target;
        body.notes = typeof localSuggestion.notes === 'string' ? localSuggestion.notes.trim() : '';
      }
      const projectId = String(this.currentProject.id);
      const pendingKey = `${status}:${suggestionId}`;
      this.kbSuggestionActionPending = pendingKey;
      this.kbSuggestionError = '';
      try {
        const data = await this.api(
          `/api/knowledge/projects/${encodeURIComponent(projectId)}/suggestions/${encodeURIComponent(suggestionId)}/status`,
          'POST',
          body,
        );
        if (String(this.currentProject?.id || '') !== projectId) return;
        const updated = this.isPlainObject(data?.suggestion) ? data.suggestion : null;
        this.kbSuggestions = this.kbSuggestions.map(suggestion => (
          suggestion?.id === suggestionId ? {...suggestion, ...(updated || {}), status} : suggestion
        ));
      } catch (e) {
        if (String(this.currentProject?.id || '') === projectId) {
          this.kbSuggestionError = e.message || '更新建议失败';
          this.toast('更新 KB 建议失败: ' + e.message, 'error');
        }
      } finally {
        if (this.kbSuggestionActionPending === pendingKey) this.kbSuggestionActionPending = '';
      }
    },

    normalizeQualityReport(data) {
      const src = this.isPlainObject(data) ? data : {};
      const summary = this.isPlainObject(src.summary) ? src.summary : {};
      const issues = Array.isArray(src.issues)
        ? src.issues.filter(item => this.isPlainObject(item))
        : [];
      const issueCount = Number.isFinite(Number(summary.issue_count)) ? Number(summary.issue_count) : issues.length;
      const repairedSource = summary.repaired_blocks ?? (Array.isArray(src.repaired_blocks) ? src.repaired_blocks.length : 0);
      const unresolvedSource = summary.unresolved_blocks ?? (Array.isArray(src.unresolved_blocks) ? src.unresolved_blocks.length : 0);
      const repairedBlocks = Number.isFinite(Number(repairedSource)) ? Number(repairedSource) : 0;
      const unresolvedBlocks = Number.isFinite(Number(unresolvedSource)) ? Number(unresolvedSource) : 0;
      return {
        ...src,
        status: typeof src.status === 'string' ? src.status : 'missing',
        issues,
        summary: {
          ...summary,
          issue_count: Math.max(0, issueCount),
          by_type: this.isPlainObject(summary.by_type) ? summary.by_type : {},
          repaired_blocks: Math.max(0, repairedBlocks),
          unresolved_blocks: Math.max(0, unresolvedBlocks),
        },
      };
    },

    qaIssueLabel(issue) {
      const type = typeof issue?.type === 'string' && issue.type.trim()
        ? issue.type.trim()
        : (typeof issue?.code === 'string' ? issue.code.trim() : '');
      const labels = {
        missing_translation: '漏译',
        english_residue: '英文残留',
        kb_term_missing: '知识库术语缺失',
        manual_term_missing: '手动术语缺失',
        domain_term_missing: '领域术语缺失',
        duplicate_id: '重复编号',
        line_too_long: '字幕过长',
        too_many_lines: '行数过多',
        reading_speed: '阅读速度过快',
        reading_speed_too_fast: '阅读速度过快',
        bad_line_break: '断行需审校',
        sound_description_translated: '环境音误译',
        punctuation_style: '标点风格',
        inferred_name_inconsistent: '专名不一致',
        proper_name_inconsistent: '专名不一致',
        scientific_term_inconsistent: '科学术语不一致',
        repetition_not_compressed: '重复表达需压缩',
      };
      return labels[type] || type || '质量问题';
    },

    qaIssueSeverityLabel(issue) {
      const severity = typeof issue?.severity === 'string' ? issue.severity : '';
      if (severity === 'error' || severity === 'severe') return '错误';
      if (severity === 'warning') return '警告';
      return '提示';
    },

    qaReportTopIssues(limit = 4) {
      const report = this.normalizeQualityReport(this.qaReport || {});
      const max = Number.isFinite(Number(limit)) ? Math.max(0, Number(limit)) : 4;
      return report.issues.slice(0, max).map(issue => ({
        ...issue,
        label: this.qaIssueLabel(issue),
        severity_label: this.qaIssueSeverityLabel(issue),
      }));
    },

    qaReportHasIssues() {
      const report = this.normalizeQualityReport(this.qaReport || {});
      return (report.summary?.issue_count || 0) > 0 || report.issues.length > 0;
    },

    qaReportSummaryText() {
      if (this.qaReportLoading) return '加载中...';
      const report = this.normalizeQualityReport(this.qaReport || {});
      if (report.status === 'missing') return '暂无报告';
      const issues = report.issues;
      const issueCount = report.summary.issue_count || issues.length;
      const errors = issues.filter(item => ['error', 'severe'].includes(String(item.severity || ''))).length;
      const warnings = issues.filter(item => String(item.severity || '') === 'warning').length;
      const repaired = report.summary.repaired_blocks || 0;
      const unresolved = report.summary.unresolved_blocks || 0;
      const conclusion = typeof report.summary.conclusion === 'string' ? report.summary.conclusion.trim() : '';
      if (conclusion) return conclusion;
      if (!issueCount) {
        return repaired ? `未发现遗留问题 · 已自动修复 ${repaired} 条` : '未发现确定性问题';
      }
      const parts = [`问题 ${issueCount} 个`];
      if (errors) parts.push(`错误 ${errors}`);
      if (warnings) parts.push(`警告 ${warnings}`);
      if (repaired) parts.push(`已修复 ${repaired}`);
      if (unresolved) parts.push(`未解决 ${unresolved}`);
      return parts.join(' · ');
    },

    qaReportNextAction() {
      const report = this.normalizeQualityReport(this.qaReport || {});
      if (!report || report.status === 'missing') return '';
      const gate = this.isPlainObject(report.summary?.quality_gate) ? report.summary.quality_gate : {};
      if (gate.passed === true) return '自动质检达标，可继续导出或烧录。';
      const issues = report.issues;
      const issueCount = report.summary.issue_count || issues.length;
      if (!issueCount) return '可继续导出或烧录。';
      if (gate.auto_repair_enabled && Number(gate.auto_repaired_blocks || 0) > 0) {
        return '系统已自动重点返工并复检；仍未达标，已停止交付，可重新启动自动返工。';
      }
      const hasErrors = issues.some(item => ['error', 'severe'].includes(String(item.severity || '')));
      if (hasErrors) return '仍有错误项，需重新自动返工后再导出或烧录。';
      if ((report.summary.unresolved_blocks || 0) > 0) return '仍有未解决警告，已停止交付，需重新自动返工。';
      return '仍有警告级问题，已停止交付，需重新自动返工。';
    },

    focusFirstQaIssue() {
      const first = this.qaReportTopIssues(1)[0];
      if (first?.block_id) this.focusSubtitleById(first.block_id);
    },

    normalizeTranslationStrategy(data) {
      const src = this.isPlainObject(data) ? data : {};
      const activeProfiles = Array.isArray(src.active_profiles)
        ? src.active_profiles.filter(item => this.isPlainObject(item))
        : [];
      const recommendations = Array.isArray(src.recommendations)
        ? src.recommendations.filter(item => this.isPlainObject(item))
        : [];
      const manualTerms = Array.isArray(src.manual_terms)
        ? src.manual_terms.filter(item => this.isPlainObject(item))
        : [];
      const retrieval = this.isPlainObject(src.retrieval) ? src.retrieval : {};
      const qa = this.isPlainObject(src.qa) ? src.qa : {};
      const qualityMode = this.isPlainObject(src.quality_mode) ? src.quality_mode : {};
      const qualityModeId = typeof qualityMode.id === 'string' && qualityMode.id.trim()
        ? qualityMode.id.trim()
        : 'fast';
      const status = typeof src.status === 'string' && src.status.trim()
        ? src.status.trim()
        : 'needs_context';
      const manualTermsCount = Number.isFinite(Number(src.manual_terms_count))
        ? Number(src.manual_terms_count)
        : manualTerms.length;
      return {
        ...src,
        status,
        summary: typeof src.summary === 'string' && src.summary.trim()
          ? src.summary.trim()
          : '尚未识别明确内容策略；可手动选择类型并补充术语。',
        content_type: typeof src.content_type === 'string' ? src.content_type : 'auto',
        content_type_label: typeof src.content_type_label === 'string' ? src.content_type_label : 'auto',
        active_profiles: activeProfiles,
        manual_terms: manualTerms,
        manual_terms_count: manualTermsCount,
        retrieval,
        qa,
        quality_mode: {
          ...qualityMode,
          id: qualityModeId,
          label: typeof qualityMode.label === 'string' && qualityMode.label.trim()
            ? qualityMode.label.trim()
            : (qualityModeId === 'professional' ? '专业自动' : '快速自动'),
          professional: qualityMode.professional === true || qualityModeId === 'professional',
          requires_kb_review: qualityMode.requires_kb_review === true,
          quality_gate: qualityMode.quality_gate === true,
          summary: typeof qualityMode.summary === 'string' ? qualityMode.summary : '',
        },
        recommendations,
      };
    },

    async loadTranslationStrategy() {
      if (!this.currentProject?.id) {
        this.clearTranslationStrategy();
        return;
      }
      const projectId = String(this.currentProject.id);
      const requestId = ++this.translationStrategyRequestSeq;
      this.translationStrategyLoading = true;
      this.translationStrategyError = '';
      try {
        const data = await this.api(`/api/projects/${encodeURIComponent(projectId)}/translation-strategy`);
        if (this.translationStrategyRequestSeq !== requestId || String(this.currentProject?.id || '') !== projectId) return;
        this.translationStrategy = this.normalizeTranslationStrategy(data);
      } catch (e) {
        if (this.translationStrategyRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.translationStrategyError = e.message || '加载翻译策略失败';
          this.translationStrategy = this.normalizeTranslationStrategy({status: 'needs_context'});
        }
      } finally {
        if (this.translationStrategyRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.translationStrategyLoading = false;
        }
      }
    },

    translationStrategyProfilePills() {
      const strategy = this.normalizeTranslationStrategy(this.translationStrategy || {});
      const labels = strategy.active_profiles
        .map(profile => (typeof profile.label === 'string' ? profile.label.trim() : ''))
        .filter(Boolean);
      if (labels.length) return labels;
      if (strategy.content_type_label && strategy.content_type_label !== 'auto') {
        return [strategy.content_type_label];
      }
      return ['自动判断'];
    },

    translationStrategyCapabilityPills() {
      const strategy = this.normalizeTranslationStrategy(this.translationStrategy || {});
      const pills = [];
      if (strategy.quality_mode?.label) pills.push(strategy.quality_mode.label);
      if (strategy.manual_terms_count > 0) pills.push(`术语 ${strategy.manual_terms_count}`);
      if (strategy.retrieval?.translation_memory) pills.push('用户修订记忆');
      if (strategy.retrieval?.phrase_library) pills.push('本地例句');
      if (strategy.qa?.auto_repair) {
        const rounds = Number.isFinite(Number(strategy.qa.auto_repair_rounds))
          ? Number(strategy.qa.auto_repair_rounds)
          : 1;
        pills.push(`自动修复 ${rounds} 轮`);
      } else {
        pills.push('质量报告');
      }
      return pills;
    },

    async loadQualityReport() {
      if (!this.currentProject?.id) {
        this.clearQualityReport();
        return;
      }
      const projectId = String(this.currentProject.id);
      const requestId = ++this.qaReportRequestSeq;
      this.qaReportLoading = true;
      this.qaReportError = '';
      try {
        const data = await this.api(`/api/projects/${encodeURIComponent(projectId)}/quality-report`);
        if (this.qaReportRequestSeq !== requestId || String(this.currentProject?.id || '') !== projectId) return;
        this.qaReport = this.normalizeQualityReport(data);
      } catch (e) {
        if (this.qaReportRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.qaReportError = e.message || '加载质量报告失败';
          this.qaReport = this.normalizeQualityReport({status: 'missing'});
        }
      } finally {
        if (this.qaReportRequestSeq === requestId && String(this.currentProject?.id || '') === projectId) {
          this.qaReportLoading = false;
        }
      }
    },

    normalizeKbUsageTrace(data) {
      const src = this.isPlainObject(data) ? data : {};
      const project = this.isPlainObject(src.project) ? src.project : {};
      const matches = Array.isArray(src.matches)
        ? src.matches.filter(item => this.isPlainObject(item))
        : [];
      const list = (key) => Array.isArray(src[key])
        ? src[key].filter(item => this.isPlainObject(item))
        : [];
      const textOf = (...values) => {
        for (const value of values) {
          if (typeof value === 'string' && value.trim()) return value.trim();
          if (typeof value === 'number' && Number.isFinite(value)) return String(value);
        }
        return '';
      };
      const memoryHits = list('memory_hits');
      const phraseHits = list('phrase_hits');
      const kbHits = list('kb_hits');
      const profileHits = list('profile_hits');
      const styleHits = list('style_hits');
      const conflictHits = list('conflict_hits');
      const displayHits = [
        ...matches.map((item) => ({
          ...item,
          trace_group: item.category ? this.kbCategoryLabel(item.category) : '项目知识库',
          trace_source: textOf(item.source, item.text, item.term),
          trace_target: textOf(item.target, item.translation, item.notes),
        })),
        ...memoryHits.map((item) => ({
          ...item,
          trace_group: '翻译记忆',
          trace_source: textOf(item.source_text, item.source, item.original, item.text),
          trace_target: textOf(item.final_translation, item.target_text, item.translation, item.target),
        })),
        ...phraseHits.map((item) => ({
          ...item,
          trace_group: '例句库',
          trace_source: textOf(item.source_text, item.source, item.original, item.text),
          trace_target: textOf(item.target_text, item.translation, item.target, item.source_name),
        })),
        ...kbHits.map((item) => ({
          ...item,
          trace_group: item.scope === 'manual_terms'
            ? '手动术语'
            : (item.scope === 'auto_kb_candidate' ? '自动候选' : '上下文'),
          trace_source: textOf(item.source, item.matched_source, item.source_title, item.id, item.scope),
          trace_target: textOf(item.target, item.notes, item.content_type, item.academic_field, item.status),
        })),
        ...profileHits.map((item) => ({
          ...item,
          trace_group: '内容策略',
          trace_source: textOf(item.label, item.id, item.scope),
          trace_target: Array.isArray(item.signals) && item.signals.length
            ? item.signals.join(' / ')
            : textOf(item.example_count),
        })),
        ...styleHits.map((item) => ({
          ...item,
          trace_group: '字幕样式',
          trace_source: textOf(item.id, item.scope),
          trace_target: [
            textOf(item.max_line_chars) ? `${item.max_line_chars}字/行` : '',
            textOf(item.max_chars_per_second) ? `${item.max_chars_per_second}cps` : '',
          ].filter(Boolean).join(' · '),
        })),
        ...conflictHits.map((item) => ({
          ...item,
          trace_group: '术语冲突',
          trace_source: textOf(item.source, item.term, item.id),
          trace_target: textOf(item.message, item.category, item.scope),
        })),
      ].filter(item => item.trace_source || item.trace_target);
      return {
        ...src,
        project,
        matches,
        memory_hits: memoryHits,
        phrase_hits: phraseHits,
        kb_hits: kbHits,
        profile_hits: profileHits,
        style_hits: styleHits,
        conflict_hits: conflictHits,
        display_hits: displayHits,
      };
    },

    kbSuggestionCounts() {
      const counts = {total: 0, pending: 0, accepted: 0, rejected: 0};
      for (const item of this.kbSuggestions || []) {
        if (!this.isPlainObject(item)) continue;
        counts.total += 1;
        const status = String(item.status || 'pending').trim();
        if (status === 'accepted') counts.accepted += 1;
        else if (status === 'rejected') counts.rejected += 1;
        else counts.pending += 1;
      }
      return counts;
    },

    kbSuggestionSummaryText() {
      if (this.kbSuggestionLoading) return '加载中...';
      const counts = this.kbSuggestionCounts();
      if (!counts.total) return '暂无建议';
      const parts = [`候选 ${counts.total} 条`];
      if (counts.pending) parts.push(`待处理 ${counts.pending}`);
      if (counts.accepted) parts.push(`已接受 ${counts.accepted}`);
      if (counts.rejected) parts.push(`已拒绝 ${counts.rejected}`);
      return parts.join(' · ');
    },

    kbUsageSummaryText() {
      if (this.kbTraceLoading) return '正在读取本次命中...';
      if (this.kbTraceError) return this.kbTraceError;
      const trace = this.normalizeKbUsageTrace(this.kbUsageTrace || {});
      const projectMatches = trace.matches.length;
      const autoCandidates = trace.kb_hits.filter(item => item.scope === 'auto_kb_candidate').length;
      const manualTerms = trace.kb_hits.filter(item => item.scope === 'manual_terms').length;
      const memoryHits = trace.memory_hits.length;
      const phraseHits = trace.phrase_hits.length;
      const parts = [];
      if (projectMatches) parts.push(`项目知识库命中 ${projectMatches}`);
      if (autoCandidates) parts.push(`自动候选参与 ${autoCandidates}`);
      if (manualTerms) parts.push(`手动术语 ${manualTerms}`);
      if (memoryHits) parts.push(`修订记忆 ${memoryHits}`);
      if (phraseHits) parts.push(`本地例句 ${phraseHits}`);
      if (parts.length) return parts.join(' · ');
      const counts = this.kbSuggestionCounts();
      if (counts.pending) return `待处理候选 ${counts.pending} 条；未审候选会作为软提示参与翻译。`;
      return '本次暂无知识库或例句命中。';
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
      event?.preventDefault?.();
      this.dropClickSuppressUntil = Date.now() + 800;

      const files = event?.dataTransfer?.files;
      const droppedFiles = Array.from(files || []);
      const localPaths = this.droppedLocalPaths(event);
      if (droppedFiles.length === 0 && localPaths.length === 0) return;
      if (this.homeSourceMode === 'batch') {
        const videoPaths = localPaths.filter((path) => this.isVideoPath(path));
        if (videoPaths.length > 0) {
          await this.startBatchVideoPaths(videoPaths, {sourceLabel: '拖入的视频文件'});
          return;
        }
        if (localPaths.length > 0) {
          this.newVideoPath = localPaths[0];
          await this.quickStartBatch();
          return;
        }
        this.toast('请使用桌面版选择文件夹，或粘贴文件夹路径后批量开始', 'error');
        return;
      }
      const videoPath = localPaths.find((path) => this.isVideoPath(path));
      if (videoPath) {
        await this.useSelectedVideoPath(videoPath);
        return;
      }
      if (this.isDesktopShell() && this.isVideoFile(droppedFiles[0])) {
        this.scheduleMissingNativeDropPathToast();
        return;
      }
      await this.useSelectedVideoFile(droppedFiles[0]);
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

    async openFolderPicker() {
      if (this.fileImporting || this.projectCreating) return;
      try {
        if (window.pywebview && window.pywebview.api?.select_video_folder) {
          const p = await window.pywebview.api.select_video_folder();
          if (p) {
            this.newVideoPath = p;
            await this.quickStartBatch();
            return;
          }
        } else if (window.electronAPI?.selectVideoFolder) {
          const p = await window.electronAPI.selectVideoFolder();
          if (p) {
            this.newVideoPath = p;
            await this.quickStartBatch();
            return;
          }
        }
      } catch(e) {
        console.warn('native folder picker failed', e);
      }
      this.toast('当前环境不支持直接选择文件夹，请粘贴文件夹路径后批量开始', 'error');
    },

    async openSubtitleFilePicker() {
      if (this.fileImporting || this.projectCreating) return;
      this.$refs.subtitleFileInput?.click();
    },

    async openAudioFilePicker() {
      if (this.fileImporting || this.projectCreating) return;
      this.$refs.audioFileInput?.click();
    },

    async handleFileSelect(event) {
      const file = event.target?.files?.[0];
      try {
        await this.useSelectedVideoFile(file);
      } finally {
        if (event.target) event.target.value = '';
      }
    },

    async handleSubtitleFileSelect(event) {
      const file = event.target?.files?.[0];
      try {
        await this.useSelectedSubtitleFile(file);
      } finally {
        if (event.target) event.target.value = '';
      }
    },

    async handleAudioFileSelect(event) {
      const file = event.target?.files?.[0];
      try {
        await this.useSelectedAudioFile(file);
      } finally {
        if (event.target) event.target.value = '';
      }
    },

    normalizeBatchVideoPaths(items) {
      const seen = new Set();
      const paths = [];
      for (const item of Array.isArray(items) ? items : []) {
        const rawPath = typeof item === 'string'
          ? item
          : (typeof item?.path === 'string' ? item.path : '');
        const path = rawPath.trim();
        if (!path || !this.isVideoPath(path)) continue;
        const key = path.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        paths.push(path);
      }
      return paths;
    },

    async runBatchVideoPaths(videoPaths, options = {}) {
      const paths = this.normalizeBatchVideoPaths(videoPaths);
      if (paths.length === 0) {
        this.toast('没有找到可处理的视频文件', 'error');
        return {created: 0, failed: 0};
      }

      const sourceLabel = String(options.sourceLabel || '文件夹').trim() || '文件夹';
      const truncated = !!options.truncated;
      const taskSettings = await this.openTaskSettings({
        title: '批量任务设置',
        message: `${sourceLabel}已发现 ${paths.length} 个视频。选择一次输出方式和语言后，系统会逐个创建项目并自动开始。${truncated ? '本次只处理前 500 个视频。' : ''}`,
        canBurn: true,
        workflow_mode: 'translate_only',
        asr_language: this.asrLanguage,
        target_language: this.targetLang,
      });
      if (!taskSettings) {
        this.toast('已取消批量处理');
        return {created: 0, failed: 0};
      }

      const asrLanguage = String(taskSettings.asr_language || this.asrLanguage || 'auto').trim() || 'auto';
      const targetLanguage = String(taskSettings.target_language || this.targetLang || '简体中文').trim() || '简体中文';
      this.asrLanguage = asrLanguage;
      this.targetLang = targetLanguage;

      let created = 0;
      let failed = 0;
      const createdProjects = [];
      for (const videoPath of paths) {
        try {
          const project = await this.api('/api/projects', 'POST', {
            video_path: videoPath,
            asr_language: asrLanguage,
            target_language: targetLanguage,
          });
          const startBody = {
            workflow_mode: this.normalizeWorkflowMode(taskSettings.workflow_mode, this.canBurnVideo(project)),
            language: asrLanguage,
            target_language: targetLanguage,
          };
          await this.api(`/api/projects/${project.id}/start-full`, 'POST', startBody);
          project.status = 'processing';
          project.workflow_mode = startBody.workflow_mode;
          created += 1;
          createdProjects.push(project);
        } catch(e) {
          failed += 1;
          console.warn('batch project failed', videoPath, e);
        }
      }

      if (createdProjects.length > 0) {
        this.clearKbSuggestions();
        this.clearKbUsageTrace();
        this.clearQualityReport();
        this.clearTranslationStrategy();
        this.currentProject = createdProjects[createdProjects.length - 1];
        this.workflowState = null;
        this.workflowStateError = '';
        this.applyWorkflowDefaultsFromProject(this.currentProject);
        await this.loadProjects();
        await this.setView('projects');
      }

      if (created === 0) {
        this.toast(`批量任务未启动：${failed} 个视频创建失败`, 'error');
      } else {
        this.toast(`批量任务已启动：${created} 个${failed ? `，失败 ${failed} 个` : ''}`);
      }
      return {created, failed};
    },

    async startBatchVideoPaths(videoPaths, options = {}) {
      if (this.projectCreating || this.fileImporting) return;
      this.projectCreating = true;
      try {
        if (!await this.ensureTranslationReadyForWorkflow()) return;
        await this.runBatchVideoPaths(videoPaths, options);
      } catch(e) {
        this.toast('批量处理失败: ' + e.message, 'error');
      } finally {
        this.projectCreating = false;
      }
    },

    async quickStartBatch() {
      if (this.projectCreating || this.fileImporting) return;
      const folderPath = String(this.newVideoPath || '').trim();
      if (!folderPath) return;
      this.projectCreating = true;
      try {
        if (!await this.ensureTranslationReadyForWorkflow()) return;
        const discovery = await this.api('/api/projects/discover-local-videos', 'POST', {
          folder_path: folderPath,
          recursive: true,
          limit: 500,
        });
        const videos = Array.isArray(discovery?.videos) ? discovery.videos : [];
        if (videos.length === 0) {
          this.toast('文件夹内没有找到可处理的视频文件', 'error');
          return;
        }
        const result = await this.runBatchVideoPaths(videos, {
          sourceLabel: '文件夹',
          truncated: !!discovery?.truncated,
        });
        if (result?.created > 0 && this.newVideoPath === folderPath) this.newVideoPath = '';
      } catch(e) {
        this.toast('批量处理失败: ' + e.message, 'error');
      } finally {
        this.projectCreating = false;
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
        this.clearKbSuggestions();
        this.clearKbUsageTrace();
        this.clearQualityReport();
        this.clearTranslationStrategy();
        this.currentProject = p;
        this.workflowState = null;
        this.workflowStateError = '';
        this.applyWorkflowDefaultsFromProject(p);
        await this.setView('detail');
        this.connectWS(p.id);
        const taskSettings = await this.openProjectTaskSettings(p, {
          title: '任务设置',
          message: '本地视频已识别完成。选择输出方式和本次任务语言；仅翻译会生成字幕文件，不烧录到视频。',
        });
        if (!taskSettings) {
          this.toast('项目已创建，未开始处理');
          return;
        }
        const startBody = this.applyTaskSettingsToCurrentProject(taskSettings, p);
        await this.api(`/api/projects/${p.id}/start-full`, 'POST', startBody);
        this.currentProject.status = 'processing';
        this.toast(startBody.workflow_mode === 'translate_only' ? '开始处理，仅生成字幕...' : '项目已创建，开始处理...');
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
          this.clearQualityReport();
          this.clearTranslationStrategy();
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
          this.clearQualityReport();
          this.clearTranslationStrategy();
        }
        this.currentProject = project;
        await this.loadWorkflowState();
        if (this.openProjectRequestSeq !== requestId || this.currentProject?.id !== project.id) return;
        this.loadKbSuggestions();
        this.loadKbUsageTrace();
        this.loadQualityReport();
        this.loadTranslationStrategy();
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

    contentTypeLabel(value) {
      const labels = {
        auto: '自动判断',
        movie: '电影',
        series: '剧集',
        documentary: '纪录片 / 非虚构',
        interview: '访谈 / 播客',
        academic_lecture: '学术讲座 / 课程',
        technical_tutorial: '技术教程',
        legal_adult: '成人内容',
        other: '其他',
      };
      return labels[value] || labels.auto;
    },

    projectMetadataHint(project) {
      const type = project?.content_type || 'auto';
      if (type === 'academic_lecture') {
        return '建议填写学科、课程/讲座主题和高频术语，例如 gradient descent=梯度下降。';
      }
      if (type === 'technical_tutorial') {
        return '建议填写技术栈、版本、命令/API 名称和固定译法。';
      }
      if (type === 'interview') {
        return '建议填写嘉宾、节目主题和姓名/机构固定译法。';
      }
      if (type === 'legal_adult') {
        return '仅在合法成人内容中使用；可填写称呼、语气和需要固定的露骨表达译法。';
      }
      return '可选填写。影视项目会继续尝试 TMDB 补全；非影视项目可直接用这里的信息指导翻译。';
    },

    async saveProjectMetadata() {
      const project = this.currentProject;
      if (!project?.id || this.isProjectMutationPending('metadata', project.id)) return;
      this.setProjectMutationPending('metadata', project.id, true);
      try {
        const updated = await this.api(`/api/projects/${project.id}`, 'PATCH', {
          content_type: String(project.content_type || 'auto').trim() || 'auto',
          original_language: String(project.original_language || '').trim(),
          academic_field: String(project.academic_field || '').trim(),
          content_notes: String(project.content_notes || '').trim(),
          manual_terms: String(project.manual_terms || '').trim(),
          metadata_source: 'manual',
        });
        if (this.currentProject?.id === project.id) this.currentProject = updated;
        await this.loadProjects();
        this.toast('内容信息已保存');
      } catch(e) {
        this.toast(e.message, 'error');
      } finally {
        this.setProjectMutationPending('metadata', project.id, false);
      }
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
          else if (p.status === 'cancelled') this.toast(p.progress_msg || '已取消');
          else if (p.status === 'completed') this.toast('带字幕的视频已就绪！');
          else this.toast('处理完成');
          await this.loadWorkflowState();
          this.loadKbSuggestions();
          this.loadKbUsageTrace();
          this.loadQualityReport();
          this.loadTranslationStrategy();
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
        await this.handleProjectActionError(e);
      } finally {
        if (this.projectActionPending === action) this.projectActionPending = '';
      }
    },

    isKbReviewRequiredError(error) {
      return this.isPlainObject(error?.detail)
        && error.detail.code === 'kb_review_required';
    },

    async handleProjectActionError(error) {
      const message = error?.message || '启动失败';
      if (this.isKbReviewRequiredError(error)) {
        this.kbSuggestionError = message;
        this.kbSuggestionsError = message;
        await this.loadKbSuggestions();
        this.toast(message, 'error');
        return;
      }
      this.toast(message, 'error');
    },

    async startASR() {
      if (!this.currentProject) return;
      if (!this.canRunAsr(this.currentProject)) {
        this.toast('纯字幕项目不需要语音识别', 'error');
        return;
      }
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
      const audioOnly = this.currentProject.source_type === 'audio';
      const subtitleOnly = this.currentProject.source_type === 'subtitle';
      if (!audioOnly && !subtitleOnly) {
        if (this.projectActionsDisabled(this.currentProject)) return;
        const action = 'start-full';
        this.projectActionPending = action;
        try {
          if (!await this.ensureTranslationReadyForWorkflow()) return;
          const taskSettings = await this.openProjectTaskSettings(this.currentProject, {
            title: '任务设置',
            message: '选择本次处理的输出方式和语言；仅翻译会生成字幕文件，不烧录到视频。',
          });
          if (!taskSettings) return;
          const body = this.applyTaskSettingsToCurrentProject(taskSettings, this.currentProject);
          await this.api(`/api/projects/${this.currentProject.id}/start-full`, 'POST', body);
          this.currentProject.status = 'processing';
          this.toast(body.workflow_mode === 'translate_only' ? '开始处理，仅生成字幕...' : '开始一键处理...');
        } catch(e) {
          await this.handleProjectActionError(e);
        } finally {
          if (this.projectActionPending === action) this.projectActionPending = '';
        }
        return;
      }
      await this.runProjectAction(
        'start-full',
        `/api/projects/${this.currentProject.id}/${audioOnly ? 'start-transcribe-translate' : (subtitleOnly ? 'start-translate' : 'start-full')}`,
        subtitleOnly
          ? { target_language: this.targetLang }
          : { language: this.asrLanguage, target_language: this.targetLang },
        audioOnly ? '开始转写并翻译...' : (subtitleOnly ? '开始翻译字幕...' : '开始一键处理...'),
        { requiresTranslation: true }
      );
    },

    async startBurn() {
      if (!this.currentProject) return;
      if (!this.canBurnVideo(this.currentProject)) {
        this.toast('当前项目没有视频烧录步骤', 'error');
        return;
      }
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
          const nextStatus = typeof result.project_status === 'string' && result.project_status.trim()
            ? result.project_status.trim()
            : 'cancelled';
          const message = typeof result.message === 'string' && result.message.trim()
            ? result.message.trim()
            : '已取消';
          this.toast(message);
          this.currentProject.status = nextStatus;
          this.currentProject.pipeline_stage = null;
          this.currentProject.error = null;
          this.currentProject.progress_msg = message;
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
      const nextTick = typeof this.$nextTick === 'function' ? this.$nextTick.bind(this) : (fn) => fn();
      nextTick(() => { if (this.$refs?.editArea) this.$refs.editArea.focus(); });
    },

    focusSubtitleById(blockId) {
      const numericId = Number(blockId);
      if (!Number.isFinite(numericId)) return false;
      const idx = this.subtitles.findIndex(item => Number(item?.index) === numericId);
      if (idx < 0) {
        this.toast(`未找到第 ${numericId} 条字幕`, 'error');
        return false;
      }
      const item = this.subtitles[idx] || {};
      this.startEdit(idx, item.translation || '');
      const nextTick = typeof this.$nextTick === 'function' ? this.$nextTick.bind(this) : (fn) => fn();
      nextTick(() => {
        if (typeof document === 'undefined') return;
        const safeId = String(numericId).replace(/"/g, '\\"');
        const row = document.querySelector(`[data-subtitle-index="${safeId}"]`);
        if (row && typeof row.scrollIntoView === 'function') {
          row.scrollIntoView({block: 'center', behavior: 'smooth'});
        }
      });
      return true;
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

    subtitleIsSoundDescription(item) {
      return this.isPlainObject(item) && item.sound_description === true;
    },

    normalizeSubtitleQualityFormat(format) {
      return ['original', 'translated', 'bilingual'].includes(format) ? format : 'translated';
    },

    subtitleQualityLinesForFormat(format, sourceText, translationText) {
      const normalizedFormat = this.normalizeSubtitleQualityFormat(format);
      const source = String(sourceText || '').trim();
      const translation = String(translationText || '').trim();
      const parts = [];
      if (normalizedFormat === 'original') {
        parts.push(source);
      } else if (normalizedFormat === 'translated') {
        parts.push(translation);
      } else {
        parts.push(source, translation);
      }
      return parts
        .flatMap((value) => String(value || '').split(/\r?\n/))
        .map((line) => line.trim())
        .filter(Boolean);
    },

    subtitleQualityIssues(format = 'translated') {
      const normalizedFormat = this.normalizeSubtitleQualityFormat(format);
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
        const sourceIsSoundDescription = this.subtitleIsSoundDescription(item);

        if (hasTiming && previous && startMs < previous.endMs) {
          addIssue(item, idx, 'overlap', 'severe', `第 ${idx + 1} 行与上一行时间重叠`);
        }
        if (hasTiming && durationMs <= 0) {
          addIssue(item, idx, 'non_positive_duration', 'severe', `第 ${idx + 1} 行时长无效`);
        }
        if (!sourceText) {
          addIssue(item, idx, 'empty_source', 'severe', `第 ${idx + 1} 行缺少原文`);
        }
        if (sourceIsSoundDescription) {
          if (hasTiming) previous = { endMs };
          return;
        }
        if (normalizedFormat !== 'original' && sourceText && !translationText) {
          addIssue(item, idx, 'missing_translation', 'severe', `第 ${idx + 1} 行缺少译文`);
        }

        const lines = this.subtitleQualityLinesForFormat(normalizedFormat, sourceText, translationText);
        if (lines.some((line) => line.trim().length > lineLimit)) {
          addIssue(item, idx, 'long_line', 'warning', `第 ${idx + 1} 行过长`);
        }
        const readableChars = lines.reduce((max, line) => Math.max(max, line.length), 0);
        const seconds = durationMs / 1000;
        if (hasTiming && readableChars > 0 && (seconds <= 0 || readableChars / seconds > readingSpeedLimit)) {
          addIssue(item, idx, 'reading_speed', 'warning', `第 ${idx + 1} 行阅读速度过快`);
        }

        if (hasTiming) previous = { endMs };
      });

      return issues;
    },

    subtitleQualitySummary(format = 'translated') {
      const issues = this.subtitleQualityIssues(format);
      return issues.reduce((summary, issue) => {
        summary.total += 1;
        if (issue.severity === 'severe') summary.severe += 1;
        else summary.warning += 1;
        return summary;
      }, { total: 0, severe: 0, warning: 0, issues });
    },

    hasSevereSubtitleIssues(format = 'translated') {
      return this.subtitleQualitySummary(format).severe > 0;
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
      const summary = this.subtitleQualitySummary(format);
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

    subtitleTimelineDurationMs() {
      const projectDuration = Number(this.currentProject?.duration);
      if (Number.isFinite(projectDuration) && projectDuration > 0) return projectDuration * 1000;
      return this.subtitles.reduce((maxEnd, item) => {
        if (!this.isPlainObject(item)) return maxEnd;
        return Math.max(maxEnd, this.parseSrtTime(item.end));
      }, 0);
    },

    subtitleTimelineSegments() {
      const durationMs = this.subtitleTimelineDurationMs();
      if (!durationMs) return [];
      const roundPct = (value) => Math.round(value * 100) / 100;
      return this.subtitles
        .filter((item) => this.isPlainObject(item))
        .map((item, idx) => {
          const startMs = Math.max(0, Math.min(durationMs, this.parseSrtTime(item.start)));
          const rawEndMs = this.parseSrtTime(item.end);
          const endMs = Math.max(startMs, Math.min(durationMs, rawEndMs));
          const left = roundPct((startMs / durationMs) * 100);
          const width = roundPct(Math.max(0.8, ((endMs - startMs) / durationMs) * 100));
          return {
            index: Number.isInteger(item.index) ? item.index : idx + 1,
            left,
            width: Math.min(width, roundPct(100 - left)),
            filtered: !!item.filtered,
            label: `第 ${Number.isInteger(item.index) ? item.index : idx + 1} 行 ${item.start || ''} - ${item.end || ''}`.trim(),
          };
        });
    },

    async handleSubtitleShortcut(event, idx) {
      if (!event || !(event.metaKey || event.ctrlKey)) return false;
      const key = String(event.key || '').toLowerCase();
      let action = null;
      if (key === 'enter' && !event.shiftKey) action = () => this.saveEdit(idx);
      else if (event.shiftKey && key === 's') action = () => this.splitSubtitle(idx);
      else if (event.shiftKey && key === 'm') action = () => this.mergeSubtitleWithNext(idx);
      else if (event.shiftKey && key === 'a') action = () => this.addSubtitleAfter(idx);
      else if (key === 'backspace' || key === 'delete') action = () => this.deleteSubtitle(idx);
      if (!action) return false;
      event.preventDefault?.();
      await action();
      return true;
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

    async exportSubtitle(format, container = 'srt') {
      container = container === 'vtt' ? 'vtt' : 'srt';
      if (!this.canExportSubtitle(format)) {
        this.toast(this.exportUnavailableMessage(format), 'error');
        return;
      }
      const warningMessage = this.subtitleExportWarningMessage(format);
      if (this.hasSevereSubtitleIssues(format) && warningMessage) {
        const confirmed = await this.askConfirm({
          title: '继续导出字幕？',
          message: warningMessage,
          confirmText: '继续导出',
          intent: 'warning',
        });
        if (!confirmed) return;
      }
      const actionKey = this.exportActionKey(format, container);
      this.projectActionPending = actionKey;
      try {
        const exportUrl = container === 'srt'
          ? `/api/projects/${this.currentProject.id}/export?format=${encodeURIComponent(format)}`
          : `/api/projects/${this.currentProject.id}/export?format=${encodeURIComponent(format)}&container=${encodeURIComponent(container)}`;
        const data = await this.api(exportUrl, 'POST');
        const filename = this.safeDownloadFilename(data.filename, `${format || 'subtitles'}.${container}`);
        const nativeApi = this.nativeSaveApi();
        if (nativeApi && typeof nativeApi.save_text_file === 'function') {
          const result = await nativeApi.save_text_file(filename, String(data.content || ''));
          if (result && result.ok === false) throw new Error(result.error || '保存失败');
          this.toast('字幕已保存');
          return;
        }
        const mime = container === 'vtt' ? 'text/vtt;charset=utf-8' : 'text/plain;charset=utf-8';
        const blob = new Blob([data.content], { type: mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
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

    async exportSrt(format) {
      return this.exportSubtitle(format, 'srt');
    },

    async saveOutputVideo() {
      if (!this.canSaveVideo()) {
        this.toast(this.saveVideoUnavailableMessage(), 'error');
        return;
      }
      const nativeApi = this.nativeSaveApi();
      if (!nativeApi || typeof nativeApi.save_project_video !== 'function') {
        this.toast('当前环境不支持保存视频', 'error');
        return;
      }
      const actionKey = 'save-video';
      this.projectActionPending = actionKey;
      try {
        const filename = this.safeDownloadFilename(
          this.currentProject.output_video,
          `${this.currentProject.name || 'output'}_subtitled.mp4`,
        );
        const result = await nativeApi.save_project_video(this.currentProject.id, filename);
        if (result && result.ok === false) throw new Error(result.error || '保存失败');
        this.toast('视频已保存');
      } catch(e) {
        this.toast(e.message || '保存视频失败', 'error');
      } finally {
        if (this.projectActionPending === actionKey) this.projectActionPending = '';
      }
    },

    async saveSettings() {
      if (this.settingsSaving) return;
      this.settingsSaving = true;
      try {
        await this.api('/api/settings', 'POST', this.settingsPayload());
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

    providerModelFallback(provider) {
      const fallback = {
        openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'o3-mini', 'o4-mini'],
        deepseek: ['deepseek-chat', 'deepseek-reasoner'],
        gemini: ['gemini-3.1-pro-preview', 'gemini-3.1-flash-lite-preview', 'gemini-3-pro-preview', 'gemini-3-flash-preview', 'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.0-flash', 'gemini-2.0-flash-lite'],
        claude_cli: ['claude-fable-5', 'claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5'],
        codex_cli: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.3-codex-spark'],
      };
      return fallback[provider] || [];
    },

    cliProviderModelOptions(provider) {
      const cached = this.modelCache[provider];
      const models = Array.isArray(cached) && cached.length > 0
        ? cached
        : this.providerModelFallback(provider);
      return models.filter(model => typeof model === 'string' && model.trim()).map(model => model.trim());
    },

    async refreshCliProviderModelCatalog(provider) {
      try {
        const response = await this.api(`/api/models/${provider}`);
        const models = Array.isArray(response.models)
          ? response.models.filter(model => typeof model === 'string' && model.trim()).map(model => model.trim())
          : [];
        if (models.length > 0) this.modelCache[provider] = models;
      } catch (error) {
        console.warn(`refreshCliProviderModelCatalog failed for ${provider}:`, error);
      }
      return this.cliProviderModelOptions(provider);
    },

    ensureSelectedModel(targetKey, models) {
      if (!this.isPlainObject(this.settings.translation)) this.settings.translation = {};
      const field = targetKey === 'primary' ? 'primary_model' : 'polish_model';
      const current = typeof this.settings.translation[field] === 'string'
        ? this.settings.translation[field].trim()
        : '';
      if (targetKey === 'polish' && models.length === 0) {
        this.settings.translation.polish_model = '';
        this.normalizeReasoningEffort(targetKey);
        return;
      }
      if (models.length > 0 && !models.includes(current)) {
        this.settings.translation[field] = models[0];
      }
      this.normalizeReasoningEffort(targetKey);
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
      const fb = this.providerModelFallback(provider);
      this.setModelOptions(targetKey, fb);
      // Try fetching from API
      const apiKeys = this.isPlainObject(this.settings.api_keys) ? this.settings.api_keys : {};
      const requiresApiKey = provider !== 'claude_cli' && provider !== 'codex_cli';
      if (requiresApiKey && !apiKeys[provider]) {
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
          claude_cli: this.translationModelForProvider('claude_cli', 'claude-opus-4-7'),
          codex_cli: this.translationModelForProvider('codex_cli', 'gpt-5.5'),
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

    networkVideoDownloadMessage() {
      return [
        '将直接下载这个网络视频，并创建本地翻译项目。',
        '',
        '下载位置：~/AI_Sub_Pro_Data/projects/<项目ID>/original.mp4',
        '不会保存到系统下载目录。创建后可以在项目卡片或项目详情点击“显示”打开项目位置。',
        '',
        '如果平台提供原生字幕，会优先翻译字幕；否则下载视频后进入 ASR 听写。',
      ].join('\n');
    },

    async confirmNetworkVideoDownload() {
      return this.askConfirm({
        title: '直接下载并翻译这个网络视频？',
        message: this.networkVideoDownloadMessage(),
        confirmText: '直接下载并翻译',
        cancelText: '取消',
        intent: 'primary',
      });
    },

    normalizeCreatedTrailerProjects(data) {
      const raw = Array.isArray(data?.projects) ? data.projects : [];
      return raw
        .filter((project) => this.isPlainObject(project))
        .map((project) => ({
          id: typeof project.id === 'string' ? project.id.trim() : '',
          name: typeof project.name === 'string' ? project.name.trim() : '',
          content_type: typeof project.content_type === 'string' ? project.content_type.trim() : '',
          academic_field: typeof project.academic_field === 'string' ? project.academic_field.trim() : '',
          metadata_source: typeof project.metadata_source === 'string' ? project.metadata_source.trim() : '',
          network_video_plan: this.isPlainObject(project.network_video_plan)
            ? project.network_video_plan
            : null,
        }))
        .filter((project) => project.id || project.name || project.content_type || project.network_video_plan);
    },

    createdTrailerProjectTitle(project) {
      const name = typeof project?.name === 'string' ? project.name.trim() : '';
      const id = typeof project?.id === 'string' ? project.id.trim() : '';
      if (name && id) return `${name} · ${id}`;
      return name || id || '在线视频项目';
    },

    createdTrailerProjectContentSummary(project) {
      const type = typeof project?.content_type === 'string' ? project.content_type.trim() : '';
      if (!type || type === 'auto') return '';
      const label = this.contentTypeLabel(type);
      const academicField = typeof project?.academic_field === 'string'
        ? project.academic_field.trim()
        : '';
      return `内容类型：${[label, academicField].filter(Boolean).join(' · ')}`;
    },

    networkVideoPlan(project) {
      return this.isPlainObject(project?.network_video_plan)
        ? project.network_video_plan
        : {};
    },

    networkVideoPlanLocation(project) {
      const plan = this.networkVideoPlan(project);
      for (const key of ['download_path', 'download_path_hint', 'download_location_label']) {
        const value = typeof plan[key] === 'string' ? plan[key].trim() : '';
        if (value) return value;
      }
      return '项目文件夹 original.mp4';
    },

    networkVideoPlanLanguages(value) {
      if (!Array.isArray(value)) return [];
      const languages = [];
      const seen = new Set();
      value.forEach((item) => {
        if (typeof item !== 'string') return;
        const language = item.trim();
        if (!language) return;
        const normalized = language.toLowerCase();
        if (['auto', 'und', 'unknown', 'none', 'null'].includes(normalized)) return;
        if (seen.has(normalized)) return;
        seen.add(normalized);
        languages.push(language);
      });
      return languages.slice(0, 8);
    },

    networkVideoPlanSummary(project) {
      const plan = this.networkVideoPlan(project);
      const label = typeof plan.subtitle_strategy_label === 'string'
        ? plan.subtitle_strategy_label.trim()
        : '';
      if (label) return label;

      const subtitleLanguages = this.networkVideoPlanLanguages(plan.detected_subtitle_languages);
      const automaticCaptionLanguages = this.networkVideoPlanLanguages(plan.detected_automatic_caption_languages);
      if (subtitleLanguages.length || automaticCaptionLanguages.length) {
        const detected = [];
        if (subtitleLanguages.length) {
          detected.push(`原生字幕：${subtitleLanguages.join(', ')}`);
        }
        if (automaticCaptionLanguages.length) {
          detected.push(`自动字幕：${automaticCaptionLanguages.join(', ')}`);
        }
        return `检测到平台字幕（${detected.join('；')}）；会优先下载字幕并翻译，失败再进入 ASR 听写。`;
      }

      if (plan.subtitle_probe_status === 'not_found') {
        return '未检测到平台字幕；下载视频后进入 ASR 听写。';
      }
      return '优先获取平台原生字幕；没有字幕再进入 ASR 听写。';
    },

    async startTrailerJobs() {
      if (this.trailerSubmitting) return;
      if (this.trailerSelectedVideos.length === 0) return;
      const show = this.trailerSelectedShow;
      if (!show) return;
      this.trailerError = null;
      this.trailerSubmitting = true;
      const singleSeason = this.trailerSelectedSeasons.length === 1 ? this.trailerSelectedSeasons[0] : null;
      try {
        if (!await this.ensureTranslationReadyForWorkflow()) {
          this.trailerError = `请先完成翻译引擎配置：${this.systemTranslationHint()}`;
          return;
        }
        const taskSettings = await this.openTaskSettings({
          title: '创建剧集翻译任务',
          message: '选择输出方式和本次任务语言。仅翻译会生成字幕文件，不烧录到视频。',
          canBurn: true,
          workflow_mode: 'translate_burn',
          asr_language: show.original_language || 'en',
          target_language: this.targetLang,
        });
        if (!taskSettings) return;
        const payload = {
          tmdb_id: show.id,
          tmdb_type: show.media_type,
          season: singleSeason,
          video_keys: this.trailerSelectedVideos,
          original_language: taskSettings.asr_language,
          name: show.name || show.title || '未命名',
          target_language: taskSettings.target_language,
          workflow_mode: taskSettings.workflow_mode,
        };
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
        this.trailerCreatedProjects = this.normalizeCreatedTrailerProjects(data);
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

    async startTrailerUrlJob() {
      if (this.trailerSubmitting) return;
      const videoUrl = String(this.trailerUrlInput || '').trim();
      if (!videoUrl) {
        this.trailerError = '请先输入 YouTube 链接或视频地址';
        return;
      }
      this.trailerError = null;
      this.trailerSubmitting = true;
      try {
        if (!await this.ensureTranslationReadyForWorkflow()) {
          this.trailerError = `请先完成翻译引擎配置：${this.systemTranslationHint()}`;
          return;
        }
        if (!await this.confirmNetworkVideoDownload()) {
          return;
        }
        const taskSettings = await this.openTaskSettings({
          title: '创建在线视频任务',
          message: '选择输出方式和本次任务语言。仅翻译会生成字幕文件，不烧录到视频。',
          canBurn: true,
          workflow_mode: 'translate_burn',
          asr_language: String(this.trailerOriginalLanguage || 'auto').trim() || 'auto',
          target_language: this.targetLang,
        });
        if (!taskSettings) return;
        const payload = {
          video_url: videoUrl,
          name: String(this.trailerNameInput || '').trim(),
          original_language: taskSettings.asr_language,
          target_language: taskSettings.target_language,
          workflow_mode: taskSettings.workflow_mode,
        };
        const r = await fetch('/api/trailer/start-url', {
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
        this.trailerCreatedProjects = this.normalizeCreatedTrailerProjects(data);
        await this.setView('trailer');
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
      this.trailerUrlInput = '';
      this.trailerNameInput = '';
      this.trailerOriginalLanguage = 'auto';
      this.trailerSearchResults = [];
      this.trailerSelectedShow = null;
      this.trailerSeasons = [];
      this.trailerSelectedSeasons = [];
      this.trailerVideos = [];
      this.trailerSelectedVideos = [];
      this.trailerError = null;
      this.trailerCreatedCount = 0;
      this.trailerCreatedProjects = [];
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
