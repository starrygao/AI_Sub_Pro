"""A login redirect may only return to known local application screens."""
import subprocess
from pathlib import Path


def test_login_redirect_does_not_leave_the_application():
    script=r'''
const fs=require('fs'),vm=require('vm');
const stub=()=>({addEventListener(){}});
const context={document:{getElementById:stub},URL,URLSearchParams,location:{origin:'http://nas.test',search:''}};
vm.createContext(context);vm.runInContext(fs.readFileSync('app/static/js/login.js','utf8'),context);
for(const next of ['https://evil.test','//evil.test','/\\evil.test','/\\','/api/settings','/desktop?project=invalid','/desktop?project=deadbeef','/library']){
 context.location.search='?next='+encodeURIComponent(next);
 const expected=next==='/desktop?project=deadbeef'?next:next==='/desktop?project=invalid'?'/desktop':'/library';
 if(context.destination()!==expected)throw Error('Unsafe or incorrect destination: '+next);
}
'''
    result=subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
