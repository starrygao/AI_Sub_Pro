'use strict';
(() => {
  const categories={characters:'人物',places:'地点',brands:'机构 / 品牌',slang:'其他术语'};
  let entries={},selected='',editingSnapshot=null,loaded=false,loading=false,saving=false,dirty=false,projectTicket=0,readTicket=0;
  const notice=(id,text)=>{$(id).textContent=text;$(id).hidden=!text;};
  function term(category='characters',value={}){
    const row=el('div',undefined,'kb-term'),select=el('select');select.setAttribute('aria-label','术语分类');
    for(const [key,label] of Object.entries(categories)){const option=el('option',label);option.value=key;select.append(option);}select.value=category;row.append(select);
    for(const [key,label] of [['source','原文'],['target','审定译文'],['notes','备注']]){const input=el('input');input.value=value[key]||'';input.placeholder=label;input.setAttribute('aria-label',label);input.required=key!=='notes';row.append(input);}
    const remove=el('button','移除','secondary');remove.type='button';remove.setAttribute('aria-label','移除此行术语');remove.onclick=()=>{row.remove();changed();};row.append(remove);$('kb-terms').append(row);
  }
  function changed(){dirty=true;$('kb-feedback').textContent='有未保存的更改';}
  function list(){
    $('kb-list').replaceChildren();
    for(const [key,value] of Object.entries(entries)){
      const button=el('button',value.show_title||key,'kb-select');button.type='button';button.setAttribute('aria-pressed',String(selected===key));
      button.onclick=()=>{if(dirty){notice('kb-error','请先保存当前更改，再选择另一部作品。');return;}edit(key);};$('kb-list').append(button);
    }
    if(!Object.keys(entries).length)$('kb-list').append(el('p','还没有影视知识库。可以新建，也可以在任务详情中确认自动候选。','hint'));
  }
  function edit(key='',focus=true){
    if(key&&!entries[key]){selected='';editingSnapshot=null;dirty=false;$('kb-form').hidden=true;list();return;}
    selected=key;dirty=false;const value=entries[key]||{};notice('kb-error','');$('kb-form').hidden=false;$('kb-form-title').textContent=key?'编辑影视知识库':'新建影视知识库';
    editingSnapshot=key?JSON.parse(JSON.stringify(value)):null;
    for(const [id,text] of [['kb-name',value.show_title],['kb-tmdb',value.tmdb_id],['kb-tone',value.style_notes?.tone],['kb-perspective',value.style_notes?.perspective],['kb-rules',(value.style_notes?.rules||[]).join('\n')]])$(id).value=text||'';
    $('kb-type').value=value.tmdb_type||'';$('kb-terms').replaceChildren();for(const category of Object.keys(categories))for(const value of entries[key]?.[category]||[])term(category,value);
    $('kb-feedback').textContent='';list();if(focus)$('kb-name').focus();
  }
  async function open(afterSave=false){
    if(loading||(saving&&!afterSave))return;const ticket=++readTicket;loading=true;$('kb-new').disabled=true;notice('kb-error','');$('kb-reload').hidden=true;
    try{
      const [all,info]=await Promise.all([request('knowledge'),api('knowledge')]);
      if(ticket!==readTicket)return;
      entries=all;list();loaded=true;
      if(!dirty&&selected)edit(selected,false);
      $('kb-overview').textContent=info.projects+' 部作品 · '+info.terms+' 条审定术语 · '+info.memory_entries+' 条人工修订记忆 · '+info.phrase_entries+' 条短语范例'+(info.memory_enabled?'':' · 翻译记忆已关闭');
      $('kb-pending').replaceChildren();for(const item of info.pending){const link=el('a',item.name+' · '+item.count+' 条候选','kb-pending-link');link.href='#project/'+encodeURIComponent(item.project_id);$('kb-pending').append(link);}if(!info.pending.length)$('kb-pending').append(el('p','暂无待确认候选。新任务提取术语后会显示在这里。','hint'));
      $('kb-storage').replaceChildren();for(const [key,label] of [['knowledge','影视知识库'],['data','翻译记忆与短语库'],['projects','任务文件与音频中间文件'],['temporary','临时目录'],['models','模型缓存']])$('kb-storage').append(el('dt',label),el('dd',info.storage[key]));
    }catch(e){if(ticket===readTicket){notice('kb-error',e.message);$('kb-reload').hidden=false;}}
    finally{if(ticket===readTicket){loading=false;$('kb-new').disabled=saving||!loaded;}}
  }
  $('kb-new').disabled=true;
  $('kb-new').onclick=()=>{if(dirty){notice('kb-error','请先保存当前更改。');return;}edit();};$('kb-reload').onclick=()=>open();
  $('kb-add-term').onclick=()=>{term();changed();};$('kb-form').addEventListener('input',changed);$('kb-form').addEventListener('change',changed);
  $('kb-form').onsubmit=async event=>{
    event.preventDefault();if(saving||!loaded||!$('kb-form').reportValidity())return;
    const id=$('kb-tmdb').value?Number($('kb-tmdb').value):null,kind=$('kb-type').value,name=$('kb-name').value.trim();
    if(!name){notice('kb-error','请填写影视名称。');return;}
    const duplicate=Object.entries(entries).find(([key,value])=>key!==selected&&((id&&value.tmdb_id===id&&(!value.tmdb_type||!kind||value.tmdb_type===kind))||(!id&&!value.tmdb_id&&value.show_title?.trim().toLocaleLowerCase()===name.toLocaleLowerCase())));
    if(duplicate){notice('kb-error','该作品已有知识库，请在左侧编辑已有条目。');return;}
    const key=selected||'kb-'+Date.now().toString(36)+Math.random().toString(36).slice(2,10);
    const data={key,show_title:name,tmdb_id:id,tmdb_type:kind,style_notes:{tone:$('kb-tone').value,perspective:$('kb-perspective').value,rules:$('kb-rules').value.split('\n').filter(s=>s.trim())}};
    if(selected&&editingSnapshot)data.expected_state=editingSnapshot;
    for(const category of Object.keys(categories))data[category]=[];
    for(const row of $('kb-terms').children){const [category,source,target,notes]=row.children;if(!source.value.trim()||!target.value.trim()){notice('kb-error','每条术语都需要原文和审定译文。');return;}data[category.value].push({source:source.value.trim(),target:target.value.trim(),notes:notes.value.trim()});}
    // Invalidate reads begun before this write; their success/error/finally must
    // not replace the committed editor or interfere with the fresh post-save read.
    saving=true;++readTicket;loading=false;$('kb-new').disabled=true;$('kb-fields').disabled=true;$('kb-save').disabled=true;notice('kb-error','');
    try{const result=await request('knowledge/projects/'+encodeURIComponent(key),data,'PUT');entries[key]=result.project||data;selected=key;dirty=false;edit(key,false);await open(true);$('kb-feedback').textContent='已保存，后续同一作品的任务会自动采用';}
    catch(e){if(e.status===409)await open(true);notice('kb-error',e.message);}finally{saving=false;$('kb-new').disabled=loading||!loaded;$('kb-fields').disabled=false;$('kb-save').disabled=false;}
  };
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  $('kb-reset').onclick=()=>edit(selected);
  async function project(pid){
    const ticket=++projectTicket;$('project-kb-suggestions').replaceChildren();$('project-kb-status').textContent='正在读取术语建议…';
    try{
      const [result,usage]=await Promise.all([request('knowledge/projects/'+pid+'/suggestions'),request('knowledge/projects/'+pid+'/usage-trace')]);
      if(ticket!==projectTicket||location.hash!=='#project/'+pid)return;
      const pending=(result.suggestions||[]).filter(item=>item.status!=='rejected');
      $('project-kb-status').textContent='本次记录：术语引用 '+(usage.kb_hits?.length||usage.matches?.length||0)+' 条，修订记忆 '+(usage.memory_hits?.length||0)+' 条。候选需确认译文后才会入库。';
      for(const item of pending){
        const row=el('div',undefined,'kb-candidate'),source=el('strong',item.source),target=el('input'),save=el('button',item.status==='accepted'?'已入库':'确认入库'),reject=el('button','忽略','secondary');target.value=item.target||'';target.placeholder='填写审定译文';target.setAttribute('aria-label',item.source+' 的审定译文');
        const meta=el('span',(categories[item.category]||'术语')+(item.notes?' · '+item.notes:''),'hint');
        save.disabled=item.status==='accepted';reject.disabled=item.status==='accepted';target.disabled=item.status==='accepted';
        async function update(status){if(status==='accepted'&&!target.value.trim()){target.focus();$('project-kb-status').textContent='确认前请填写译文。';return;}save.disabled=true;reject.disabled=true;try{await request('knowledge/projects/'+pid+'/suggestions/'+encodeURIComponent(item.id)+'/status',{status,target:target.value.trim()});await project(pid);}catch(e){$('project-kb-status').textContent=e.message;save.disabled=false;reject.disabled=false;}}
        save.onclick=()=>update('accepted');reject.onclick=()=>update('rejected');row.append(source,target,save,reject,meta);$('project-kb-suggestions').append(row);
      }
      if(!pending.length)$('project-kb-suggestions').append(el('p','暂无候选术语。可以在知识库页面手动添加审定术语。','hint'));
    }catch(e){if(ticket===projectTicket)$('project-kb-status').textContent='术语建议暂时无法读取：'+e.message;}
  }
  window.LibraryKnowledge={open,project};
})();
