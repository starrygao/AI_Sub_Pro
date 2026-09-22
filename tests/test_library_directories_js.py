from tests.test_library_panels_js import run_js


def test_directory_edits_preserve_server_errors_and_save_only_explicit_changes():
    run_js(r'''
let calls=[],fail=false;
const watch={current:['/vol2/media/A'],desired:['/vol2/media/A'],allowed:['/vol2/media'],pending:false,error:''};
const storage={supported:true,current:{data:'/vol2/aisub/data',temporary:'/vol2/aisub/tmp',models:'/vol2/aisub/models'},allowed:'/vol2/aisub',pending:false};storage.desired=storage.current;
Object.assign(elements['directory-dialog'],{open:false,showModal(){this.open=true},close(){this.open=false}});
context.clearTimeout=()=>{};context.setTimeout=()=>1;context.refresh=()=>{};
context.api=async(path,body)=>{if(!body)return {watch,storage};if(fail)throw Error('文件夹不存在');calls.push({path,body:structuredClone(body)});return {...watch,desired:body.roots,pending:true};};
vm.runInContext(fs.readFileSync('app/static/js/library-directories.js','utf8'),context);
await $('watch-edit').onclick();assert.equal($('watch-paths').value,'/vol2/media/A');assert.equal($('directory-save').disabled,true);
$('watch-paths').value='/vol2/media/A\n/vol2/media/B';$('directory-form').handlers.input();
assert.equal($('directory-save').disabled,false);fail=true;await $('directory-form').onsubmit({preventDefault(){}});
assert.match($('directory-error').textContent,/不存在/);assert.equal($('watch-paths').value,'/vol2/media/A\n/vol2/media/B');
fail=false;await $('directory-form').onsubmit({preventDefault(){}});
assert.deepEqual(calls,[{path:'directories/watch',body:{roots:['/vol2/media/A','/vol2/media/B']}}]);
assert.match($('directory-feedback').textContent,/已保存/);assert.equal($('directory-save').disabled,true);
$('directory-close').onclick();await $('storage-edit').onclick();
assert.equal($('storage-data').value,'/vol2/aisub/data');assert.equal($('directory-save').disabled,true);
''')
