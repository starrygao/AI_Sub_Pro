# Contributing

Language: [English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

Contributions are welcome. Please keep changes focused and include tests for
behavioral changes.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
npm install
npm run build:css
pytest
```

## Guidelines

- Do not commit runtime data, API keys, downloaded media, build artifacts, or
  ASR model files.
- Keep user-facing workflows local-first and safe by default.
- Add regression tests for subtitle parsing, project-store behavior, provider
  errors, and API changes.
- For frontend changes, update the JavaScript tests that exercise the affected
  state transitions.
- Use clear commit messages that describe the user-visible behavior or safety
  issue being changed.
