'use strict';
(() => {
  let kind='watch', data=null, busy=false, ticket=0, timer=null;
  const notice=(id,text)=>{$(id).textContent=text;$(id).hidden=!text;};
  const payload=()=>kind==='watch'?{roots:$('watch-paths').value.split('\n').map(s=>s.trim()).filter(Boolean)}:Object.fromEntries(['data','temporary','models'].map(key=>[key,$('storage-'+key).value.trim()]));
  const desired=()=>kind==='watch'?{roots:data?.desired||[]}:data?.desired||{};
  const dirty=()=>data&&JSON.stringify(payload())!==JSON.stringify(desired());
  function state(){
    const locked=busy||!data||(kind==='storage'&&(!data.supported||data.phase==='restarting'));
    $('watch-fields').disabled=locked||kind!=='watch';$('storage-fields').disabled=locked||kind!=='storage';
    $('directory-save').disabled=locked||!dirty();$('directory-reset').disabled=locked||!dirty();
  }
  function populate(){
    if(kind==='watch')$('watch-paths').value=(data.desired||[]).join('\n');
    else for(const key of ['data','temporary','models'])$('storage-'+key).value=data.desired?.[key]||'';
    $('directory-allowed').textContent='可选范围：'+(Array.isArray(data.allowed)?data.allowed.join('；'):data.allowed||'尚未配置');
    notice('directory-error',data.error||'');
    $('directory-feedback').textContent=data.pending?(kind==='watch'?'已保存，等待当前任务结束后记录新增文件夹中的现有视频。':'已保存，等待任务结束后迁移并重启；页面会自动重新连接。'):'当前目录已生效';
    state();
  }
  function poll(){
    clearTimeout(timer);
    if($('directory-dialog').open&&data?.pending)timer=setTimeout(()=>load(false),2000);
  }
  async function load(initial=true){
    const request=++ticket;if(initial){busy=true;notice('directory-error','');$('directory-feedback').textContent='正在读取…';state();}
    try{
      const result=(await api('directories'))[kind];if(request!==ticket)return;
      const keep=dirty();data=result;if(!keep||initial)populate();
      $('directory-reload').hidden=true;
      if(!data.pending&&!keep){refresh();if(location.hash==='#knowledge')window.LibraryKnowledge?.open();}
    }catch(e){
      if(request!==ticket)return;
      if(kind==='storage'&&data?.pending)$('directory-feedback').textContent='正在迁移并重启，等待服务恢复…';
      else{notice('directory-error',e.message);$('directory-reload').hidden=false;}
    }finally{if(request===ticket){busy=false;state();poll();}}
  }
  async function open(next){
    kind=next;data=null;clearTimeout(timer);
    $('directory-title').textContent=kind==='watch'?'编辑监控文件夹':'编辑保存位置';
    $('watch-fields').hidden=kind!=='watch';$('storage-fields').hidden=kind!=='storage';
    $('directory-description').textContent=kind==='watch'?'新增文件夹会先记录现有视频，只翻译之后新增的内容。移除文件夹不会删除视频、字幕或历史任务。':'选择新建或空的目录。知识库、任务和模型会复制并校验后切换；临时目录用于后续文件，原目录保留。其他磁盘需先配置 Docker 挂载。';
    $('directory-save').textContent=kind==='watch'?'保存监控目录':'保存并迁移';
    $('directory-dialog').showModal();$('directory-title').focus();await load();
  }
  $('watch-edit').onclick=()=>open('watch');$('storage-edit').onclick=()=>open('storage');
  $('directory-close').onclick=()=>{$('directory-dialog').close();clearTimeout(timer);ticket++;};
  $('directory-dialog').addEventListener('close',()=>{clearTimeout(timer);ticket++;});
  $('directory-form').addEventListener('input',()=>{state();$('directory-feedback').textContent=dirty()?'有未保存的更改':'尚未修改';});
  $('directory-reset').onclick=populate;$('directory-reload').onclick=()=>load();
  $('directory-form').onsubmit=async event=>{
    event.preventDefault();if(busy||!data||!dirty()||!$('directory-form').reportValidity())return;
    const request=++ticket;
    busy=true;state();notice('directory-error','');
    try{const result=await api('directories/'+kind,payload());if(request!==ticket)return;data=result;populate();poll();}
    catch(e){if(request===ticket)notice('directory-error',e.message);}
    finally{if(request===ticket){busy=false;state();}}
  };
})();
