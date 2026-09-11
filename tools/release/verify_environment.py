"""Fail a release build on toolchain drift; emit a reproducible input manifest."""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def verify_environment(ffmpeg=None):
    expected_python = (ROOT / '.python-version').read_text().strip()
    if platform.python_version() != expected_python or (platform.system() != 'Darwin' or platform.machine() != 'arm64'):
        raise RuntimeError(f'Release requires Python {expected_python} on macOS arm64')
    packages = {}
    for line in (ROOT / 'requirements-release-macos-arm64.lock').read_text().splitlines():
        if not line or line.startswith('#'): continue
        name, expected = line.split()[0].split('==')
        actual = version(name)
        if actual != expected: raise RuntimeError(f'Release dependency drift: {name} expected {expected}, got {actual}')
        packages[name] = actual
    node = subprocess.check_output(['node', '--version'], text=True).strip().removeprefix('v')
    if node != (ROOT / '.node-version').read_text().strip():
        raise RuntimeError('Release Node.js version differs from .node-version')
    result = {'python': platform.python_version(), 'node': node, 'platform': platform.platform(), 'packages': packages}
    if ffmpeg:
        ffmpeg = Path(ffmpeg)
        first_line = subprocess.check_output([str(ffmpeg), '-version'], text=True).splitlines()[0]
        if not first_line.startswith('ffmpeg version 8.1.1 '):
            raise RuntimeError('Release requires FFmpeg 8.1.1; review native dependency changes explicitly')
        result['ffmpeg'] = {'version': first_line, 'sha256': hashlib.sha256(ffmpeg.read_bytes()).hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    manifest = verify_environment(args.ffmpeg)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2) + '\n')
    print('Release environment verified')


if __name__ == '__main__': main()
