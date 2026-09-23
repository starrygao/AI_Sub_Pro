'use strict';
(() => {
  let data=null,busy=false,dirty=false,ticket=0;
  const bytes=value=>value>=1024**3?(value/1024**3).toFixed(2)+' GB':value>=1024**2?(value/1024**2).toFixed(1)+' MB':Math.round(value/1024)+' KB';
  function state(){
    $('cleanup-limit').disabled=busy||!data;
    $('cleanup-save').disabled=busy||!data||(!dirty&&data.enabled);
    $('cleanup-pause').hidden=!data?.enabled;$('cleanup-pause').disabled=busy;
    $('cleanup-refresh').disabled=busy;
  }
  function show(result){
    data=result;if(!dirty)$('cleanup-limit').value=result.limit_gb;
    $('cleanup-limit').min=result.minimum_gb;
    $('cleanup-summary').textContent=(result.enabled?'自动清理已启用':'自动清理未启用')+' · 过程文件 '+bytes(result.managed_bytes)+' · 可清理 '+bytes(result.eligible_bytes)+' · 受保护 '+bytes(result.protected_bytes);
    const last=result.last_run||{};
    const messages={error:'清理暂未完成，稍后重试；字幕处理会继续。',below_limit:'尚未超过占用上限，未删除文件。',busy:'当前有任务或目录迁移，清理已延后。',protected_remaining:'已保留仍在保护范围内的文件，不会为达到上限扩大删除范围。',cleaned:'已清理 '+(last.removed_files||0)+' 个过程文件，释放 '+bytes(last.freed_bytes||0)+'。'};
    $('cleanup-feedback').textContent=(messages[last.status]||'保存并启用后，后台按占用上限检查。')+(last.errors?' 部分文件清理失败，已保留。':'');
  }
  function error(message){$('cleanup-error').textContent=message;$('cleanup-error').hidden=!message;}
  async function load(){
    if(busy)return;const request=++ticket;busy=true;state();error('');
    try{const result=await api('cleanup');if(request===ticket)show(result);}
    catch(e){if(request===ticket)error(e.message);}
    finally{if(request===ticket){busy=false;state();}}
  }
  async function save(enabled){
    if(busy||!data)return;
    if(enabled&&!$('cleanup-form').reportValidity())return;
    const value=enabled?Number($('cleanup-limit').value):data.limit_gb;
    busy=true;state();error('');
    try{const result=await api('cleanup',{enabled,limit_gb:value});dirty=false;show(result);$('cleanup-feedback').textContent=enabled?'已保存，后台将检查过程文件占用；有运行任务时等待任务结束。':'自动清理已暂停。';}
    catch(e){error(e.message);}
    finally{busy=false;state();}
  }
  $('cleanup-form').onsubmit=event=>{event.preventDefault();return save(true);};
  $('cleanup-limit').oninput=()=>{dirty=true;state();};
  $('cleanup-pause').onclick=()=>save(false);$('cleanup-refresh').onclick=load;
  const open=()=>{if(location.hash==='#settings'&&!dirty)load();};
  window.addEventListener('hashchange',open);open();
})();
