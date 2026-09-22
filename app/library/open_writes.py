"""Read only host process file descriptors; publish media write paths, never file contents."""
import json
import os
from pathlib import Path
import time

EXTENSIONS={'.mkv','.mp4','.avi','.mov','.m4v','.ts','.m2ts','.webm'}


def writable_video_handles(proc,roots):
    found=set();denied=0
    for process in Path(proc).iterdir():
        if not process.name.isdigit():continue
        try:fds=list((process/'fd').iterdir())
        except FileNotFoundError:continue
        except PermissionError:denied+=1;continue
        for fd in fds:
            try:
                target=os.readlink(fd)
                if not any(target==root or target.startswith(root.rstrip('/')+'/') for root in roots):continue
                if Path(target).suffix.lower() not in EXTENSIONS:continue
                data=(process/'fdinfo'/fd.name).read_text()
                flags=next(line.split(':',1)[1].strip() for line in data.splitlines() if line.startswith('flags:'))
                if int(flags,8)&os.O_ACCMODE in {os.O_WRONLY,os.O_RDWR}:found.add(target)
            except FileNotFoundError:continue
            except PermissionError:denied+=1
    if denied:raise RuntimeError('无法检查全部进程的写入状态')
    return sorted(found)


def main():
    dest=Path('/state/open-writes.json');dest.parent.mkdir(parents=True,exist_ok=True)
    roots=json.loads(os.environ.get('AISUBPRO_HOST_MEDIA_ROOTS','["/vol2/1000/video","/vol2/1000/备份","/video","/media","/备份"]'))
    while True:
        try:value={'updated':time.time(),'ok':True,'paths':writable_video_handles('/proc',roots)}
        except Exception:value={'updated':time.time(),'ok':False,'paths':[]}
        tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False));tmp.chmod(0o644);tmp.replace(dest)
        time.sleep(10)

if __name__=='__main__':main()
