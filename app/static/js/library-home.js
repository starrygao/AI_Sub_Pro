'use strict';
(() => {
  let pending = false, signature = '';
  const sum = (counts, states) => states.reduce((total, state) => total + (counts[state] || 0), 0);
  const activeStates = ['translating', 'publishing', 'pausing', 'cancelling'];
  const attentionStates = ['error', 'changed', 'missing'];
  const number = value => Number(value || 0).toLocaleString();
  function link(text, viewName = 'processed', state = '') {
    const node = el('a', text); node.href = '#tasks';
    node.onclick = () => { selectView(viewName); if (state) { $('filter').value = state; refresh(); } };
    return node;
  }
  function taskLink(row, text = '查看详情 →') {
    if (/^[a-f0-9]{8}$/.test(row.project_id || '')) { const a = el('a', text); a.href = '#project/' + row.project_id; return a; }
    return link('查看任务 →', row.state === 'ready' ? 'ready' : 'processed', row.state);
  }
  function renderActive(rows, total) {
    const cards = rows.map(row => {
      const card = el('article', undefined, 'home-active-task'), info = taskTitle(row), top = el('div', undefined, 'home-active-top');
      const title = el('div', undefined, 'home-active-title');
      title.append(el('h3', info.title), el('span', info.episode, 'task-episode'), el('p', progressLabel(row), 'home-stage'));
      top.append(taskArtwork(row), title); card.append(top);
      const progress = row.progress || {}, known = typeof progress.progress === 'number' && Number.isFinite(progress.progress);
      const line = el('div', undefined, 'home-progress-line');
      line.append(el('span', progress.message || row.reason || '等待阶段信息'), el('strong', known ? Math.round(Math.max(0, Math.min(100, progress.progress))) + '%' : '进度待更新'));
      card.append(line);
      if (known) { const bar = el('progress'); bar.max = 100; bar.value = Math.max(0, Math.min(100, progress.progress)); bar.setAttribute('aria-label', '整体流程进度'); card.append(bar); }
      const foot = el('div', undefined, 'home-active-footer'); foot.append(el('span', '提取 · 翻译与复核 · 保存', 'hint'), taskLink(row)); card.append(foot);
      return card;
    });
    if (!rows.length) cards.push(el('p', '当前没有正在处理的任务。符合条件的视频会在自动翻译开启后依次处理。', 'home-empty'));
    if (total > rows.length) cards.push(link('显示 ' + rows.length + ' / ' + total + ' 项 · 查看全部'));
    $('home-active').replaceChildren(...cards);
  }
  function modelText(values, stage) {
    const provider = values[stage + '_provider'], model = values[stage + '_model'], effort = values[stage + '_effort'];
    if (provider === 'disabled') return '未启用';
    if (!provider) return '未配置';
    const strength = {none:'无', minimal:'最低', low:'低', medium:'中', high:'高', xhigh:'超高', max:'最高', ultra:'极高'}[effort] || effort;
    return (model || provider) + (strength ? ' · ' + strength : '');
  }
  function render(data) {
    const counts = data.counts, active = sum(counts, activeStates), attention = sum(counts, attentionStates);
    const metrics = [ ['已保存字幕', counts.done || 0, '当前保留的交付记录', 'processed', 'done'], ['处理中', active, '正在处理的任务', 'processed', ''], ['待翻译', counts.ready || 0, '已完成检测，等待翻译', 'ready', ''], ['需关注', attention, '需要处理的问题', 'processed', ''], ['待检测', counts.waiting || 0, '新发现文件，等待检测', 'waiting', ''] ];
    $('home-metrics').replaceChildren(...metrics.map(([title, value, hint, viewName, state]) => { const item = link('', viewName, state); item.append(el('span', title), el('strong', number(value)), el('small', hint)); return item; }));
    $('home-active-count').textContent = active + ' 项'; renderActive(data.active, active);
    const days = data.deliveries.days, maximum = Math.max(1, ...days.map(day => day.count));
    $('home-week-total').textContent = number(days.reduce((total, day) => total + day.count, 0));
    $('home-range').textContent = days[0].date.slice(5).replace('-', '/') + ' – ' + days.at(-1).date.slice(5).replace('-', '/');
    $('home-chart').setAttribute('aria-label', '每日交付：' + days.map(day => day.date + ' ' + day.count + ' 份').join('；'));
    $('home-chart').replaceChildren(...days.map(day => { const col = el('div', undefined, 'home-chart-column'), track = el('div', undefined, 'home-chart-track'), bar = el('div', undefined, 'home-chart-bar'); bar.style.height = (day.count / maximum * 100) + '%'; track.append(bar); col.append(el('span', String(day.count)), track, el('small', day.date.slice(5).replace('-', '/'))); return col; }));
    $('home-delivery-note').textContent = '按 ' + data.deliveries.timezone + ' 的完成日期统计。' + (data.deliveries.undated ? data.deliveries.undated + ' 份记录无有效完成时间，未计入趋势。' : '仅统计当前保留的交付记录。');
    $('home-queue-count').textContent = '显示 ' + data.queue.length + ' / ' + (counts.ready || 0) + ' 项';
    $('home-queue').replaceChildren(...(data.queue.length ? data.queue.map((row, index) => { const item = el('article', undefined, 'home-queue-row'), info = taskTitle(row), title = el('div'); title.append(el('h3', info.title), el('span', info.episode, 'hint')); item.append(el('span', String(index + 1), 'home-row-number'), taskArtwork(row), title, taskLink(row, '查看任务 →')); return item; }) : [el('p', '暂无等待翻译的任务。', 'home-empty')]));
    $('home-attention-count').textContent = attention + ' 项';
    const explanations = {error:'处理未完成，请查看错误详情后重试。', changed:'源视频已变化，需要重新检查。', missing:'源视频暂时不可读，请检查文件位置或挂载。'};
    $('home-attention').replaceChildren(...(attention ? attentionStates.filter(state => counts[state]).map(state => { const box = el('div', undefined, 'home-attention-row'); box.append(link(counts[state] + ' 项 · ' + names[state], 'processed', state), el('p', explanations[state])); return box; }) : [el('p', '暂无需要处理的问题。', 'home-empty')]));
    const models = data.models, columns = el('div', undefined, 'home-model-columns');
    for (const [key, title] of [['current', '当前生效'], ['desired', models.pending ? '后续任务 · 待生效' : '后续任务配置']]) { const column = el('div'); column.append(el('h3', title)); for (const [stage, label] of [['primary','初译'], ['polish','润色'], ['review','复核']]) { const row = el('p'); row.append(el('span', label), el('strong', modelText(models[key], stage))); column.append(row); } columns.append(column); }
    $('home-models').replaceChildren(columns);
    if (models.pending) $('home-models').append(el('p', '已保存新配置，等待当前任务结束后生效。', 'hint'));
    if (models.error) $('home-models').append(el('p', models.error, 'failure-text'));
  }
  function runtime() {
    $('home-automation').textContent = status.enabled === undefined ? '运行状态暂不可用' : status.enabled ? '● 自动翻译已开启' : '○ 自动翻译已暂停';
    $('home-connection').textContent = $('connection-summary').textContent;
  }
  async function load() {
    if (pending || $('panel-home').hidden) return;
    pending = true;
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
      const data = await api('overview?timezone=' + encodeURIComponent(timezone));
      // Keep focused links and cached artwork stable during polling.
      const next = JSON.stringify({...data, generated_at: 0});
      if (next !== signature) { render(data); signature = next; }
      $('home-content').hidden = false; $('home-error').hidden = true; $('home-retry').hidden = true;
      $('home-updated').textContent = '最近更新 ' + new Date(data.generated_at * 1000).toLocaleTimeString() + ' · 每 5 秒刷新';
    } catch (e) {
      $('home-error').textContent = '概览暂时无法更新：' + e.message + (signature ? ' 下方保留上次成功读取的数据。' : '');
      $('home-error').hidden = false; $('home-retry').hidden = false;
    } finally { pending = false; $('home-loading').hidden = true; runtime(); }
  }
  $('home-date').textContent = new Date().toLocaleDateString('zh-CN', {year:'numeric', month:'long', day:'numeric', weekday:'long'});
  for (const a of document.querySelectorAll('.home-task-link')) a.onclick = () => selectView(a.dataset.view);
  $('home-add').onclick = () => $('emby-open').click();
  $('emby-dialog').addEventListener('close', () => { if (!$('panel-home').hidden) $('home-add').focus(); });
  $('home-retry').onclick = load;
  window.LibraryHome = {refresh: load};
  setInterval(() => { runtime(); if (!document.hidden) load(); }, 5000);
  load();
})();
