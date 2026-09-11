#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 -c 'import platform,pathlib; assert platform.python_version()==pathlib.Path(".python-version").read_text().strip(), "Use the pinned Python version"'
python3 -m venv .release-venv
.release-venv/bin/python -m pip install --require-hashes -r requirements-release-bootstrap.lock
.release-venv/bin/python -m pip install --require-hashes --no-build-isolation -r requirements-release-macos-arm64.lock
.release-venv/bin/python -m pip check
npm ci
