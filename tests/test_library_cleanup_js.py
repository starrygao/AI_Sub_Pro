from tests.test_library_panels_js import run_js


def test_cleanup_settings_load_save_pause_and_preserve_failed_input():
    run_js(r'''
const policy={enabled:false,limit_gb:20,minimum_gb:5,managed_bytes:0,eligible_bytes:0,protected_bytes:0,last_run:{}};
const requests=[];let failure=false;
context.api=async(path,body)=>{assert.equal(path,'cleanup');if(failure)throw Error('暂时不可用');if(body){requests.push(body);Object.assign(policy,body);}return {...policy};};
vm.runInContext(fs.readFileSync('app/static/js/library-cleanup.js','utf8'),context);await flush();
assert.equal($('cleanup-limit').value,20);assert.equal($('cleanup-limit').min,5);
assert.equal($('cleanup-save').disabled,false);assert.equal($('cleanup-pause').hidden,true);
$('cleanup-limit').value='12';$('cleanup-limit').oninput();failure=true;
await $('cleanup-form').onsubmit({preventDefault(){}});
assert.equal($('cleanup-limit').value,'12');assert.match($('cleanup-error').textContent,/暂时不可用/);
failure=false;await $('cleanup-form').onsubmit({preventDefault(){}});
assert.equal(requests[0].limit_gb,12);assert.equal(requests[0].enabled,true);
assert.equal($('cleanup-save').disabled,true);assert.equal($('cleanup-pause').hidden,false);
await $('cleanup-pause').onclick();assert.equal(requests[1].enabled,false);
assert.match($('cleanup-feedback').textContent,/暂停/);
''')


def test_cleanup_load_failure_and_protected_remaining_are_visible():
    run_js(r'''
let fail=true;
context.api=async()=>{if(fail)throw Error('读取失败');return {enabled:true,limit_gb:5,minimum_gb:5,managed_bytes:10*1024**3,eligible_bytes:0,protected_bytes:10*1024**3,last_run:{status:'protected_remaining'}};};
vm.runInContext(fs.readFileSync('app/static/js/library-cleanup.js','utf8'),context);await flush();
assert.equal($('cleanup-save').disabled,true);assert.match($('cleanup-error').textContent,/读取失败/);
fail=false;await $('cleanup-refresh').onclick();
assert.match($('cleanup-summary').textContent,/受保护 10.00 GB/);
assert.match($('cleanup-feedback').textContent,/不会.*扩大删除范围/);
''')
