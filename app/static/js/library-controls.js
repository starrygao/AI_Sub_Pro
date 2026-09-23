'use strict';
(() => {
  const selected=new Map();let visible=[],busy=false,pendingCancel=[];
  const labels={pause:'暂停',resume:'继续',cancel:'取消'};
  function state(){
    $('task-selection-count').textContent='已选 '+selected.size+' 项 · 最多 100 项';
    for(const action of Object.keys(labels))$('tasks-'+action).disabled=busy||!selected.size||![...selected.values()].every(r=>r.available_actions.includes(action));
    $('tasks-clear').disabled=busy||!selected.size;
    $('task-select-page').disabled=busy||!visible.length;
    $('task-select-page').checked=!!visible.length&&visible.every(r=>selected.has(r.path));
    $('task-select-page').indeterminate=visible.some(r=>selected.has(r.path))&&!$('task-select-page').checked;
  }
  function sync(rows){
    visible=rows.filter(r=>r.available_actions?.length);
    for(const row of rows){if(selected.has(row.path)){if(!row.available_actions?.length||selected.get(row.path).control_revision!==row.control_revision)selected.delete(row.path);else selected.set(row.path,{...row});}}
    state();
  }
  async function perform(action,rows){
    if(busy)return;busy=true;state();$('task-action-errors').hidden=true;$('task-action-feedback').textContent='正在提交'+labels[action]+'请求…';
    rowsSignature='';await refresh();
    try{
      const result=await api('tasks/control',{action,items:rows.map(r=>({path:r.path,revision:r.control_revision}))});
      const failures=result.results.filter(r=>!r.ok),success=result.results.length-failures.length;
      for(const r of result.results)if(r.ok)selected.delete(r.path);
      $('task-action-feedback').textContent='已接受 '+success+' 项'+labels[action]+'请求'+(failures.length?'，'+failures.length+' 项未执行':'')+'。运行中任务将在安全退出后更新状态。';
      $('task-action-errors').replaceChildren(...failures.map(r=>el('li',r.path.split('/').pop()+'：'+r.error)));$('task-action-errors').hidden=!failures.length;
    }catch(e){$('task-action-feedback').textContent='操作失败：'+e.message+' 已保留选择，可重试。';}
    finally{busy=false;state();rowsSignature='';await refresh();}
  }
  function act(action,rows){
    if(busy)return;
    if(action!=='cancel')return perform(action,rows);
    pendingCancel=rows.slice();$('task-cancel-description').textContent='将取消 '+rows.length+' 项任务，取消后不再自动处理。';
    $('task-cancel-items').replaceChildren(...rows.map(r=>el('li',taskTitle(r).title+' '+taskTitle(r).episode)));
    $('task-cancel-dialog').showModal();$('task-cancel-back').focus();
  }
  function redraw(){rowsSignature='';return refresh();}
  function render(row,side,focusable){
    if(!row.available_actions?.length)return;
    const label=el('label',undefined,'task-select'),input=el('input');input.type='checkbox';input.checked=selected.has(row.path);input.disabled=busy;
    input.setAttribute('aria-label','选择 '+taskTitle(row).title+' '+taskTitle(row).episode);
    input.onchange=()=>{if(input.checked){if(selected.size>=100){input.checked=false;$('task-action-feedback').textContent='每批最多选择 100 项。';return;}selected.set(row.path,{...row});}else selected.delete(row.path);state();};
    label.append(focusable(input,'select'),el('span','选择'));side.append(label);
    const actions=el('div',undefined,'row-actions');
    for(const action of row.available_actions){const button=el('button',labels[action],'secondary');button.disabled=busy;button.onclick=()=>act(action,[row]);actions.append(focusable(button,action));}
    side.append(actions);
  }
  for(const action of Object.keys(labels))$('tasks-'+action).onclick=()=>act(action,[...selected.values()]);
  $('tasks-clear').onclick=()=>{selected.clear();state();return redraw();};
  $('task-select-page').onchange=()=>{if($('task-select-page').checked){for(const row of visible)if(selected.size<100)selected.set(row.path,{...row});}else for(const row of visible)selected.delete(row.path);state();return redraw();};
  $('task-cancel-back').onclick=()=>{$('task-cancel-dialog').close();pendingCancel=[];};
  $('task-cancel-confirm').onclick=()=>{const rows=pendingCancel;pendingCancel=[];$('task-cancel-dialog').close();return perform('cancel',rows);};
  window.LibraryControls={sync,render};rowsSignature='';refresh();
})();
