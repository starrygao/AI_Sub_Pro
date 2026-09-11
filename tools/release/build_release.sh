#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
bash tools/release/setup_environment.sh
export PATH="$PWD/.release-venv/bin:$PATH"
python3 tools/release/verify_environment.py
bash make_dmg.sh
VERSION=$(python3 -c 'from app.version import APP_VERSION; print(APP_VERSION)')
python3 tools/release/smoke_test.py --bundle 'dist/AI Sub Pro.app' --version "$VERSION" --output dist/release-smoke-report.json
