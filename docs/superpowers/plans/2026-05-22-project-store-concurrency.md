# project.json 安全并发访问 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉代码审计的 4 个高危问题(路径遍历、`active_tasks` 竞态、JSON 非原子写入、`project.json` 读改写丢失更新),方法是把"安全访问 project.json"收敛成一个独立、可测试的基础设施模块。

**Architecture:** 新增 `app/utils/project_store.py`:pid 校验(防路径遍历)+ 原子 JSON 写入(`tmp + os.replace`)+ per-pid `RLock` + `mutate_project` 读改写助手。`api`/`engines`/`config` 层的散落 load/save 调用收敛到该模块。纯读不加锁(`os.replace` 保证读不到写半文件),只有读-改-写序列加锁。

**Tech Stack:** Python 3.9、FastAPI、pytest、`threading`、`os.replace`。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `app/utils/project_store.py` | pid 校验、原子写、per-pid 锁、`mutate_project` | 新建 |
| `tests/test_project_store.py` | `project_store` 全部单元测试 | 新建 |
| `tests/test_task_registration.py` | `active_tasks` 并发注册测试 | 新建 |
| `app/config.py` | `Config.save` 改原子写 | 修改 |
| `app/engines/knowledge.py` | `KnowledgeBase.save` 改原子写 | 修改 |
| `app/api/projects.py` | `_load_project`/`_save_project` 委托;`patch_project`/`tmdb_search` 用 `mutate_project`;路由加 pid 校验 | 修改 |
| `app/api/translate.py` | save 站点改 `mutate_project`;`active_tasks` 加锁;路由加 pid 校验 | 修改 |
| `app/engines/trailer_pipeline.py` | `_save_partial` 改 `mutate_project` | 修改 |
| `app/main.py` | `download_video` 路由加 pid 校验 | 修改 |
| `tests/test_project_patch.py` | 补非法 pid 路由测试 | 修改 |

每个测试命令在仓库根目录 `/Users/gaopengxiang/Desktop/AI_Sub_Pro` 下运行,前缀 `python3 -m pytest`。

---

## Task 1: `validate_pid` + `project_dir`(pid 校验,防路径遍历)

**Files:**
- Create: `app/utils/project_store.py`
- Test: `tests/test_project_store.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_project_store.py`:

```python
import json
import threading

import pytest

from app.utils import project_store


def test_validate_pid_accepts_normal_id():
    assert project_store.validate_pid("a1b2c3d4") == "a1b2c3d4"


@pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "", "x" * 65, "a.b", "/abs", "a\\b"])
def test_validate_pid_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        project_store.validate_pid(bad)


def test_project_dir_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    with pytest.raises(ValueError):
        project_store.project_dir("../outside")


def test_project_dir_normal(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    assert project_store.project_dir("abcd1234") == (tmp_path / "abcd1234").resolve()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_project_store.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.utils.project_store'`

- [ ] **Step 3: 创建模块的最小实现**

创建 `app/utils/project_store.py`:

```python
"""Safe concurrent access to per-project JSON state.

Centralizes: pid validation (path-traversal defense), atomic JSON writes
(crash-safe, never leaves a torn file), and per-project locking for
read-modify-write sequences.

Framework-agnostic — does not import FastAPI. The API layer translates the
`ValueError` / `FileNotFoundError` raised here into HTTP responses.
"""
import json
import os
import re
import threading
from pathlib import Path
from typing import Callable, Optional

from app.config import PROJECTS_DIR

PID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_PID_RE = re.compile(PID_PATTERN)


def validate_pid(pid: str) -> str:
    """Return `pid` unchanged if it is a safe project id, else raise ValueError."""
    if not isinstance(pid, str) or not _PID_RE.match(pid):
        raise ValueError(f"invalid project id: {pid!r}")
    return pid


def project_dir(pid: str) -> Path:
    """Resolve a project directory, rejecting any pid that escapes PROJECTS_DIR."""
    validate_pid(pid)
    root = Path(PROJECTS_DIR).resolve()
    pdir = (root / pid).resolve()
    if not pdir.is_relative_to(root):
        raise ValueError(f"project id escapes projects dir: {pid!r}")
    return pdir
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_project_store.py -v`
Expected: PASS(4 个测试)

- [ ] **Step 5: 提交**

```bash
git add app/utils/project_store.py tests/test_project_store.py
git commit -m "feat(project-store): pid validation + path-traversal-safe project_dir"
```

---

## Task 2: `atomic_write_json`(原子写入,防文件截断)

**Files:**
- Modify: `app/utils/project_store.py`
- Test: `tests/test_project_store.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_project_store.py` 末尾追加:

```python
def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "x.json"
    project_store.atomic_write_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert not (tmp_path / "x.json.tmp").exists()


def test_atomic_write_preserves_original_on_failure(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    p.write_text('{"original": true}', encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(project_store.json, "dump", boom)
    with pytest.raises(RuntimeError):
        project_store.atomic_write_json(p, {"new": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"original": True}
    assert not (tmp_path / "x.json.tmp").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_project_store.py -k atomic_write -v`
Expected: FAIL —— `AttributeError: module 'app.utils.project_store' has no attribute 'atomic_write_json'`

- [ ] **Step 3: 实现 `atomic_write_json`**

在 `app/utils/project_store.py` 的 `project_dir` 之后追加:

```python
def atomic_write_json(path: Path, data: dict) -> None:
    """Write `data` as JSON to `path` atomically.

    Writes a sibling `<name>.tmp` file then `os.replace`s it into place. On
    failure the original file is left untouched and the `.tmp` is removed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_project_store.py -k atomic_write -v`
Expected: PASS(2 个测试)

- [ ] **Step 5: 提交**

```bash
git add app/utils/project_store.py tests/test_project_store.py
git commit -m "feat(project-store): crash-safe atomic_write_json"
```

---

## Task 3: `get_project_lock` + `load_project` + `mutate_project`(防丢失更新)

**Files:**
- Modify: `app/utils/project_store.py`
- Test: `tests/test_project_store.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_project_store.py` 末尾追加:

```python
def _make_project(tmp_path, monkeypatch, pid="proj0001"):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    pdir = tmp_path / pid
    pdir.mkdir()
    project_store.atomic_write_json(pdir / "project.json", {"counter": 0})
    return pid


def test_load_project_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        project_store.load_project("nope0001")


def test_load_project_reads_data(tmp_path, monkeypatch):
    pid = _make_project(tmp_path, monkeypatch)
    assert project_store.load_project(pid) == {"counter": 0}


def test_mutate_project_serializes_concurrent_writes(tmp_path, monkeypatch):
    pid = _make_project(tmp_path, monkeypatch)
    threads_n, per_thread = 8, 50

    def bump():
        for _ in range(per_thread):
            project_store.mutate_project(
                pid, lambda p: p.__setitem__("counter", p["counter"] + 1)
            )

    ts = [threading.Thread(target=bump) for _ in range(threads_n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert project_store.load_project(pid)["counter"] == threads_n * per_thread


def test_mutate_project_applies_normalize(tmp_path, monkeypatch):
    pid = _make_project(tmp_path, monkeypatch)

    def normalize(d):
        d.setdefault("added_by_normalize", True)
        return d

    result = project_store.mutate_project(
        pid, lambda p: p.__setitem__("counter", 99), normalize=normalize
    )
    assert result["counter"] == 99
    assert result["added_by_normalize"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_project_store.py -k "mutate or load_project" -v`
Expected: FAIL —— `AttributeError: ... has no attribute 'load_project'`

- [ ] **Step 3: 实现锁注册表 + `load_project` + `mutate_project`**

在 `app/utils/project_store.py` 末尾追加(并确认顶部 `import` 已含 `Callable, Optional`):

```python
_locks: dict = {}
_locks_guard = threading.Lock()


def get_project_lock(pid: str) -> threading.RLock:
    """Return the process-wide RLock for `pid`, creating it on first use."""
    validate_pid(pid)
    lock = _locks.get(pid)
    if lock is None:
        with _locks_guard:
            lock = _locks.get(pid)
            if lock is None:
                lock = threading.RLock()
                _locks[pid] = lock
    return lock


def load_project(pid: str) -> dict:
    """Read project.json. Raises FileNotFoundError if the project is absent.

    No lock is taken — writes go through atomic os.replace, so a reader always
    sees either the complete old file or the complete new file.
    """
    pfile = project_dir(pid) / "project.json"
    if not pfile.exists():
        raise FileNotFoundError(f"project not found: {pid}")
    with open(pfile, "r", encoding="utf-8") as f:
        return json.load(f)


def mutate_project(
    pid: str,
    fn: Callable[[dict], None],
    *,
    normalize: Optional[Callable[[dict], dict]] = None,
) -> dict:
    """Atomically read-modify-write project.json under the per-pid lock.

    `fn` mutates the loaded dict in place. `normalize` (optional) is applied to
    the freshly loaded dict before `fn` runs (used to backfill default fields).
    Returns the final dict that was written.
    """
    with get_project_lock(pid):
        pfile = project_dir(pid) / "project.json"
        if not pfile.exists():
            raise FileNotFoundError(f"project not found: {pid}")
        with open(pfile, "r", encoding="utf-8") as f:
            data = json.load(f)
        if normalize is not None:
            data = normalize(data)
        fn(data)
        atomic_write_json(pfile, data)
        return data
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_project_store.py -v`
Expected: PASS(全部 10 个测试)。`test_mutate_project_serializes_concurrent_writes` 期望 `counter == 400` —— 没有锁会因丢失更新得到小于 400 的值。

- [ ] **Step 5: 提交**

```bash
git add app/utils/project_store.py tests/test_project_store.py
git commit -m "feat(project-store): per-pid lock + load_project + mutate_project"
```

---

## Task 4: `config.json` / `knowledge.json` 改用原子写入

**Files:**
- Modify: `app/config.py:107-110`
- Modify: `app/engines/knowledge.py:78-85`
- Test: `tests/test_config.py`(扩展)

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 末尾追加(若已有同名导入则复用):

```python
def test_config_save_is_atomic(tmp_path, monkeypatch):
    import json as _json
    from app import config as cfg

    target = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", target)
    cfg.Config._data = {"k": "v"}

    real_dump = _json.dump

    def boom(*a, **k):
        raise RuntimeError("disk full")

    target.write_text('{"existing": 1}', encoding="utf-8")
    monkeypatch.setattr("app.utils.project_store.json.dump", boom)
    import pytest
    with pytest.raises(RuntimeError):
        cfg.Config.save()
    # original file survived the failed write
    assert _json.loads(target.read_text(encoding="utf-8")) == {"existing": 1}
    assert not (tmp_path / "config.json.tmp").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_config.py -k atomic -v`
Expected: FAIL —— 当前 `Config.save` 直接 `json.dump` 到真实文件,原文件被截断,断言不成立。

- [ ] **Step 3: 改 `Config.save` 与 `KnowledgeBase.save`**

`app/config.py` —— 把 `save` 方法(当前 107-110 行)替换为:

```python
    @classmethod
    def save(cls):
        from app.utils.project_store import atomic_write_json
        atomic_write_json(CONFIG_FILE, cls._data)
```

`app/engines/knowledge.py` —— 把 `save` 方法(当前 78-85 行)替换为:

```python
    def save(self) -> None:
        from app.utils.project_store import atomic_write_json
        data = {k: p.to_dict() for k, p in self._projects.items()}
        atomic_write_json(Path(KB_FILE), data)
```

(两处用函数内 `import` 避免模块导入期循环依赖。)

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_config.py tests/test_knowledge_base_v2.py tests/test_kb_migration.py -v`
Expected: PASS —— 新原子测试通过,KB 相关现有测试无回归。

- [ ] **Step 5: 提交**

```bash
git add app/config.py app/engines/knowledge.py tests/test_config.py
git commit -m "fix(io): atomic writes for config.json and knowledge.json"
```

---

## Task 5: `active_tasks` 加锁(防并发启动同一项目两条流水线)

**Files:**
- Modify: `app/api/translate.py`(`active_tasks` 定义附近,约 38 行)
- Test: `tests/test_task_registration.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_task_registration.py`:

```python
import threading

import pytest

from app.api import translate


def test_try_register_task_rejects_duplicate(monkeypatch):
    monkeypatch.setattr(translate, "active_tasks", {})
    factory = lambda: threading.Thread(target=lambda: None)
    translate.try_register_task("p1", factory)
    with pytest.raises(translate.TaskAlreadyRunning):
        translate.try_register_task("p1", factory)


def test_unregister_allows_reregister(monkeypatch):
    monkeypatch.setattr(translate, "active_tasks", {})
    factory = lambda: threading.Thread(target=lambda: None)
    translate.try_register_task("p1", factory)
    translate.unregister_task("p1")
    translate.try_register_task("p1", factory)  # must not raise


def test_concurrent_register_single_winner(monkeypatch):
    monkeypatch.setattr(translate, "active_tasks", {})
    barrier = threading.Barrier(10)
    results = []
    lock = threading.Lock()

    def attempt():
        barrier.wait()
        try:
            translate.try_register_task(
                "p1", lambda: threading.Thread(target=lambda: None)
            )
            outcome = "ok"
        except translate.TaskAlreadyRunning:
            outcome = "rejected"
        with lock:
            results.append(outcome)

    ts = [threading.Thread(target=attempt) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count("ok") == 1
    assert results.count("rejected") == 9
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_task_registration.py -v`
Expected: FAIL —— `AttributeError: module 'app.api.translate' has no attribute 'TaskAlreadyRunning'`

- [ ] **Step 3: 加 `TaskAlreadyRunning` + 注册助手**

在 `app/api/translate.py` 中 `active_tasks: Dict[str, threading.Thread] = {}` 那一行(约 38 行)的紧下方追加:

```python
_tasks_lock = threading.Lock()


class TaskAlreadyRunning(Exception):
    """Raised when a pipeline task is already registered for a project."""

    def __init__(self, pid: str):
        super().__init__(f"task already running for {pid}")
        self.pid = pid


def try_register_task(pid: str, factory):
    """Atomically register a pipeline thread for `pid`.

    Raises TaskAlreadyRunning if one is already registered. The returned thread
    is NOT started — the caller starts it after this returns.
    """
    with _tasks_lock:
        if pid in active_tasks:
            raise TaskAlreadyRunning(pid)
        t = factory()
        active_tasks[pid] = t
    return t


def unregister_task(pid: str) -> None:
    """Remove `pid` from the active-task registry (safe if absent)."""
    with _tasks_lock:
        active_tasks.pop(pid, None)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_task_registration.py -v`
Expected: PASS(3 个测试)

- [ ] **Step 5: 提交**

```bash
git add app/api/translate.py tests/test_task_registration.py
git commit -m "feat(translate): lock-guarded active_tasks registration"
```

---

## Task 6: `projects.py` —— 收敛 IO + 路由 pid 校验

**Files:**
- Modify: `app/api/projects.py`

本任务为重构,无新增行为测试 —— 由 `project_store` 单元测试(Task 1-3)与全量回归(Task 10)守护。

- [ ] **Step 1: 在 `app/api/projects.py` 顶部 import 区追加**

```python
from fastapi import Path as PathParam
from app.utils.project_store import (
    project_dir as _ps_project_dir,
    load_project as _ps_load_project,
    mutate_project,
    atomic_write_json,
    PID_PATTERN,
)
```

- [ ] **Step 2: 把 `_project_dir` / `_load_project` / `_save_project`(111-128 行)替换为委托实现**

```python
def _project_dir(pid: str) -> Path:
    return _ps_project_dir(pid)


def _load_project(pid: str) -> dict:
    try:
        return _apply_safe_defaults(_ps_load_project(pid))
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    except ValueError:
        raise HTTPException(400, "Invalid project id")


def _save_project(pid: str, data: dict):
    atomic_write_json(_ps_project_dir(pid) / "project.json", data)
```

- [ ] **Step 3: `patch_project`(361-375 行)改用 `mutate_project`**

```python
@router.patch("/{pid}")
def patch_project(req: PatchProjectReq, pid: str = PathParam(pattern=PID_PATTERN)):
    """Partially update a project. Only whitelisted fields are accepted.
    Pass field names in `clear` to explicitly set those fields to null."""
    payload = req.model_dump(exclude_unset=True, exclude={"clear"})

    def _apply(project):
        for k, v in payload.items():
            if k in _PATCHABLE_FIELDS:
                project[k] = v
        for k in (req.clear or []):
            if k in _PATCHABLE_FIELDS:
                project[k] = None

    try:
        return mutate_project(pid, _apply, normalize=_apply_safe_defaults)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
```

注意:`req`(无默认值)必须排在带默认值的 `pid` 之前,否则 Python 语法报错。

- [ ] **Step 4: `tmdb_search_for_project`(约 337-358 行)的 `_save_project` 收尾改 `mutate_project`**

把结尾的:

```python
    candidates = [_normalize_candidate(r, kind) for r in results[:10]]
    project["tmdb_candidates"] = candidates
    _save_project(pid, project)
    return {"candidates": candidates}
```

改为:

```python
    candidates = [_normalize_candidate(r, kind) for r in results[:10]]
    mutate_project(pid, lambda p: p.__setitem__("tmdb_candidates", candidates),
                   normalize=_apply_safe_defaults)
    return {"candidates": candidates}
```

- [ ] **Step 5: 给所有 `{pid}` 路由的 `pid` 参数加 `PathParam` 校验**

对 `app/api/projects.py` 中每个带 `{pid}` 的路由(`get_project`、`delete_project`、`reveal_in_finder`、`tmdb_search_for_project`,以及任何其他 `{pid}`/`{pid}/...` 路由),把签名里的 `pid: str` 改为 `pid: str = PathParam(pattern=PID_PATTERN)`。规则:若该函数还有**无默认值**的参数(如 Pydantic body),把它移到 `pid` 之前。`patch_project` 已在 Step 3 处理。

- [ ] **Step 6: 运行回归**

Run: `python3 -m pytest tests/test_project_patch.py tests/test_projects_loader.py tests/test_create_trailer_project.py tests/test_subtitle_picker.py -v`
Expected: PASS(无回归)

- [ ] **Step 7: 提交**

```bash
git add app/api/projects.py
git commit -m "refactor(projects): route project.json IO through project_store + pid validation"
```

---

## Task 7: `translate.py` —— save 站点改 `mutate_project` + 路由校验 + 用任务助手

**Files:**
- Modify: `app/api/translate.py`

- [ ] **Step 1: 顶部 import 区追加**

```python
from fastapi import Path as PathParam
from app.utils.project_store import mutate_project, PID_PATTERN
from app.api.projects import _apply_safe_defaults
```

(`_apply_safe_defaults` 若已导入则跳过。)

- [ ] **Step 2: 把每个"读-改-写"序列改为 `mutate_project`**

`translate.py` 中 `_save_project(pid, ...)` 出现在约 149/162/247/255/270/339/347/457/464/493 行。**规则:`mutate_project` 的 `fn` 只写本代码路径负责产生的字段,不要把早先 `_load_project` 得到的整个陈旧 dict 写回**(这正是修复丢失更新的关键)。

模式 A —— 阶段进度/状态更新:

```python
# 原:
project = _load_project(pid)
project["status"] = "translating"
_save_project(pid, project)
# 改为:
mutate_project(pid, lambda p: p.update({"status": "translating"}),
               normalize=_apply_safe_defaults)
```

模式 B —— 终态成功(写产出文件路径):

```python
# 原:
project = _load_project(pid)
project["status"] = "completed"
project["output_video"] = out_path
_save_project(pid, project)
# 改为:
mutate_project(pid, lambda p: p.update({"status": "completed",
                                        "output_video": out_path}),
               normalize=_apply_safe_defaults)
```

模式 C —— 错误收尾:

```python
# 原:
project = _load_project(pid)
project["status"] = "error"
project["error"] = str(e)[:200]
_save_project(pid, project)
# 改为:
mutate_project(pid, lambda p: p.update({"status": "error",
                                        "error": str(e)[:200]}),
               normalize=_apply_safe_defaults)
```

对于"函数开头 `_load_project` 读取输入、几十行后才 `_save_project`"的情况:保留开头的 `_load_project` 作为**只读输入**,在 save 点用 `mutate_project` 只写该阶段产生的字段。逐个把 10 处 `_save_project` 调用按上述模式改写。

- [ ] **Step 3: 4 个启动端点改用 `try_register_task` / `unregister_task`**

`start_asr`(501-515 行)改为:

```python
@router.post("/{pid}/start-asr")
def start_asr(pid: str = PathParam(pattern=PID_PATTERN), req: ASRRequest = ASRRequest()):
    """Start ASR pipeline."""
    project = _load_project(pid)
    audio_track = req.audio_track if req.audio_track is not None else project.get("selected_audio_track", 0)
    language = req.language or project.get("asr_language", "auto")
    try:
        t = try_register_task(pid, lambda: threading.Thread(
            target=_run_asr_pipeline, args=(pid, audio_track, language), daemon=True))
    except TaskAlreadyRunning:
        raise HTTPException(409, "Task already running for this project")
    t.start()
    return {"status": "started", "message": "ASR pipeline started"}
```

`start_translate`、`start-full`、`start-burn` 三个端点同样改造:删掉 `if pid in active_tasks: raise HTTPException(409, ...)` 和裸 `active_tasks[pid] = t`,改为 `try_register_task(pid, lambda: threading.Thread(...))` + `except TaskAlreadyRunning` + 锁外 `t.start()`。

- [ ] **Step 4: 全部 worker 的 `active_tasks.pop(pid, None)` 改为 `unregister_task(pid)`**

`translate.py` 中 worker `finally` 里的 `active_tasks.pop(pid, None)`(约 260/352/498 行)逐处替换为 `unregister_task(pid)`。

- [ ] **Step 5: 其余 `{pid}` 路由加 `PathParam` 校验**

`translate.py` 中其他带 `{pid}` 的路由(`cancel_task` 等),把 `pid: str` 改为 `pid: str = PathParam(pattern=PID_PATTERN)`,无默认值参数移到 `pid` 之前。

- [ ] **Step 6: 运行回归**

Run: `python3 -m pytest tests/test_translate_integration.py tests/test_translator_full_doc.py tests/test_scheduler_cancel.py tests/test_bilingual_burn_integration.py tests/test_startup_progress_restore.py -v`
Expected: PASS(无回归)

- [ ] **Step 7: 提交**

```bash
git add app/api/translate.py
git commit -m "refactor(translate): mutate_project for all writes + locked task registration"
```

---

## Task 8: `trailer_pipeline.py` —— `_save_partial` 改 `mutate_project`

**Files:**
- Modify: `app/engines/trailer_pipeline.py:83-87`

- [ ] **Step 1: 顶部 import 区追加**

```python
from app.utils.project_store import mutate_project
```

- [ ] **Step 2: 替换 `_save_partial`(83-87 行)**

```python
def _save_partial(pid: str, **fields) -> None:
    """Atomically merge `fields` into the project under the per-pid lock."""
    from app.api.projects import _apply_safe_defaults
    mutate_project(pid, lambda p: p.update(fields), normalize=_apply_safe_defaults)
```

- [ ] **Step 3: 运行回归**

Run: `python3 -m pytest tests/test_trailer_pipeline.py tests/test_trailer_api.py tests/test_create_trailer_project.py -v`
Expected: PASS(无回归)

- [ ] **Step 4: 提交**

```bash
git add app/engines/trailer_pipeline.py
git commit -m "refactor(trailer): _save_partial uses atomic locked mutate_project"
```

---

## Task 9: `main.py` —— `download_video` 路由 pid 校验

**Files:**
- Modify: `app/main.py:141-158`

- [ ] **Step 1: 顶部 import 区追加**

```python
from fastapi import Path as PathParam
from app.utils.project_store import PID_PATTERN
```

- [ ] **Step 2: 给 `download_video` 的 `pid` 加校验**

把签名 `def download_video(pid: str):` 改为:

```python
def download_video(pid: str = PathParam(pattern=PID_PATTERN)):
```

(`ws_progress` 无需改动:它只读内存中的 `progress_store`,从不用 `project_id` 拼文件路径,不存在路径遍历面。)

- [ ] **Step 3: 运行回归 + 手工冒烟**

Run: `python3 -m pytest tests/ -q`
Expected: 全量通过。
手工:启动 `python3 -m uvicorn app.main:app --port 18090`,`curl -i http://127.0.0.1:18090/api/projects/..%2F..%2Fetc/download-video` 应返回 422,不返回文件。

- [ ] **Step 4: 提交**

```bash
git add app/main.py
git commit -m "fix(main): validate pid on download-video route"
```

---

## Task 10: 全量回归 + 收尾

**Files:** 无

- [ ] **Step 1: 全量测试**

Run: `python3 -m pytest tests/ -v`
Expected: 全部通过(原 42 个测试文件 + 新增 `test_project_store.py`、`test_task_registration.py`,以及 `test_config.py`/`test_project_patch.py` 的新增用例)。

- [ ] **Step 2: 确认无残留裸调用**

Run: `grep -rn "_save_project" app/api/translate.py app/engines/trailer_pipeline.py`
Expected: 无输出(所有写入已收敛到 `mutate_project`)。
Run: `grep -rn "active_tasks\[" app/api/translate.py`
Expected: 无输出(不再有裸 `active_tasks[pid] = ...` 赋值)。

- [ ] **Step 3: 对照 spec 验收标准逐条核对**

逐条确认 `docs/superpowers/specs/2026-05-22-project-store-concurrency-design.md` §9 的 5 条验收标准均满足。

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "test: full regression green for project-store phase 1"
```

---

## Self-Review 结果

- **Spec 覆盖**:问题 1(Task 1/6/7/9 pid 校验)、问题 2(Task 5/7)、问题 3(Task 2/4/6)、问题 4(Task 3/6/7/8 `mutate_project`)—— 全部 spec §1 的 4 个问题与 §5 调用点清单均有对应任务;§6 测试策略对应 Task 1-3/5 的 TDD 与 Task 10 全量回归。
- **占位符扫描**:无 TBD / TODO / "类似 Task N";每个改代码的步骤都给出完整代码。
- **类型一致性**:`validate_pid`/`project_dir`/`atomic_write_json`/`load_project`/`mutate_project`/`get_project_lock`/`PID_PATTERN` 在 Task 1-3 定义,Task 4/6/7/8/9 引用名称一致;`TaskAlreadyRunning`/`try_register_task`/`unregister_task` 在 Task 5 定义,Task 7 引用一致;`mutate_project(pid, fn, *, normalize=...)` 签名在 Task 3 定义,后续调用一致。
