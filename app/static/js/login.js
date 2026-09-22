'use strict';
const form=document.getElementById('login-form');
const password=document.getElementById('password');
const username=document.getElementById('username');
const toggle=document.getElementById('show-password');
const submit=document.getElementById('submit');
const error=document.getElementById('login-error');
const status=document.getElementById('login-status');
function destination(){
  const next=new URLSearchParams(location.search).get('next');
  if(!next||!next.startsWith('/')||next.startsWith('//'))return '/library';
  let url;
  try{url=new URL(next,location.origin);}catch{return '/library';}
  if(url.origin!==location.origin)return '/library';
  if(url.pathname==='/library')return '/library';
  if(url.pathname==='/desktop'){
    const project=url.searchParams.get('project');
    return '/desktop'+(/^[a-f0-9]{8}$/.test(project||'')?'?project='+project:'');
  }
  return '/library';
}
toggle.onclick=()=>{
  const visible=password.type==='password';
  password.type=visible?'text':'password';
  toggle.setAttribute('aria-label',visible?'隐藏密码':'显示密码');
  toggle.setAttribute('aria-pressed',String(visible));
  document.getElementById('eye-slash').toggleAttribute('hidden',!visible);
};
for(const field of [username,password])field.addEventListener('input',()=>{
  error.hidden=true;username.removeAttribute('aria-invalid');password.removeAttribute('aria-invalid');
});
form.addEventListener('submit',async event=>{
  event.preventDefault();if(submit.disabled)return;
  submit.disabled=true;document.getElementById('submit-label').textContent='正在登录…';
  status.textContent='正在验证账号';error.hidden=true;
  try{
    const response=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username.value,password:password.value})});
    if(!response.ok){
      const message=response.status===429?'尝试次数较多，请一分钟后再试。':response.status===401?'账号或密码不正确，请重新输入。':'暂时无法登录，请稍后重试。';
      if(response.status===401){username.setAttribute('aria-invalid','true');password.setAttribute('aria-invalid','true');password.focus();}
      throw Error(message);
    }
    password.value='';status.textContent='登录成功，正在进入媒体库';location.replace(destination());
  }catch(e){error.textContent=e instanceof TypeError?'无法连接服务器，请检查网络后重试。':e.message;error.hidden=false;status.textContent='';submit.disabled=false;document.getElementById('submit-label').textContent='进入媒体库';}
});
