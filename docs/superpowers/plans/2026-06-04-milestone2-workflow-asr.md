# Milestone 2 Workflow Reliability And ASR Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add intent-level ASR recommendations and a structured long-running workflow state layer with logs, retry, resume, and frontend controls.

**Architecture:** Keep ASR capability detection in a focused engine module and expose it through the existing `/api/system-check` contract. Add a focused `workflow_state` engine that persists `workflow_state.json` plus bounded per-stage logs in each project directory, then wire current pipeline stages into it without replacing the existing progress WebSocket. Add retry/resume APIs and compact frontend controls after backend behavior is covered by tests.

**Tech Stack:** Python dataclasses, FastAPI, atomic project-store JSON helpers, existing scheduler/progress APIs, vanilla JavaScript state tests with Node `vm`, pytest.

---

## File Structure

- Create `app/engines/asr_capabilities.py`: ASR backend capability detection and mode recommendation.
- Modify `app/engines/asr.py`: expose backend order execution through an optional recommended backend while keeping the fallback chain.
- Modify `app/config.py`: add `asr.mode` default.
- Modify `app/api/settings.py`: validate ASR mode and include capability/recommendation data in `/api/system-check`.
- Create `tests/test_asr_capabilities.py`: simulated platform/package/cache coverage.
- Extend `tests/test_config.py` and `tests/test_settings_claude_cli.py` or add focused settings tests for ASR mode validation/system check payload.
- Create `app/engines/workflow_state.py`: structured stage state, bounded logs, retry/resume eligibility helpers.
- Extend `app/engines/scheduler.py`: keep `progress.json` behavior while appending safe stage log entries.
- Modify `app/api/translate.py`: mark workflow/stage lifecycle for ASR, translation, burn, full pipeline, cancel, retry, and resume.
- Modify `app/api/projects.py`: expose workflow-state and log-download endpoints.
- Create `tests/test_workflow_state.py`: state normalization, transitions, bounded logs, redaction, eligibility.
- Extend `tests/test_scheduler_progress.py`, `tests/test_scheduler_cancel.py`, `tests/test_translate_integration.py`, and `tests/test_project_patch.py`.
- Modify `app/static/js/app.js` and `app/static/index.html`: ASR mode/recommendation UI plus workflow state/log/retry/resume controls.
- Extend `tests/test_frontend_settings_js.py`, `tests/test_frontend_accessibility.py`, and `tests/test_frontend_loading_js.py` or add `tests/test_frontend_workflow_js.py`.
- Update `docs/USAGE.md`, `docs/USAGE.zh-CN.md`, `docs/RELEASE_NOTES.md`, and `docs/RELEASE_NOTES.zh-CN.md`.

## Task 1: ASR Capability Detector

**Files:**
- Create: `app/engines/asr_capabilities.py`
- Test: `tests/test_asr_capabilities.py`

- [ ] **Step 1: Write failing capability tests**

Create `tests/test_asr_capabilities.py`:

```python
from pathlib import Path


def test_detect_asr_capabilities_prefers_apple_silicon_mlx(monkeypatch, tmp_path):
    from app.engines import asr_capabilities

    monkeypatch.setattr(asr_capabilities.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(asr_capabilities.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(asr_capabilities.importlib.util, "find_spec", lambda name: object() if name == "mlx_whisper" else None)
    monkeypatch.setattr(asr_capabilities, "resolve_mlx_model_source", lambda model: {
        "source": "bundled",
        "available": True,
        "path": str(tmp_path / model),
        "path_or_repo": str(tmp_path / model),
    })

    caps = asr_capabilities.detect_asr_capabilities({"model_size": "large-v3-turbo"})

    assert caps["platform"]["system"] == "Darwin"
    assert caps["backends"]["mlx_whisper"]["installed"] is True
    assert caps["backends"]["mlx_whisper"]["accelerated"] is True
    assert caps["models"]["large-v3-turbo"]["available"] is True


def test_recommend_asr_settings_maps_speed_accuracy_and_offline(monkeypatch):
    from app.engines.asr_capabilities import recommend_asr_settings

    caps = {
        "platform": {"system": "Darwin", "machine": "arm64"},
        "backends": {
            "mlx_whisper": {"installed": True, "accelerated": True, "supports_vad": False, "supports_beam": False},
            "faster_whisper": {"installed": True, "accelerated": False, "supports_vad": True, "supports_beam": True},
            "openai_whisper": {"installed": False, "accelerated": False, "supports_vad": False, "supports_beam": True},
        },
        "models": {
            "small": {"available": True, "download_hint": "~900MB", "source": "cache"},
            "large-v3": {"available": False, "download_hint": "~3GB", "source": "download"},
            "large-v3-turbo": {"available": True, "download_hint": "~1.6GB", "source": "bundled"},
        },
    }

    speed = recommend_asr_settings("speed", caps)
    accuracy = recommend_asr_settings("accuracy", caps)
    offline = recommend_asr_settings("offline", caps)

    assert speed["mode"] == "speed"
    assert speed["backend"] == "mlx_whisper"
    assert speed["model_size"] == "large-v3-turbo"
    assert accuracy["backend"] == "faster_whisper"
    assert accuracy["model_size"] == "large-v3"
    assert accuracy["download_required"] is True
    assert offline["download_required"] is False
    assert offline["model_size"] in {"small", "large-v3-turbo"}


def test_recommendation_degrades_when_no_backend_is_installed():
    from app.engines.asr_capabilities import recommend_asr_settings

    caps = {
        "platform": {"system": "Linux", "machine": "x86_64"},
        "backends": {
            "mlx_whisper": {"installed": False, "accelerated": False, "supports_vad": False, "supports_beam": False},
            "faster_whisper": {"installed": False, "accelerated": False, "supports_vad": True, "supports_beam": True},
            "openai_whisper": {"installed": False, "accelerated": False, "supports_vad": False, "supports_beam": True},
        },
        "models": {},
    }

    rec = recommend_asr_settings("offline", caps)

    assert rec["backend"] == ""
    assert rec["ready"] is False
    assert "安装" in rec["reason"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_asr_capabilities.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.engines.asr_capabilities'`.

- [ ] **Step 3: Implement ASR capability module**

Create `app/engines/asr_capabilities.py`:

```python
"""ASR capability detection and intent-level recommendations."""
from __future__ import annotations

import importlib.util
import platform
from typing import Any

from app.engines.asr import MODEL_DOWNLOAD_HINTS, resolve_mlx_model_source

ASR_MODES = ("speed", "accuracy", "offline")
MODEL_ORDER = ("tiny", "base", "small", "medium", "large-v3-turbo", "large-v3")


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _backend(installed: bool, *, accelerated: bool, supports_vad: bool, supports_beam: bool) -> dict[str, Any]:
    return {
        "installed": bool(installed),
        "accelerated": bool(accelerated),
        "supports_vad": bool(supports_vad),
        "supports_beam": bool(supports_beam),
    }


def _model_info(model: str) -> dict[str, Any]:
    source = resolve_mlx_model_source(model)
    return {
        "model_size": model,
        "available": bool(source.get("available")),
        "source": source.get("source", "unknown"),
        "path": source.get("path", ""),
        "download_hint": MODEL_DOWNLOAD_HINTS.get(model, ""),
    }


def detect_asr_capabilities(asr_cfg: dict | None = None) -> dict[str, Any]:
    cfg = asr_cfg if isinstance(asr_cfg, dict) else {}
    system = platform.system()
    machine = platform.machine()
    apple_silicon = system == "Darwin" and machine in {"arm64", "aarch64"}
    selected_model = cfg.get("model_size") if isinstance(cfg.get("model_size"), str) else "large-v3-turbo"
    models = {model: _model_info(model) for model in MODEL_ORDER}
    if selected_model not in models:
        models[selected_model] = _model_info(selected_model)
    return {
        "platform": {"system": system, "machine": machine, "apple_silicon": apple_silicon},
        "backends": {
            "mlx_whisper": _backend(
                _has_module("mlx_whisper"),
                accelerated=apple_silicon,
                supports_vad=False,
                supports_beam=False,
            ),
            "faster_whisper": _backend(
                _has_module("faster_whisper"),
                accelerated=False,
                supports_vad=True,
                supports_beam=True,
            ),
            "openai_whisper": _backend(
                _has_module("whisper"),
                accelerated=False,
                supports_vad=False,
                supports_beam=True,
            ),
        },
        "models": models,
    }


def _installed(caps: dict[str, Any], backend: str) -> bool:
    return bool(caps.get("backends", {}).get(backend, {}).get("installed"))


def _model(caps: dict[str, Any], model: str) -> dict[str, Any]:
    info = caps.get("models", {}).get(model)
    return info if isinstance(info, dict) else {"available": False, "download_hint": MODEL_DOWNLOAD_HINTS.get(model, "")}


def _first_available_model(caps: dict[str, Any]) -> str:
    for model in ("large-v3-turbo", "small", "base", "tiny", "medium", "large-v3"):
        if _model(caps, model).get("available"):
            return model
    return "large-v3-turbo"


def recommend_asr_settings(mode: str, caps: dict[str, Any]) -> dict[str, Any]:
    mode = mode if mode in ASR_MODES else "speed"
    backends = caps.get("backends", {}) if isinstance(caps, dict) else {}
    installed = [name for name, info in backends.items() if isinstance(info, dict) and info.get("installed")]
    if not installed:
        return {
            "mode": mode,
            "backend": "",
            "model_size": "",
            "ready": False,
            "download_required": False,
            "download_hint": "",
            "reason": "未检测到本地 ASR 后端，请安装 mlx-whisper、faster-whisper 或 openai-whisper。",
        }

    if mode == "accuracy":
        backend = "faster_whisper" if _installed(caps, "faster_whisper") else installed[0]
        model = "large-v3"
        reason = "准确优先：使用更大模型和支持 beam/VAD 的后端。"
    elif mode == "offline":
        backend = "mlx_whisper" if _installed(caps, "mlx_whisper") else installed[0]
        model = _first_available_model(caps)
        reason = "离线优先：优先选择已缓存或内置模型，减少下载依赖。"
    else:
        backend = "mlx_whisper" if _installed(caps, "mlx_whisper") else installed[0]
        model = "large-v3-turbo" if backend == "mlx_whisper" else "small"
        reason = "速度优先：优先选择 Apple Silicon/本地快速后端和较快模型。"

    info = _model(caps, model)
    return {
        "mode": mode,
        "backend": backend,
        "model_size": model,
        "ready": bool(backend),
        "download_required": not bool(info.get("available")),
        "download_hint": info.get("download_hint", ""),
        "model_source": info.get("source", "unknown"),
        "supports_vad": bool(backends.get(backend, {}).get("supports_vad")),
        "supports_beam": bool(backends.get(backend, {}).get("supports_beam")),
        "reason": reason,
    }
```

- [ ] **Step 4: Run capability tests**

Run: `python3 -m pytest -q tests/test_asr_capabilities.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/engines/asr_capabilities.py tests/test_asr_capabilities.py
git commit -m "feat: detect ASR capabilities"
```

## Task 2: ASR Mode Settings And System Check

**Files:**
- Modify: `app/config.py`
- Modify: `app/api/settings.py`
- Test: `tests/test_config.py`
- Test: `tests/test_settings_claude_cli.py`

- [ ] **Step 1: Write failing settings/system-check tests**

Append to `tests/test_settings_claude_cli.py`:

```python
def test_system_check_includes_asr_capabilities_and_recommendation(monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.settings as settings_api
    from app.main import app

    monkeypatch.setattr(settings_api, "detect_asr_capabilities", lambda cfg: {
        "platform": {"system": "Darwin", "machine": "arm64", "apple_silicon": True},
        "backends": {"mlx_whisper": {"installed": True, "accelerated": True}},
        "models": {"large-v3-turbo": {"available": True, "download_hint": "~1.6GB", "source": "bundled"}},
    })
    monkeypatch.setattr(settings_api, "recommend_asr_settings", lambda mode, caps: {
        "mode": mode,
        "backend": "mlx_whisper",
        "model_size": "large-v3-turbo",
        "ready": True,
        "download_required": False,
        "download_hint": "~1.6GB",
        "reason": "速度优先",
    })

    data = TestClient(app).get("/api/system-check").json()

    assert data["asr_mode"] in {"speed", "accuracy", "offline"}
    assert data["asr_capabilities"]["platform"]["apple_silicon"] is True
    assert data["asr_recommendation"]["backend"] == "mlx_whisper"
```

Append to `tests/test_config.py`:

```python
def test_default_config_has_asr_mode():
    from app.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["asr"]["mode"] == "speed"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_config.py::test_default_config_has_asr_mode tests/test_settings_claude_cli.py::test_system_check_includes_asr_capabilities_and_recommendation`

Expected: FAIL because `asr.mode` and system-check capability fields are missing.

- [ ] **Step 3: Add config default and settings validation**

In `app/config.py`, add `mode` to `DEFAULT_CONFIG["asr"]`:

```python
"asr": {
    "mode": "speed",
    "model_size": "large-v3-turbo",
    "language": "auto",
    "beam_size": 5,
    "offset_ms": 0,
    "vad_filter": True,
    "use_demucs": True,
},
```

In `app/api/settings.py`, import the new helpers near the other imports:

```python
from app.engines.asr_capabilities import ASR_MODES, detect_asr_capabilities, recommend_asr_settings
```

In `_validate_settings_update()`, inside the `asr` section, add:

```python
        _require_non_blank_str("asr", asr, "mode")
        if "mode" in asr:
            asr["mode"] = asr["mode"].strip()
            if asr["mode"] not in ASR_MODES:
                allowed = ", ".join(ASR_MODES)
                raise HTTPException(status_code=400, detail=f"ASR mode must be one of: {allowed}")
```

In `system_check()`, after `asr_cfg` is available, add:

```python
    asr_mode = asr_cfg.get("mode") if isinstance(asr_cfg.get("mode"), str) else "speed"
    if asr_mode not in ASR_MODES:
        asr_mode = "speed"
    asr_capabilities = detect_asr_capabilities(asr_cfg)
    asr_recommendation = recommend_asr_settings(asr_mode, asr_capabilities)
```

Add these keys to the returned dict:

```python
        "asr_mode": asr_mode,
        "asr_capabilities": asr_capabilities,
        "asr_recommendation": asr_recommendation,
```

- [ ] **Step 4: Run settings tests**

Run: `python3 -m pytest -q tests/test_config.py::test_default_config_has_asr_mode tests/test_settings_claude_cli.py::test_system_check_includes_asr_capabilities_and_recommendation tests/test_settings_claude_cli.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/api/settings.py tests/test_config.py tests/test_settings_claude_cli.py
git commit -m "feat: expose ASR mode recommendation"
```

## Task 3: Frontend ASR Mode Recommendation UI

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `app/static/index.html`
- Test: `tests/test_frontend_settings_js.py`
- Test: `tests/test_frontend_accessibility.py`

- [ ] **Step 1: Write failing frontend tests**

Append to `tests/test_frontend_settings_js.py`:

```python
def test_frontend_formats_asr_recommendation_from_system_check():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.sysCheck = {
          asr_recommendation: {
            mode: 'offline',
            backend: 'mlx_whisper',
            model_size: 'large-v3-turbo',
            download_required: false,
            download_hint: '~1.6GB',
            reason: '离线优先',
          },
        };

        if (state.asrModeLabel('speed') !== '速度优先') throw new Error('missing speed label');
        if (!state.asrRecommendationSummary().includes('mlx_whisper')) {
          throw new Error(`missing backend summary: ${state.asrRecommendationSummary()}`);
        }
        if (!state.asrRecommendationSummary().includes('large-v3-turbo')) {
          throw new Error(`missing model summary: ${state.asrRecommendationSummary()}`);
        }
        """
    )

    assert result.returncode == 0, result.stderr
```

Append to `tests/test_frontend_accessibility.py`:

```python
def test_asr_mode_and_recommendation_are_visible_in_settings():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert 'x-model="settings.asr.mode"' in html
    assert 'aria-label="ASR 模式"' in html
    assert "asrRecommendationSummary()" in html
    assert "asrModeLabel" in js
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_frontend_settings_js.py::test_frontend_formats_asr_recommendation_from_system_check tests/test_frontend_accessibility.py::test_asr_mode_and_recommendation_are_visible_in_settings`

Expected: FAIL because helpers and markup are missing.

- [ ] **Step 3: Add frontend ASR helpers**

In `app/static/js/app.js`, add methods near settings helpers:

```javascript
    asrModeLabel(mode) {
      return {
        speed: '速度优先',
        accuracy: '准确优先',
        offline: '离线优先',
      }[mode] || mode || '速度优先';
    },

    asrRecommendationSummary() {
      const rec = this.sysCheck?.asr_recommendation || {};
      if (!rec.ready) return rec.reason || '未检测到可用 ASR 后端';
      const parts = [rec.backend, rec.model_size].filter(Boolean);
      const download = rec.download_required && rec.download_hint
        ? `需下载 ${rec.download_hint}`
        : '本地可用';
      return `${this.asrModeLabel(rec.mode)}：${parts.join(' / ')}，${download}`;
    },
```

Ensure `normalizeSettings()` keeps `asr.mode` by defaulting through the existing `DEFAULT_SETTINGS` merge. If the frontend default object lacks `mode`, add `mode: 'speed'` under `settings.asr`.

- [ ] **Step 4: Add ASR mode and recommendation markup**

In the ASR settings section of `app/static/index.html`, add a mode select before the model select:

```html
            <div>
              <label class="block text-[12px] text-surface-400 mb-1.5 font-medium">ASR 模式</label>
              <select x-model="settings.asr.mode" aria-label="ASR 模式" class="w-full px-3 py-2 rounded-xl text-[13px]">
                <option value="speed">速度优先</option>
                <option value="accuracy">准确优先</option>
                <option value="offline">离线优先</option>
              </select>
            </div>
```

Add a compact recommendation line inside the ASR card:

```html
          <div x-show="sysCheck?.asr_recommendation" class="mt-4 rounded-xl border border-surface-200 px-3 py-2 text-[12px] text-surface-600">
            <p class="font-medium text-surface-700" x-text="asrRecommendationSummary()"></p>
            <p class="mt-1 text-surface-400" x-text="sysCheck?.asr_recommendation?.reason || ''"></p>
          </div>
```

- [ ] **Step 5: Run frontend tests**

Run: `python3 -m pytest -q tests/test_frontend_settings_js.py tests/test_frontend_accessibility.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/static/js/app.js app/static/index.html tests/test_frontend_settings_js.py tests/test_frontend_accessibility.py
git commit -m "feat: show ASR mode recommendation"
```

## Task 4: Workflow State Engine

**Files:**
- Create: `app/engines/workflow_state.py`
- Test: `tests/test_workflow_state.py`

- [ ] **Step 1: Write failing workflow state tests**

Create `tests/test_workflow_state.py`:

```python
import json


def test_workflow_state_records_stage_lifecycle(tmp_project_dir):
    from app.engines.workflow_state import (
        fail_stage,
        finish_stage,
        load_workflow_state,
        reset_workflow,
        start_stage,
    )

    reset_workflow("wf1", ["asr", "translate", "burn"])
    start_stage("wf1", "asr", input_artifact="input.mp4")
    finish_stage("wf1", "asr", output_artifact="filtered.srt")
    start_stage("wf1", "translate", input_artifact="filtered.srt")
    fail_stage("wf1", "translate", RuntimeError("bad api key"))

    state = load_workflow_state("wf1")

    assert state["stages"]["asr"]["status"] == "succeeded"
    assert state["stages"]["translate"]["status"] == "failed"
    assert state["stages"]["translate"]["retry_count"] == 1
    assert state["stages"]["translate"]["resume_eligible"] is False
    assert "bad api key" in state["stages"]["translate"]["error_summary"]


def test_stage_logs_are_bounded_and_redacted(tmp_project_dir):
    from app.engines.workflow_state import append_stage_log, stage_log_path

    secret = "sk-" + "x" * 48
    for _ in range(200):
        append_stage_log("wf-log", "asr", f"message with {secret}")

    path = stage_log_path("wf-log", "asr")
    text = path.read_text(encoding="utf-8")

    assert secret not in text
    assert "<redacted>" in text
    assert path.stat().st_size <= 200_000


def test_load_workflow_state_normalizes_invalid_file(tmp_project_dir):
    from app.engines.workflow_state import load_workflow_state

    pdir = tmp_project_dir / "wf-bad"
    pdir.mkdir()
    (pdir / "workflow_state.json").write_text(json.dumps({"stages": []}), encoding="utf-8")

    state = load_workflow_state("wf-bad")

    assert state["version"] == 1
    assert state["stages"] == {}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_workflow_state.py`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement workflow state module**

Create `app/engines/workflow_state.py`:

```python
"""Structured workflow state and bounded per-stage logs."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.utils.errors import redact_error_message
from app.utils.project_store import atomic_write_json, project_dir, validate_pid

VALID_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled", "skipped"}
VALID_STAGES = {"download", "asr", "subtitle_extract", "filter", "translate", "burn", "export"}
LOG_LIMIT_BYTES = 200_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_stage(stage: str) -> str:
    if stage not in VALID_STAGES:
        raise ValueError(f"invalid workflow stage: {stage}")
    return stage


def workflow_state_path(pid: str) -> Path:
    validate_pid(pid)
    return project_dir(pid) / "workflow_state.json"


def stage_log_path(pid: str, stage: str) -> Path:
    validate_pid(pid)
    stage = _clean_stage(stage)
    return project_dir(pid) / "workflow_logs" / f"{stage}.log"


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "updated_at": _now(), "stages": {}}


def _stage(status: str = "pending") -> dict[str, Any]:
    return {
        "status": status,
        "started_at": None,
        "finished_at": None,
        "input_artifact": "",
        "output_artifact": "",
        "retry_count": 0,
        "error_summary": "",
        "log_path": "",
        "resume_eligible": False,
    }


def _normalize_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_state()
    raw_stages = data.get("stages")
    if not isinstance(raw_stages, dict):
        return _empty_state()
    state = {"version": 1, "updated_at": data.get("updated_at") if isinstance(data.get("updated_at"), str) else _now(), "stages": {}}
    for name, raw in raw_stages.items():
        if name not in VALID_STAGES or not isinstance(raw, dict):
            continue
        item = _stage(raw.get("status") if raw.get("status") in VALID_STATUSES else "pending")
        for key in ("started_at", "finished_at", "input_artifact", "output_artifact", "error_summary", "log_path"):
            if isinstance(raw.get(key), str):
                item[key] = raw[key]
        retry_count = raw.get("retry_count")
        item["retry_count"] = retry_count if isinstance(retry_count, int) and retry_count >= 0 else 0
        item["resume_eligible"] = bool(raw.get("resume_eligible"))
        state["stages"][name] = item
    return state


def load_workflow_state(pid: str) -> dict[str, Any]:
    path = workflow_state_path(pid)
    if not path.exists():
        return _empty_state()
    try:
        import json

        return _normalize_state(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return _empty_state()


def save_workflow_state(pid: str, state: dict[str, Any]) -> dict[str, Any]:
    state = _normalize_state(state)
    state["updated_at"] = _now()
    atomic_write_json(workflow_state_path(pid), state)
    return state


def reset_workflow(pid: str, stages: list[str]) -> dict[str, Any]:
    state = _empty_state()
    for stage in stages:
        state["stages"][_clean_stage(stage)] = _stage("pending")
    return save_workflow_state(pid, state)


def start_stage(pid: str, stage: str, *, input_artifact: str = "") -> dict[str, Any]:
    stage = _clean_stage(stage)
    state = load_workflow_state(pid)
    item = state["stages"].setdefault(stage, _stage())
    item.update({
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "input_artifact": input_artifact or item.get("input_artifact", ""),
        "error_summary": "",
        "log_path": str(stage_log_path(pid, stage).relative_to(project_dir(pid))),
        "resume_eligible": False,
    })
    return save_workflow_state(pid, state)


def finish_stage(pid: str, stage: str, *, output_artifact: str = "", resume_eligible: bool = True) -> dict[str, Any]:
    stage = _clean_stage(stage)
    state = load_workflow_state(pid)
    item = state["stages"].setdefault(stage, _stage())
    item.update({
        "status": "succeeded",
        "finished_at": _now(),
        "output_artifact": output_artifact or item.get("output_artifact", ""),
        "error_summary": "",
        "resume_eligible": bool(resume_eligible),
    })
    return save_workflow_state(pid, state)


def fail_stage(pid: str, stage: str, exc: BaseException | str) -> dict[str, Any]:
    stage = _clean_stage(stage)
    state = load_workflow_state(pid)
    item = state["stages"].setdefault(stage, _stage())
    item.update({
        "status": "failed",
        "finished_at": _now(),
        "retry_count": int(item.get("retry_count", 0)) + 1,
        "error_summary": redact_error_message(exc),
        "resume_eligible": False,
    })
    return save_workflow_state(pid, state)


def cancel_workflow(pid: str, stage: str) -> dict[str, Any]:
    stage = _clean_stage(stage)
    state = load_workflow_state(pid)
    item = state["stages"].setdefault(stage, _stage())
    item.update({"status": "cancelled", "finished_at": _now(), "resume_eligible": False})
    return save_workflow_state(pid, state)


def append_stage_log(pid: str, stage: str, message: str) -> Path:
    path = stage_log_path(pid, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_now()} {redact_error_message(message if isinstance(message, str) else '')}\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    combined = (existing + line).encode("utf-8")
    if len(combined) > LOG_LIMIT_BYTES:
        combined = combined[-LOG_LIMIT_BYTES:]
    path.write_bytes(combined)
    return path
```

- [ ] **Step 4: Run workflow state tests**

Run: `python3 -m pytest -q tests/test_workflow_state.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/engines/workflow_state.py tests/test_workflow_state.py
git commit -m "feat: add structured workflow state"
```

## Task 5: Progress Log Persistence And Workflow APIs

**Files:**
- Modify: `app/engines/scheduler.py`
- Modify: `app/api/projects.py`
- Test: `tests/test_scheduler_progress.py`
- Test: `tests/test_project_patch.py`

- [ ] **Step 1: Write failing log/API tests**

Append to `tests/test_scheduler_progress.py`:

```python
def test_update_progress_appends_stage_log(tmp_project_dir):
    from app.engines.scheduler import update_progress
    from app.engines.workflow_state import stage_log_path

    update_progress("pid_log", stage="asr", local_pct=10, msg="正在识别")

    assert "正在识别" in stage_log_path("pid_log", "asr").read_text(encoding="utf-8")
```

Append to `tests/test_project_patch.py`:

```python
def test_workflow_state_endpoint_returns_project_state(client, tmp_project_dir):
    import json
    from app.utils.project_store import atomic_write_json

    pid = "workflow_api"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Workflow"})
    atomic_write_json(pdir / "workflow_state.json", {
        "version": 1,
        "stages": {"asr": {"status": "succeeded", "retry_count": 0}},
    })

    resp = client.get(f"/api/projects/{pid}/workflow-state")

    assert resp.status_code == 200
    assert resp.json()["stages"]["asr"]["status"] == "succeeded"


def test_workflow_log_endpoint_downloads_stage_log(client, tmp_project_dir):
    from app.utils.project_store import atomic_write_json

    pid = "workflow_log"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Workflow"})
    log_dir = pdir / "workflow_logs"
    log_dir.mkdir()
    (log_dir / "asr.log").write_text("hello log", encoding="utf-8")

    resp = client.get(f"/api/projects/{pid}/logs/asr")

    assert resp.status_code == 200
    assert "hello log" in resp.text
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_scheduler_progress.py::test_update_progress_appends_stage_log tests/test_project_patch.py::test_workflow_state_endpoint_returns_project_state tests/test_project_patch.py::test_workflow_log_endpoint_downloads_stage_log`

Expected: FAIL because log append and endpoints are missing.

- [ ] **Step 3: Append progress messages to stage logs**

In `app/engines/scheduler.py`, import:

```python
from app.engines.workflow_state import append_stage_log
```

At the end of `update_progress()`, after the `progress.json` write attempt, add:

```python
    if stage and payload["message"]:
        try:
            append_stage_log(pid, stage, payload["message"])
        except Exception as e:
            log.warning("append workflow log failed pid=%s stage=%s: %s", pid, stage, e)
```

- [ ] **Step 4: Add workflow-state and log endpoints**

In `app/api/projects.py`, import `FileResponse`:

```python
from fastapi.responses import FileResponse
```

Add endpoints near `get_progress` or before subtitle routes:

```python
@router.get("/{pid}/workflow-state")
def get_workflow_state(pid: str = PathParam(pattern=PID_PATTERN)):
    from app.engines.workflow_state import load_workflow_state

    _load_project(pid)
    return load_workflow_state(pid)


@router.get("/{pid}/logs/{stage}")
def download_workflow_log(pid: str = PathParam(pattern=PID_PATTERN), stage: str = ""):
    from app.engines.workflow_state import stage_log_path

    _load_project(pid)
    try:
        path = stage_log_path(pid, stage)
    except ValueError:
        raise HTTPException(400, "invalid stage")
    if not path.is_file():
        raise HTTPException(404, "log not found")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=f"{pid}-{stage}.log")
```

- [ ] **Step 5: Run log/API tests**

Run: `python3 -m pytest -q tests/test_scheduler_progress.py tests/test_project_patch.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/engines/scheduler.py app/api/projects.py tests/test_scheduler_progress.py tests/test_project_patch.py
git commit -m "feat: expose workflow state and logs"
```

## Task 6: Pipeline Workflow State Integration

**Files:**
- Modify: `app/api/translate.py`
- Test: `tests/test_translate_integration.py`
- Test: `tests/test_scheduler_cancel.py`

- [ ] **Step 1: Write failing pipeline state tests**

Append to `tests/test_translate_integration.py`:

```python
def test_start_asr_initializes_workflow_state(tmp_project_dir, monkeypatch):
    import json
    from app.api import translate
    from app.utils.project_store import atomic_write_json

    pid = "asr_workflow_init"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Workflow",
        "video_path": str(pdir / "video.mp4"),
        "audio_tracks": [],
    })
    (pdir / "video.mp4").write_bytes(b"video")
    monkeypatch.setattr(translate, "try_register_task", lambda pid, factory, reset_cancellation=False: factory())

    from app.main import app
    from fastapi.testclient import TestClient

    resp = TestClient(app).post(f"/api/projects/{pid}/start-asr", json={"language": "auto"})

    assert resp.status_code == 200
    state = json.loads((pdir / "workflow_state.json").read_text(encoding="utf-8"))
    assert "asr" in state["stages"]
```

Append to `tests/test_scheduler_cancel.py`:

```python
def test_cancel_marks_workflow_stage_cancelled(tmp_project_dir):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.utils.project_store import atomic_write_json

    pid = "cancel_workflow"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Cancel",
        "status": "processing",
        "pipeline_stage": "asr",
    })

    resp = TestClient(app).post(f"/api/projects/{pid}/cancel")

    assert resp.status_code == 200
    state = TestClient(app).get(f"/api/projects/{pid}/workflow-state").json()
    assert state["stages"]["asr"]["status"] == "cancelled"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_translate_integration.py::test_start_asr_initializes_workflow_state tests/test_scheduler_cancel.py::test_cancel_marks_workflow_stage_cancelled`

Expected: FAIL because workflow-state integration is missing.

- [ ] **Step 3: Add workflow helpers in translate API**

In `app/api/translate.py`, import:

```python
from app.engines.workflow_state import (
    cancel_workflow,
    fail_stage,
    finish_stage,
    reset_workflow,
    start_stage,
)
```

Add helper:

```python
def _reset_workflow_for_action(pid: str, action: str) -> None:
    stages = {
        "asr": ["asr"],
        "translate": ["translate"],
        "full": ["asr", "translate", "burn"],
        "burn": ["burn"],
    }[action]
    reset_workflow(pid, stages)
```

Call `_reset_workflow_for_action()` in `start_asr`, `start_translate`, `start_full`, and `start_burn` before thread start after `_persist_workflow_options()` succeeds.

- [ ] **Step 4: Mark stage lifecycle in pipelines**

In `_run_asr_pipeline()`, after loading project/video path, call:

```python
            start_stage(pid, "asr", input_artifact=project.get("video_path", ""))
```

Before successful ASR return after embedded subtitles and after normal ASR completion, call:

```python
            finish_stage(pid, "asr", output_artifact="filtered.srt", resume_eligible=True)
```

In the ASR `except` block before `_emit_progress`, call:

```python
        try:
            fail_stage(pid, "asr", e)
        except Exception:
            pass
```

Repeat the same pattern for `_run_translate_pipeline()` with `translate` and output `translated.srt`, and `_run_burn_pipeline()`/standalone burn with `burn` and output video path when available.

In `cancel_task()`, after determining `stage`, call:

```python
        try:
            cancel_workflow(pid, stage)
        except Exception:
            pass
```

- [ ] **Step 5: Run pipeline workflow tests**

Run: `python3 -m pytest -q tests/test_translate_integration.py tests/test_scheduler_cancel.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/translate.py tests/test_translate_integration.py tests/test_scheduler_cancel.py
git commit -m "feat: record pipeline workflow stages"
```

## Task 7: Retry And Resume APIs

**Files:**
- Modify: `app/api/translate.py`
- Modify: `app/engines/workflow_state.py`
- Test: `tests/test_translate_integration.py`

- [ ] **Step 1: Write failing retry/resume tests**

Append to `tests/test_translate_integration.py`:

```python
def test_retry_rejects_active_task(tmp_project_dir, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import translate
    from app.utils.project_store import atomic_write_json

    pid = "retry_busy"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "status": "error", "pipeline_stage": None})
    monkeypatch.setattr(translate, "is_task_registered", lambda _pid: True)

    resp = TestClient(app).post(f"/api/projects/{pid}/retry", json={"stage": "asr"})

    assert resp.status_code == 409


def test_resume_chooses_translate_when_filtered_srt_exists(tmp_project_dir, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import translate
    from app.utils.project_store import atomic_write_json

    pid = "resume_translate"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "status": "error",
        "pipeline_stage": None,
        "target_language": "简体中文",
    })
    (pdir / "filtered.srt").write_text("1\\n00:00:00,000 --> 00:00:01,000\\nHi\\n", encoding="utf-8")
    monkeypatch.setattr(translate, "require_translation_ready", lambda: {"translation_ready": True})
    monkeypatch.setattr(translate, "try_register_task", lambda pid, factory, reset_cancellation=False: factory())

    resp = TestClient(app).post(f"/api/projects/{pid}/resume")

    assert resp.status_code == 200
    assert resp.json()["stage"] == "translate"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_translate_integration.py::test_retry_rejects_active_task tests/test_translate_integration.py::test_resume_chooses_translate_when_filtered_srt_exists`

Expected: FAIL because endpoints are missing.

- [ ] **Step 3: Add retry/resume request models and helpers**

In `app/api/translate.py`, add:

```python
class RetryRequest(BaseModel):
    stage: Optional[str] = None


def _latest_failed_stage(pid: str) -> str:
    from app.engines.workflow_state import load_workflow_state

    state = load_workflow_state(pid)
    for stage in ("burn", "translate", "asr", "download"):
        if state.get("stages", {}).get(stage, {}).get("status") == "failed":
            return stage
    return "asr"


def _resume_stage_for_project(pid: str) -> str:
    pdir = PROJECTS_DIR / pid
    if (pdir / "translated.srt").is_file() or (pdir / "bilingual.srt").is_file():
        return "burn"
    if any((pdir / name).is_file() for name in ("filtered.srt", "raw.srt", "native.srt")):
        return "translate"
    return "asr"
```

- [ ] **Step 4: Add retry/resume endpoints**

Add endpoints after `start_full()`:

```python
@router.post("/{pid}/retry")
def retry_stage(pid: str = PathParam(pattern=PID_PATTERN), req: RetryRequest = RetryRequest()):
    project = _load_project(pid)
    if is_task_registered(pid):
        raise HTTPException(409, "Task already running for this project")
    _reject_busy_project(project)
    stage = req.stage if isinstance(req.stage, str) and req.stage.strip() else _latest_failed_stage(pid)
    stage = stage.strip()
    if stage == "asr":
        return start_asr(pid, ASRRequest(language=project.get("asr_language")))
    if stage == "translate":
        return start_translate(pid, TranslateRequest(target_language=project.get("target_language")))
    if stage == "burn":
        return start_burn(pid)
    raise HTTPException(400, "stage must be asr, translate, or burn")


@router.post("/{pid}/resume")
def resume_workflow(pid: str = PathParam(pattern=PID_PATTERN)):
    project = _load_project(pid)
    if is_task_registered(pid):
        raise HTTPException(409, "Task already running for this project")
    _reject_busy_project(project)
    stage = _resume_stage_for_project(pid)
    if stage == "translate":
        response = start_translate(pid, TranslateRequest(target_language=project.get("target_language")))
    elif stage == "burn":
        response = start_burn(pid)
    else:
        response = start_asr(pid, ASRRequest(language=project.get("asr_language")))
    return {**response, "stage": stage}
```

If direct function calls conflict with FastAPI default model instantiation, refactor shared launch logic into private helpers inside the same commit. Keep `TaskAlreadyRunning` protection and translation readiness checks.

- [ ] **Step 5: Run retry/resume tests**

Run: `python3 -m pytest -q tests/test_translate_integration.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/translate.py tests/test_translate_integration.py
git commit -m "feat: add workflow retry and resume APIs"
```

## Task 8: Frontend Workflow State Controls

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `app/static/index.html`
- Test: `tests/test_frontend_loading_js.py`
- Test: `tests/test_frontend_accessibility.py`

- [ ] **Step 1: Write failing frontend workflow tests**

Append to `tests/test_frontend_loading_js.py`:

```python
def test_frontend_loads_workflow_state_and_retries_failed_stage():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          const calls = [];
          state.toast = () => {};
          state.currentProject = {id: 'p1'};
          state.api = async (url, method = 'GET', body = null) => {
            calls.push({url, method, body});
            if (url === '/api/projects/p1/workflow-state') {
              return {stages: {translate: {status: 'failed', error_summary: 'bad key'}}};
            }
            if (url === '/api/projects/p1/retry' && method === 'POST') {
              return {status: 'started'};
            }
            throw new Error(`unexpected ${method} ${url}`);
          };

          await state.loadWorkflowState();
          if (state.workflowState.stages.translate.status !== 'failed') {
            throw new Error('expected failed translate state');
          }
          await state.retryWorkflowStage('translate');
          if (!calls.some((c) => c.url === '/api/projects/p1/retry' && c.body.stage === 'translate')) {
            throw new Error(`missing retry call ${JSON.stringify(calls)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr
```

Append to `tests/test_frontend_accessibility.py`:

```python
def test_workflow_state_controls_are_present():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "workflowState" in js
    assert "loadWorkflowState" in js
    assert "@click=\"retryWorkflowStage" in html
    assert "@click=\"resumeWorkflow()" in html
    assert "下载日志" in html
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_frontend_loading_js.py::test_frontend_loads_workflow_state_and_retries_failed_stage tests/test_frontend_accessibility.py::test_workflow_state_controls_are_present`

Expected: FAIL because frontend state/methods/markup are missing.

- [ ] **Step 3: Add workflow state methods**

In `app/static/js/app.js`, add state:

```javascript
    workflowState: null,
    workflowStateLoading: false,
    workflowStateError: '',
    workflowActionPending: '',
```

Add methods near progress/project actions:

```javascript
    async loadWorkflowState() {
      if (!this.currentProject?.id) {
        this.workflowState = null;
        this.workflowStateError = '';
        return;
      }
      this.workflowStateLoading = true;
      try {
        this.workflowState = await this.api(`/api/projects/${this.currentProject.id}/workflow-state`);
        this.workflowStateError = '';
      } catch (e) {
        this.workflowStateError = e.message || '无法加载工作流状态';
      } finally {
        this.workflowStateLoading = false;
      }
    },

    workflowFailedStages() {
      const stages = this.workflowState?.stages || {};
      return Object.entries(stages)
        .filter(([, item]) => item?.status === 'failed')
        .map(([stage, item]) => ({stage, ...item}));
    },

    async retryWorkflowStage(stage) {
      if (!this.currentProject?.id || this.workflowActionPending) return;
      this.workflowActionPending = `retry:${stage}`;
      try {
        await this.api(`/api/projects/${this.currentProject.id}/retry`, 'POST', {stage});
        this.currentProject.status = 'processing';
        this.toast('已重新启动失败阶段');
      } catch (e) {
        this.toast(e.message, 'error');
      } finally {
        this.workflowActionPending = '';
      }
    },

    async resumeWorkflow() {
      if (!this.currentProject?.id || this.workflowActionPending) return;
      this.workflowActionPending = 'resume';
      try {
        await this.api(`/api/projects/${this.currentProject.id}/resume`, 'POST');
        this.currentProject.status = 'processing';
        this.toast('已恢复工作流');
      } catch (e) {
        this.toast(e.message, 'error');
      } finally {
        this.workflowActionPending = '';
      }
    },
```

Call `await this.loadWorkflowState()` in `openProject()` after `currentProject` assignment and in `pollProgress()` when a project leaves processing.

- [ ] **Step 4: Add workflow controls markup**

In project detail below the progress panel, add:

```html
          <div x-show="workflowState" class="glass rounded-2xl p-4 mt-4">
            <div class="flex items-center justify-between gap-3">
              <h3 class="text-[13px] font-semibold">工作流状态</h3>
              <button @click="resumeWorkflow()"
                      :disabled="workflowActionPending || projectActionsDisabled(currentProject)"
                      class="btn-secondary px-3 py-1.5 rounded-lg text-[12px] disabled:opacity-50">恢复</button>
            </div>
            <div class="mt-3 space-y-2">
              <template x-for="item in workflowFailedStages()" :key="item.stage">
                <div class="flex items-center justify-between gap-3 rounded-lg border border-danger/20 px-3 py-2 text-[12px]">
                  <span class="min-w-0 truncate" x-text="`${item.stage}: ${item.error_summary || '失败'}`"></span>
                  <div class="flex items-center gap-2">
                    <a :href="`/api/projects/${currentProject.id}/logs/${item.stage}`" class="text-accent">下载日志</a>
                    <button @click="retryWorkflowStage(item.stage)"
                            :disabled="!!workflowActionPending"
                            class="btn-primary px-2.5 py-1 rounded-lg text-[12px] disabled:opacity-50">重试</button>
                  </div>
                </div>
              </template>
            </div>
          </div>
```

- [ ] **Step 5: Run frontend workflow tests**

Run: `python3 -m pytest -q tests/test_frontend_loading_js.py tests/test_frontend_accessibility.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/static/js/app.js app/static/index.html tests/test_frontend_loading_js.py tests/test_frontend_accessibility.py
git commit -m "feat: add workflow recovery controls"
```

## Task 9: Documentation And Verification

**Files:**
- Modify: `docs/USAGE.md`
- Modify: `docs/USAGE.zh-CN.md`
- Modify: `docs/RELEASE_NOTES.md`
- Modify: `docs/RELEASE_NOTES.zh-CN.md`
- Test: existing focused suites

- [ ] **Step 1: Document ASR modes in English**

Add to `docs/USAGE.md` under ASR/settings:

```markdown
### ASR Modes

The ASR settings expose three intent-level modes:

- **Speed first** chooses the fastest available local backend, usually
  `mlx-whisper` on Apple Silicon with `large-v3-turbo`.
- **Accuracy first** prefers a larger model and a backend that supports VAD
  and beam search when available.
- **Offline first** prefers already bundled or cached models and reports when
  a download is still required.

`/api/system-check` reports detected ASR backends, model cache status, and the
current recommendation. The default tests simulate these capabilities and do
not download models.
```

- [ ] **Step 2: Document workflow recovery in English**

Add to `docs/USAGE.md`:

```markdown
### Workflow Recovery

Each long-running project workflow writes a local `workflow_state.json` and
bounded per-stage logs under the project directory. When a stage fails, the
project detail view can show the failing stage, download its log, retry that
stage, or resume from the last verified artifact.

Retry and resume respect the same task locks as normal processing, so they do
not start while another task is active for the project.
```

- [ ] **Step 3: Add Simplified Chinese docs**

Add equivalent sections to `docs/USAGE.zh-CN.md`:

```markdown
### ASR 模式

ASR 设置提供三个意图级模式：

- **速度优先**：选择当前最快的本地后端，Apple Silicon 上通常是
  `mlx-whisper` 与 `large-v3-turbo`。
- **准确优先**：优先较大模型，并在可用时选择支持 VAD 和 beam search 的后端。
- **离线优先**：优先使用已内置或已缓存模型，并明确提示是否仍需下载模型。

`/api/system-check` 会返回本机 ASR 后端、模型缓存状态和当前推荐。默认测试只
模拟这些能力，不会下载模型。

### 工作流恢复

每个长任务会在项目目录写入本地 `workflow_state.json`，并保存有大小上限的阶段
日志。阶段失败后，项目详情页可以展示失败阶段、下载日志、重试该阶段，或从最后
一个已验证产物继续恢复。

重试和恢复会复用现有任务锁，不会在项目已有任务运行时并发启动。
```

- [ ] **Step 4: Update bilingual release notes**

Add a new unreleased entry or extend the current unreleased milestone entry in both release-note files:

```markdown
- Added intent-level ASR modes with backend/model recommendation details.
- Added structured workflow state, bounded stage logs, retry, resume, and log download.
```

Chinese:

```markdown
- 新增 ASR 意图模式，并展示后端/模型推荐信息。
- 新增结构化工作流状态、有界阶段日志、重试、恢复和日志下载。
```

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
python3 -m pytest -q tests/test_asr_capabilities.py tests/test_config.py tests/test_settings_claude_cli.py tests/test_frontend_settings_js.py tests/test_frontend_accessibility.py tests/test_workflow_state.py tests/test_scheduler_progress.py tests/test_scheduler_cancel.py tests/test_project_patch.py tests/test_translate_integration.py tests/test_frontend_loading_js.py
node --check app/static/js/app.js
git diff --check
python3 -m pytest -q
```

Expected: PASS. Record the exact full-suite count in the PR body.

- [ ] **Step 6: Commit docs**

```bash
git add docs/USAGE.md docs/USAGE.zh-CN.md docs/RELEASE_NOTES.md docs/RELEASE_NOTES.zh-CN.md
git commit -m "docs: document ASR modes and workflow recovery"
```

## Task 10: Final Review And Branch Finish

**Files:**
- No planned source edits unless review finds defects.

- [ ] **Step 1: Run milestone verification gate**

Run:

```bash
python3 -m pytest -q tests/test_asr_capabilities.py tests/test_workflow_state.py tests/test_scheduler_progress.py tests/test_scheduler_cancel.py tests/test_project_patch.py tests/test_translate_integration.py tests/test_frontend_settings_js.py tests/test_frontend_loading_js.py tests/test_frontend_accessibility.py
node --check app/static/js/app.js
git diff --check
python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Request code review**

Dispatch a read-only reviewer over `2bbdc80..HEAD` with this review focus:

- ASR mode recommendation handles absent optional packages without import-time failures.
- System-check payload remains backward compatible.
- Workflow logs redact secrets and stay bounded.
- Retry/resume cannot run concurrently with active project tasks.
- Resume only starts from verified local artifacts.
- Frontend controls do not enable retry/resume while busy.
- Existing progress WebSocket and polling behavior still works.

- [ ] **Step 3: Address review**

If review returns changes, fix them in focused commits, rerun the affected tests, and request re-review.

- [ ] **Step 4: Finish branch**

Use `finishing-a-development-branch`:

- Push branch `codex/milestone2-workflow-asr`.
- Create a stacked PR against `codex/milestone1-quality-kb-core`.
- PR title: `feat: add ASR recommendations and workflow recovery`.
- PR body must include focused tests, full-suite result, and note that no new package/app was built.
