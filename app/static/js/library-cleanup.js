'use strict';
(() => {
  let data=null,busy=false,dirty=false,ticket=0;
  const bytes=value=>value>=1024**3?(value/1024**3).toFixed(2)+' GB':value>=1024**2?(value/1024**2).toFixed(1)+' MB':value>=1024?Math.round(value/1024)+' KB':value+' B';
  function state(){
    $('cleanup-limit').disabled=busy||!data;
    $('cleanup-save').disabled=busy||!data||(!dirty&&data.enabled);
    $('cleanup-pause').hidden=!data?.enabled;$('cleanup-pause').disabled=busy;
    $('cleanup-refresh').disabled=busy;
  }
  function usage(value){
    if(!value)return;
    $('storage-total').textContent=bytes(value.total_bytes);
    $('storage-disk').textContent=(value.disks||[]).map(d=>'磁盘可用 '+bytes(d.free_bytes)+' / 总容量 '+bytes(d.total_bytes)).join(' · ');
    $('storage-categories').replaceChildren(...(value.categories||[]).map(group=>{const row=el('tr');for(const text of [group.label,bytes(group.bytes),bytes(group.eligible_bytes),String(group.files)])row.append(el('td',text));return row;}));
    const paths=value.paths||{},root=paths.data?.replace(/\/+$/,'');
    const locations=[['数据主目录',paths.data],['影视知识库',root&&root+'/knowledge.json'],
      ['翻译记忆',root&&root+'/translation_memory.sqlite3'],['短语库',root&&root+'/phrase_library.sqlite3'],
      ['任务文件与音频中间文件',root&&root+'/projects'],['临时文件',paths.temporary],['模型缓存',paths.models]];
    $('system-storage').replaceChildren();for(const [label,path] of locations){if(path)$('system-storage').append(el('dt',label),el('dd',path));}
    $('storage-measured').textContent='统计时间 '+new Date(value.measured_at*1000).toLocaleString()+' · 可清理量已排除受保护文件。'+(value.unreadable_entries?' 有 '+value.unreadable_entries+' 项无法读取，统计不完整。':'');
  }
  function show(result){
    usage(result.usage);
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
    catch(e){if(request===ticket){error(e.message);$('storage-measured').textContent=data?'刷新失败，当前显示上次统计。':'统计失败，请点击刷新占用重试。';}}
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
  const open=()=>{if(location.hash==='#system'&&!dirty)load();};
  window.addEventListener('hashchange',open);open();
})();
