'use strict';
(() => {
  const providerNames = {codex_cli:'Codex CLI', claude_cli:'Claude CLI', openai:'OpenAI', deepseek:'DeepSeek', gemini:'Gemini'};
  const effortNames = {auto:'自动', low:'低', medium:'中', high:'高', xhigh:'很高', max:'最大', ultra:'极高'};
  const fields = {
    'setting-model':['translation','primary_model'],
    'setting-effort':['translation','primary_effort'],
    'setting-polish-provider':['translation','polish_provider'],
    'setting-polish-model':['translation','polish_model'],
    'setting-polish-effort':['translation','polish_effort'],
    'setting-asr-model':['asr','model_size'],
    'setting-beam':['asr','beam_size'],
    'setting-batch':['translation','batch_size'],
    'setting-qa-batch':['translation','semantic_qa_batch_size'],
    'setting-full-doc':['translation','full_doc_mode'],
  };
  let panel = 'tasks', pid = '', settings = null, catalog = {}, serverStatus = null;
  let saving = false, settingsLoading = false, detailRequest = 0, detailPending = 0, previewKey = '', blocks = [], shown = 0;
  let polishCatalog = {}, modelCatalogs = {}, polishLoading = false, polishError = '', polishRequest = 0;

  function notice(id, message) { $(id).textContent = message; $(id).hidden = !message; }
  function options(id, values, selected, labels = {}) {
    const all = [...new Set([...values, selected].filter(value => value !== undefined && (value !== '' || Object.hasOwn(labels, ''))))];
    $(id).replaceChildren(...all.map(value => { const option = el('option', labels[value] || value); option.value = value; return option; }));
    $(id).value = selected;
  }
  function modelEfforts(selected, target = 'primary') {
    const prefix = target === 'polish' ? 'setting-polish-' : 'setting-';
    const info = target === 'polish' ? polishCatalog : catalog;
    const efforts = info.capabilities?.[$(prefix + 'model').value]?.reasoning_efforts || [];
    const values = ['auto', ...efforts];
    options(prefix + 'effort', values, selected, effortNames);
    $(prefix + 'effort').disabled = efforts.length === 0 && selected === 'auto';
  }
  async function loadPolishModels(model = '', effort = 'auto') {
    const ticket = ++polishRequest, provider = $('setting-polish-provider').value;
    polishError = ''; polishLoading = !!provider;
    $('polish-model-fields').hidden = !provider;
    $('setting-polish-model').required = !!provider;
    $('setting-polish-model').disabled = true; $('setting-polish-effort').disabled = true;
    $('polish-loading').hidden = !provider; $('polish-reload').hidden = true; notice('polish-error', '');
    $('polish-hint').textContent = provider ? '可独立选择润色模型。每篇或每批字幕会增加一次模型调用和处理时间；保存后用于后续任务。' : '未启用独立润色，翻译后仍会进行质量复核。';
    options('setting-polish-model', [], model, {'':'请选择模型'});
    options('setting-polish-effort', ['auto'], effort, effortNames);
    settingsState();
    try {
      if (!provider) return;
      const info = modelCatalogs[provider] || await request('models/' + encodeURIComponent(provider));
      if (ticket !== polishRequest) return;
      modelCatalogs[provider] = info; polishCatalog = info;
      const selected = model || info.models?.[0] || '';
      if (!selected) throw Error('暂无可用润色模型，请重试或选择其他服务。');
      options('setting-polish-model', info.models || [], selected);
      modelEfforts(effort, 'polish');
    } catch (e) {
      if (ticket === polishRequest) { polishError = e.message; notice('polish-error', e.message); $('polish-reload').hidden = false; }
    } finally {
      if (ticket === polishRequest) {
        polishLoading = false; $('polish-loading').hidden = true;
        $('setting-polish-model').disabled = !provider || !!polishError;
        if (!provider || polishError) $('setting-polish-effort').disabled = true;
        settingsState();
      }
    }
  }
  function changes() {
    const patch = {};
    if (!settings) return patch;
    for (const [id, [section, key]] of Object.entries(fields)) {
      const input = $(id);
      const value = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
      if (value !== settings[section]?.[key]) (patch[section] ||= {})[key] = value;
    }
    return patch;
  }
  function dirty() { return Object.keys(changes()).length > 0; }
  function settingsState(s = serverStatus) {
    serverStatus = s;
    $('settings-fields').disabled = saving || !settings;
    $('settings-save').disabled = saving || !settings || polishLoading || !!polishError || !dirty();
    $('settings-reset').disabled = saving || !settings || !dirty();
    const update = s?.model_settings;
    const current = [update?.current_model, effortNames[update?.current_effort]].filter(Boolean).join(' · ');
    const currentPolish = update?.current_polish_provider ? [providerNames[update.current_polish_provider] || update.current_polish_provider, update.current_polish_model || update.current_model, effortNames[update.current_polish_effort]].filter(Boolean).join(' · ') : '未启用';
    notice('settings-availability', update?.error || (update?.pending ? '新设置已保存，等待生效。当前翻译：' + current + '；当前润色：' + currentPolish + '。正在处理的任务完成并保存字幕后，自动应用新设置。' : '可以随时修改并保存。正在处理的任务继续使用原设置，新设置用于后续任务。'));
    if (update && !update.pending && !dirty() && $('settings-feedback').textContent.startsWith('已保存')) $('settings-feedback').textContent = '设置已生效';
  }
  function populate() {
    for (const [id, [section, key]] of Object.entries(fields)) {
      const input = $(id), value = settings[section]?.[key];
      if (id === 'setting-model' || id === 'setting-effort' || id.startsWith('setting-polish-')) continue;
      if (input.type === 'checkbox') input.checked = !!value;
      else if (input.tagName === 'SELECT') options(id, [...input.options].map(o => o.value), value);
      else input.value = value;
    }
    options('setting-model', catalog.models || [], settings.translation.primary_model);
    modelEfforts(settings.translation.primary_effort);
    const provider = settings.translation.primary_provider;
    const polishProvider = settings.translation.polish_provider || '';
    const providers = Object.keys(providerNames).filter(name => name === provider || name === polishProvider || settings.credentials_configured?.[name]);
    options('setting-polish-provider', ['', ...providers], polishProvider, {'':'不启用', ...providerNames});
    loadPolishModels(settings.translation.polish_model || '', settings.translation.polish_effort || 'auto');
    $('provider-label').textContent = providerNames[provider] || provider;
    $('asr-backend').textContent = settings.asr.backend;
    $('settings-feedback').textContent = '尚未修改';
    settingsState();
  }
  async function loadSettings() {
    if (settingsLoading) return;
    settingsLoading = true;
    notice('settings-error', ''); $('settings-reload').hidden = true; $('settings-loading').hidden = false;
    try {
      const result = await api('settings'), config = result.settings;
      const models = await request('models/' + encodeURIComponent(config.translation.primary_provider));
      settings = config; catalog = models; modelCatalogs = {[config.translation.primary_provider]:models}; serverStatus = {...serverStatus, model_settings:result.state};
      populate(); $('settings-form').hidden = false;
    } catch (e) { notice('settings-error', e.message); $('settings-reload').hidden = false; }
    finally { settingsLoading = false; $('settings-loading').hidden = true; }
  }
  $('setting-model').onchange = () => {
    const efforts = catalog.capabilities?.[$('setting-model').value]?.reasoning_efforts || [];
    const current = $('setting-effort').value;
    modelEfforts(current === 'auto' || efforts.includes(current) ? current : 'auto');
  };
  $('setting-polish-provider').onchange = () => {
    const provider = $('setting-polish-provider').value;
    const current = provider && provider === settings.translation.polish_provider;
    const primary = provider && provider === settings.translation.primary_provider;
    return loadPolishModels(current ? settings.translation.polish_model : primary ? $('setting-model').value : '', current ? settings.translation.polish_effort : primary ? $('setting-effort').value : 'auto');
  };
  $('setting-polish-model').onchange = () => {
    const efforts = polishCatalog.capabilities?.[$('setting-polish-model').value]?.reasoning_efforts || [];
    const current = $('setting-polish-effort').value;
    modelEfforts(current === 'auto' || efforts.includes(current) ? current : 'auto', 'polish');
  };
  $('polish-reload').onclick = () => loadPolishModels($('setting-polish-model').value, $('setting-polish-effort').value);
  $('settings-form').addEventListener('input', () => { $('settings-feedback').textContent = dirty() ? '有未保存的更改' : '尚未修改'; settingsState(); });
  $('settings-form').addEventListener('change', () => { $('settings-feedback').textContent = dirty() ? '有未保存的更改' : '尚未修改'; settingsState(); });
  $('settings-reset').onclick = () => { populate(); notice('settings-error', ''); };
  $('settings-reload').onclick = loadSettings;
  $('settings-form').onsubmit = async event => {
    event.preventDefault();
    if (saving || !settings || polishLoading || polishError || !dirty() || !$('settings-form').reportValidity()) return;
    saving = true; settingsState(); notice('settings-error', ''); $('settings-save').textContent = '正在保存…';
    try {
      const patch = changes();
      const result = await api('settings', patch);
      settings = result.settings;
      serverStatus = {...serverStatus, model_settings:result.state};
      populate();
      $('settings-feedback').textContent = result.state.pending ? '已保存，等待当前任务结束后生效' : '设置已生效';
    } catch (e) { notice('settings-error', e.message); }
    finally { saving = false; $('settings-save').textContent = '保存设置'; settingsState(); }
  };
  window.addEventListener('beforeunload', event => { if (dirty()) { event.preventDefault(); event.returnValue = ''; } });

  function fact(label, value) {
    if (value) $('project-facts').append(el('dt', label), el('dd', value));
  }
  function renderProject(project, progress, workflow) {
    $('project-title').textContent = project.name || '翻译详情';
    $('project-meta').textContent = [project.show_title, project.tmdb_id ? 'TMDB ' + project.tmdb_id : '', project.target_language].filter(Boolean).join(' · ');
    const states = {created:'待处理', ready:'已就绪', processing:'处理中', asr_done:'识别完成', completed:'已完成', translated:'翻译完成', error:'需要处理', cancelled:'已停止'};
    $('project-state').textContent = states[project.status] || project.status || '待处理';
    $('project-progress-text').textContent = project.status === 'cancelled' ? '任务已停止，保留上次进度' : progress.message || '暂无进度信息';
    $('project-progress').value = Math.max(0, Math.min(100, Number(progress.progress) || 0));
    $('project-facts').replaceChildren();
    fact('视频路径', project.video_path); fact('目标语言', project.target_language);
    fact('影视信息', project.tmdb_id ? [project.show_title, 'TMDB ' + project.tmdb_id, project.metadata_source].filter(Boolean).join(' · ') : '尚未关联');
    fact('最近更新', progress.updated_at ? new Date(progress.updated_at).toLocaleString() : '');
    const stageNames = {asr:'语音识别', translate:'翻译与复核', burn:'字幕压制', download:'下载', subtitle_extract:'提取字幕', filter:'整理字幕', export:'保存字幕'};
    const stageStates = {pending:'等待中', running:'进行中', succeeded:'已完成', completed:'已完成', failed:'失败', cancelled:'已暂停', queued:'排队中', skipped:'已跳过'};
    $('project-stages').replaceChildren();
    for (const [name, stage] of Object.entries(workflow.stages || {})) {
      const item = el('li'); item.append(el('strong', stageNames[name] || name), el('span', stageStates[stage.status] || stage.status));
      if (stage.error_summary) item.append(el('p', stage.error_summary, 'failure-text'));
      if (stage.log_path) { const link = el('a', '下载日志'); link.href = '/api/projects/' + pid + '/logs/' + encodeURIComponent(name); item.append(link); }
      $('project-stages').append(item);
    }
    if (!$('project-stages').children.length) $('project-stages').append(el('li', '任务尚未开始处理。'));
  }
  function showMoreSubtitles() {
    const end = Math.min(shown + 40, blocks.length);
    for (const block of blocks.slice(shown, end)) {
      const row = el('div', undefined, 'subtitle-row');
      row.append(el('span', String(block.index), 'subtitle-number'));
      const text = el('div'); text.append(el('p', block.text || '', 'subtitle-source'));
      if (block.translation) text.append(el('p', block.translation, 'subtitle-translation'));
      row.append(text); $('subtitle-preview').append(row);
    }
    shown = end; $('subtitle-more').hidden = shown >= blocks.length;
    $('subtitle-count').textContent = blocks.length ? shown + ' / ' + blocks.length + ' 条' : '';
  }
  async function loadProject(initial = false) {
    // Polls wait for this request; explicit navigation/reload may supersede it.
    if (!initial && detailPending) return;
    const id = pid, ticket = ++detailRequest;
    detailPending = ticket;
    if (initial) { $('project-loading').hidden = false; $('project-content').hidden = true; $('project-title').textContent = '翻译详情'; $('project-meta').textContent = ''; }
    $('project-reload').hidden = true; notice('project-error', '');
    try {
      const [project, progress, workflow] = await Promise.all(['', '/progress', '/workflow-state'].map(suffix => request('projects/' + id + suffix)));
      if (ticket !== detailRequest || panel !== 'project') return;
      renderProject(project, progress, workflow); $('project-content').hidden = false;
      // Refresh the certified preview when a task changes state, without resetting reading position on each poll.
      const key = id + ':' + project.status;
      if (key !== previewKey) {
        blocks = []; shown = 0; $('subtitle-preview').replaceChildren(); $('subtitle-count').textContent = ''; $('subtitle-more').hidden = true;
        notice('subtitle-message', '正在读取字幕…');
        try {
          const result = await request('projects/' + id + '/subtitles');
          if (ticket !== detailRequest || panel !== 'project') return;
          blocks = result.blocks || []; previewKey = blocks.length ? key : '';
          notice('subtitle-message', blocks.length ? '' : '字幕尚未生成，处理完成后会在这里显示。'); showMoreSubtitles();
        } catch (e) {
          if (ticket !== detailRequest || panel !== 'project') return;
          notice('subtitle-message', e.status === 409 ? '字幕正在生成或等待质量检查，通过后可预览。' : '字幕暂时无法读取，将自动重试。');
        }
      }
    } catch (e) { if (ticket === detailRequest && panel === 'project') { notice('project-error', e.message); $('project-reload').hidden = false; } }
    finally { if (ticket === detailRequest) $('project-loading').hidden = true; if (ticket === detailPending) detailPending = 0; }
  }
  $('subtitle-more').onclick = showMoreSubtitles;
  $('project-reload').onclick = () => { previewKey = ''; loadProject(true); };
  function route(focus = true) {
    const match = /^#project\/([a-f0-9]{8})$/.exec(location.hash);
    panel = match ? 'project' : location.hash === '#settings' ? 'settings' : location.hash === '#knowledge' ? 'knowledge' : 'tasks';
    pid = match ? match[1] : ''; detailRequest++;
    for (const name of ['tasks', 'settings', 'project', 'knowledge']) $('panel-' + name).hidden = name !== panel;
    for (const name of ['tasks', 'settings', 'knowledge']) {
      if (name === (panel === 'project' ? 'tasks' : panel)) $('nav-' + name).setAttribute('aria-current', 'page');
      else $('nav-' + name).removeAttribute('aria-current');
    }
    document.title = (panel === 'settings' ? '模型设置' : panel === 'project' ? '翻译详情' : panel === 'knowledge' ? '知识库' : '字幕任务') + ' · AI Sub Pro';
    if (focus) $(panel + '-title').focus({preventScroll:true});
    if (panel === 'settings' && !settings) loadSettings();
    if (panel === 'knowledge') window.LibraryKnowledge?.open();
    if (panel === 'project') { previewKey = ''; loadProject(true); window.LibraryKnowledge?.project(pid); }
  }
  window.LibraryPanels = {statusChanged:settingsState};
  window.addEventListener('hashchange', () => route());
  setInterval(() => { if (panel === 'project' && !document.hidden) loadProject(); }, 10000);
  route(false);
})();
