'use strict';
(() => {
  let data=null, loading=false, saving=false;
  const fields={'proxy-url':'proxy_url','proxy-dashboard':'dashboard_url'};
  const notice=(id,text)=>{$(id).textContent=text;$(id).hidden=!text;};
  function changes(){
    if(!data)return {};
    return Object.fromEntries(Object.entries(fields).map(([id,key])=>[key,$(id).value.trim()])
      .filter(([key,value])=>value!==data.desired[key]));
  }
  const dirty=()=>Object.keys(changes()).length>0;
  function state(){
    $('proxy-fields').disabled=saving||!data;
    $('proxy-save').disabled=saving||loading||!data||!dirty();
    $('proxy-reset').disabled=saving||!data||!dirty();
    $('proxy-reload').disabled=saving||loading;
  }
  function summary(){
    $('proxy-current').textContent=data.current.proxy_url||'直连（未使用代理）';
    $('proxy-source').textContent=(data.source==='environment'?'来源：服务器启动配置':'来源：网页保存的设置，重启后保留')+(data.credentials_configured?' · 已配置认证，账号密码不显示':'');
    notice('proxy-availability',data.pending?'新代理地址已保存，等待当前任务结束后应用。当前请求继续使用上方地址。':'保存后自动应用；有任务运行时等待其完成，再用于后续请求。');
    const link=$('proxy-dashboard-open');
    link.hidden=!data.current.dashboard_url;
    if(data.current.dashboard_url)link.href=data.current.dashboard_url;
    else link.removeAttribute('href');
  }
  function populate(){
    for(const [id,key] of Object.entries(fields))$(id).value=data.desired[key]||'';
    $('proxy-feedback').textContent=data.pending?'已保存，等待生效':'当前设置已生效';
    summary();state();
  }
  async function load(){
    if(loading||saving)return;
    loading=true;state();notice('proxy-error','');$('proxy-loading').hidden=!!data;
    try{
      const result=await api('proxy'),keep=dirty();data=result;
      if(!keep)populate();else summary();
      $('proxy-form').hidden=false;$('proxy-reload').hidden=false;$('proxy-reload').textContent='刷新代理状态';
      notice('proxy-error',data.error||'');
    }catch(e){notice('proxy-error',e.message);$('proxy-reload').hidden=false;}
    finally{loading=false;$('proxy-loading').hidden=true;state();}
  }
  $('proxy-form').addEventListener('input',()=>{$('proxy-feedback').textContent=dirty()?'有未保存的更改':'尚未修改';state();});
  $('proxy-reset').onclick=()=>{populate();notice('proxy-error','');};
  $('proxy-reload').onclick=load;
  $('proxy-form').onsubmit=async event=>{
    event.preventDefault();
    if(saving||loading||!data||!dirty()||!$('proxy-form').reportValidity())return;
    const patch=changes();saving=true;state();notice('proxy-error','');$('proxy-save').textContent='正在保存…';
    try{data=await api('proxy',patch);populate();}
    catch(e){notice('proxy-error',e.message);$('proxy-error').focus();}
    finally{saving=false;$('proxy-save').textContent='保存代理设置';state();}
  };
  window.LibraryProxy={open:load};
  setInterval(()=>{if(location.hash==='#proxy'&&!document.hidden&&data?.pending)load();},2000);
  if(location.hash==='#proxy')load();
})();
