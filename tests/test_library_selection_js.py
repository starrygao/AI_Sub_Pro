from tests.test_library_panels_js import run_js


def test_search_pagination_selection_and_failed_add_preserve_user_choices():
    run_js(r'''
let calls=[],fail=false,selectedView='';
Object.assign($('emby-dialog'),{open:false,showModal(){this.open=true},close(){this.open=false;this.handlers.close?.()}});
context.selectView=value=>selectedView=value;context.refresh=async()=>{};
const item={id:'1',name:'Movie',type:'Movie',selectable:true,audio_languages:['eng'],subtitle_languages:[],path:'/video/Movie.mkv'};
context.api=async(path,body)=>{calls.push({path,body:body?structuredClone(body):undefined});if(body){if(fail)throw Error('连接中断');return {enabled:false,items:[{id:'1',status:'queued',message:'已加入'}]};}return {items:[item],total:61,offset:path.includes('offset=30')?30:0,limit:30};};
vm.runInContext(fs.readFileSync('app/static/js/library-selection.js','utf8'),context);
$('emby-open').onclick();$('emby-query').value='Movie';await $('emby-search').onsubmit({preventDefault(){}});
assert.match(calls[0].path,/search\?q=Movie/);
$('emby-select-page').onclick();assert.equal($('emby-add').disabled,false);assert.match($('emby-selection-count').textContent,/1/);
await $('emby-next').onclick();assert.match(calls[1].path,/offset=30/);
fail=true;await $('emby-add').onclick();assert.match($('emby-error').textContent,/连接中断/);assert.equal($('emby-add').disabled,false);
fail=false;await $('emby-add').onclick();assert.equal($('emby-add').disabled,true);assert.match($('emby-feedback').textContent,/暂停/);
const posted=calls.filter(x=>x.body);assert.deepEqual(posted[0].body,{ids:['1']});
$('emby-go-tasks').onclick();assert.equal(selectedView,'waiting');assert.equal($('emby-dialog').open,false);
''')


def test_slow_old_search_cannot_overwrite_newer_results():
    run_js(r'''
let resolveOld;
Object.assign($('emby-dialog'),{open:false,showModal(){this.open=true},close(){this.open=false}});
context.api=path=>path.includes('q=old')?new Promise(resolve=>resolveOld=resolve):Promise.resolve({items:[],total:0,offset:0,limit:30});
vm.runInContext(fs.readFileSync('app/static/js/library-selection.js','utf8'),context);
$('emby-open').onclick();$('emby-query').value='old';const old=$('emby-search').onsubmit({preventDefault(){}});
$('emby-query').value='new';await $('emby-search').onsubmit({preventDefault(){}});
resolveOld({items:[{id:'1',name:'Old',type:'Movie',selectable:true}],total:1,offset:0,limit:30});await old;
assert.equal($('emby-results').children.length,0);assert.match($('emby-message').textContent,/没有找到/);
''')
