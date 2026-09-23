'use strict';
(() => {
  const selected=new Map();
  let items=[],query='',kind='all',series=null,searchOffset=0,offset=0,sequence=0,loading=false,adding=false;
  const dialog=$('emby-dialog');
  function failure(message=''){$('emby-error').textContent=message;$('emby-error').hidden=!message;}
  function selectionState(){
    $('emby-selection-count').textContent='已选 '+selected.size+' 项 · 最多 50 项';
    $('emby-add').disabled=adding||loading||!selected.size;
    $('emby-clear').disabled=adding||!selected.size;
    $('emby-select-page').disabled=adding||loading||!items.some(item=>item.selectable&&!selected.has(item.id));
  }
  function title(item){
    const episode=Number.isInteger(item.episode)?'S'+String(item.season??0).padStart(2,'0')+'E'+String(item.episode).padStart(2,'0')+' · ':'';
    return episode+item.name;
  }
  function choose(item,checked){
    if(checked&&selected.size>=50&&!selected.has(item.id)){failure('每批最多添加 50 项，请先添加当前选择。');return false;}
    if(checked)selected.set(item.id,item);else selected.delete(item.id);
    selectionState();return checked;
  }
  function render(){
    const rows=[];
    for(const item of items){
      const row=el('div',undefined,'emby-result'),body=el('div',undefined,'emby-result-body');
      if(item.type==='Series'){
        body.append(el('h4',item.name));
      }else{
        const label=el('label',undefined,'emby-choice'),check=el('input');check.type='checkbox';check.checked=selected.has(item.id);check.disabled=!item.selectable;
        check.onchange=()=>{check.checked=choose(item,check.checked);};label.append(check,el('span',title(item)));body.append(label);
      }
      const langs=values=>(values||[]).map(value=>({eng:'英语',en:'英语',chi:'中文',zho:'中文',zh:'中文',jpn:'日语',ja:'日语',kor:'韩语',und:'未标明'}[value]||value)).join('、');
      body.append(el('p',item.type==='Series'?['剧集',item.year].filter(Boolean).join(' · '):['音轨：'+(langs(item.audio_languages)||'未提供'),'字幕：'+(langs(item.subtitle_languages)||'未提供')].join(' · '),'hint'));
      if(item.path){const file=el('p',item.path,'emby-file');file.title=item.path;body.append(file);}
      if(item.reason)body.append(el('p',item.reason,'hint'));
      row.append(body);
      if(item.type==='Series'){
        const button=el('button','选择集数','secondary');button.onclick=()=>{searchOffset=offset;series={id:item.id,name:item.name};offset=0;return load();};row.append(button);
      }
      rows.push(row);
    }
    $('emby-results').replaceChildren(...rows);selectionState();
  }
  async function load(){
    const current=++sequence;loading=true;failure();items=[];render();
    $('emby-feedback').textContent='';$('emby-outcomes').hidden=true;$('emby-go-tasks').hidden=true;
    $('emby-message').textContent='正在读取 Emby…';$('emby-results').setAttribute('aria-busy','true');
    $('emby-prev').hidden=true;$('emby-next').hidden=true;$('emby-page').textContent='';
    $('emby-back').hidden=!series;$('emby-series').hidden=!series;$('emby-series').textContent=series?.name||'';
    const path=series?'emby/episodes?series_id='+encodeURIComponent(series.id):'emby/search?q='+encodeURIComponent(query)+'&kind='+kind;
    try{
      const response=await api(path+'&offset='+offset+'&limit=30');
      if(current!==sequence||!dialog.open)return;
      items=response.items;render();
      $('emby-message').textContent=items.length?(response.total_is_exact===false?'至少 ':'共 ')+response.total+' 项'+(series?'，勾选需要检查的集数。':'，电影可直接勾选，剧集请先选择集数。'):'没有找到可显示的条目，请换个名称或检查 Emby 收录情况。';
      $('emby-prev').hidden=offset===0;$('emby-next').hidden=!(response.has_more??(offset+response.limit<response.total));
      $('emby-page').textContent=response.total?'第 '+(Math.floor(offset/response.limit)+1)+' 页':'';
    }catch(e){if(current===sequence){failure(e.message);$('emby-message').textContent='读取失败，请重新搜索或返回重试。';}}
    finally{if(current===sequence){loading=false;$('emby-results').setAttribute('aria-busy','false');selectionState();}}
  }
  $('emby-open').onclick=()=>{dialog.showModal();$('emby-query').focus();};
  $('emby-close').onclick=()=>{if(!adding)dialog.close();};
  dialog.addEventListener('cancel',event=>{if(adding)event.preventDefault();});
  dialog.addEventListener('close',()=>{sequence++;loading=false;selectionState();$('emby-open').focus();});
  $('emby-search').onsubmit=event=>{event.preventDefault();if(adding)return;query=$('emby-query').value.trim();kind=$('emby-kind').value||'all';series=null;offset=0;if(!query){failure('请输入电影或剧集名称');return;}return load();};
  $('emby-back').onclick=()=>{series=null;offset=searchOffset;return load();};
  $('emby-prev').onclick=()=>{offset=Math.max(0,offset-30);return load();};
  $('emby-next').onclick=()=>{offset+=30;return load();};
  $('emby-select-page').onclick=()=>{for(const item of items){if(item.selectable&&!selected.has(item.id)){if(selected.size>=50){failure('每批最多添加 50 项，已保留前 50 项。');break;}selected.set(item.id,item);}}render();};
  $('emby-clear').onclick=()=>{selected.clear();render();failure();};
  $('emby-add').onclick=async()=>{
    if(adding||loading||!selected.size)return;
    adding=true;failure();$('emby-browser').disabled=true;$('emby-close').disabled=true;selectionState();
    const submitted=new Map(selected);$('emby-feedback').textContent='正在添加 '+submitted.size+' 项…';
    try{
      const result=await api('emby/enqueue',{ids:[...submitted.keys()]});let queued=0,existing=0;const outcomes=[];
      for(const item of result.items){
        if(item.status==='queued'||item.status==='existing'){selected.delete(item.id);queued+=Number(item.status==='queued');existing+=Number(item.status==='existing');const visible=items.find(row=>row.id===item.id);if(visible){visible.selectable=false;visible.reason=item.message;}}
        outcomes.push(el('li',(submitted.get(item.id)?.name||item.id)+'：'+item.message));
      }
      $('emby-outcomes').replaceChildren(...outcomes);$('emby-outcomes').hidden=false;
      $('emby-feedback').textContent='已添加 '+queued+' 项，已有记录 '+existing+' 项。'+(selected.size?'其余条目未添加，可查看原因后重试。':'')+(result.enabled?'检查通过后依次翻译。':'自动翻译已暂停，开启后才会检查并开始。');
      $('emby-go-tasks').hidden=!(queued||existing);render();await refresh();
    }catch(e){failure(e.message);$('emby-feedback').textContent='未确认添加结果，已保留选择。可重试，已有任务不会重复创建。';}
    finally{adding=false;$('emby-browser').disabled=false;$('emby-close').disabled=false;selectionState();}
  };
  $('emby-go-tasks').onclick=()=>{dialog.close();selectView('waiting');};
})();
