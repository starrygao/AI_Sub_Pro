"""Bounded subtitle extraction with observed input-read progress for Docker."""
from pathlib import Path
import subprocess
import tempfile
import time


def input_position(pid, source, proc_root=Path('/proc')):
    """Read the input descriptor position, never infer progress from elapsed time."""
    try:
        for fd in (proc_root / str(pid) / 'fd').iterdir():
            if fd.samefile(source):
                info = proc_root / str(pid) / 'fdinfo' / fd.name
                for line in info.read_text().splitlines():
                    if line.startswith('pos:'):
                        return max(0, int(line.split(':', 1)[1]))
    except (OSError, ValueError):
        pass  # /proc can disappear on exit, or be unavailable outside Linux.
    return None


def extract_subtitles(cmd, source, report, stop_event, *, timeout=900, poll_seconds=1):
    total = Path(source).stat().st_size
    started = time.monotonic()
    # A file avoids deadlocking on ffmpeg stderr and uses the configured temp volume.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            while True:
                elapsed = time.monotonic() - started
                if stop_event.is_set():
                    raise RuntimeError('服务停止，字幕提取已中断，请重新检查')
                if elapsed >= timeout:
                    raise RuntimeError(f'字幕提取超时（{int(timeout)} 秒），请检查磁盘读取后重新检查')
                report(input_position(process.pid, source), total, int(elapsed))
                try:
                    result = process.wait(timeout=min(poll_seconds, timeout - elapsed))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if result:
                raise RuntimeError('字幕提取失败，请检查视频是否完整可读后重新检查')
        finally:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise RuntimeError('字幕提取已请求停止，磁盘仍未响应，请检查存储连接') from None
