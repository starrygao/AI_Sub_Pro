# AI_Sub_Pro — project.json 安全并发访问(阶段 1)

**Date**: 2026-05-22
**Scope**: 全项目代码审计后 4 阶段修复计划的**阶段 1**。本 spec 覆盖数据完整性与安全相关的 4 个高危问题。
**前置**: 代码审计报告(2026-05-22,31 个问题)。后续阶段(子进程健壮性、流水线逻辑、输入校验与前端)各自独立成 spec。

---

## 1. 目标

修掉 4 个互相关联的高危问题,它们都围绕"磁盘 JSON 状态的安全并发访问":

| # | 问题 | 位置 |
|---|---|---|
| 1 | **路径遍历** —— `pid` 完全未校验,`PROJECTS_DIR / pid` 可逃逸 | `projects.py:111-112` 及所有 `{pid}` 路由 |
| 2 | **`active_tasks` 检查-写入竞态** —— 并发请求可对同一项目启动两条流水线 | `translate.py:504/521/537/559` |
| 3 | **JSON 写入非原子** —— 进程中断/并发写截断文件,后续 `json.load` 永久失败 | `projects.py:124-128`、`config.py:108-110`、`knowledge.py:78-85` |
| 4 | **`project.json` 读-改-写丢失更新** —— 流水线线程与 API PATCH 互相覆盖 | `translate.py` 15+ 处 load/save 配对 |

**核心做法**:把"安全访问 project.json"收敛成一个有明确边界、可独立测试的基础设施单元。

## 2. 范围

### 包含
- 新模块 `app/utils/project_store.py`(锁注册表 + 原子写 + pid 校验 + `mutate_project`)
- 全部 `{pid}` 路由的 pid 校验
- `active_tasks` 加锁
- `project.json` / `config.json` / `knowledge.json` 原子写入
- `translate.py`、`trailer_pipeline.py`、`projects.py` 的读改写调用点收敛到 `mutate_project`
- 每个修复配回归测试(TDD)

### 不包含(后续阶段)
- 审计问题 5-31(子进程返回码、滤镜转义、取消逻辑、信号量校验、输入校验、前端等)
- `Config.load()` 每次启动都重写配置文件的优化(审计低危项,非问题 1-4)
- `progress.json` —— `scheduler.update_progress` 已使用 `tmp + os.replace` 原子写,**不改动**

## 3. 新模块:`app/utils/project_store.py`

放在 `utils/` 而非 `api/projects.py`:`translate.py`、`trailer_pipeline.py`、`main.py` 都需要它,而它们当前反向从 `app.api.projects` 导入 `_load_project`/`_save_project`,耦合方向混乱。独立模块理顺依赖,且不依赖 FastAPI。

### 公开接口

```python
def validate_pid(pid: str) -> str
def project_dir(pid: str) -> Path
def load_project(pid: str) -> dict
def mutate_project(pid: str, fn: Callable[[dict], None], *, normalize: Callable[[dict], dict] | None = None) -> dict
def atomic_write_json(path: Path, data: dict) -> None
def get_project_lock(pid: str) -> threading.RLock
```

| 函数 | 职责 | 加锁 |
|---|---|---|
| `validate_pid` | 正则 `^[A-Za-z0-9_-]{1,64}$`;失败抛 `ValueError` | — |
| `project_dir` | 调 `validate_pid`,再用 `resolved.is_relative_to(PROJECTS_DIR.resolve())` 二次确认未逃逸 | — |
| `load_project` | 原始读 `project.json`;文件缺失抛 `FileNotFoundError` | 否 |
| `mutate_project` | per-pid RLock 内:`load → normalize(可选) → fn(data) → atomic_write_json`;返回最终 dict | **是** |
| `atomic_write_json` | 同目录写 `<name>.tmp` → `os.replace`;异常时 `finally` 清理残留 `.tmp` | — |
| `get_project_lock` | 锁注册表查/建(模式同 `scheduler.py` 的 `_sem_cache` + `_sem_cache_lock`,双重检查) | — |

### 关键设计取舍

- **`os.replace` 原子 → 纯读永不见写半文件**。因此独立读(`get_project`、`export_srt`、`download_video`)**不加锁**,保持全并发;只有"读-改-写"序列经 `mutate_project` 加锁,防丢失更新。
- **per-pid 锁**(非全局锁):跨项目并行不受影响,烧录项目 A 不阻塞读项目 B。
- **RLock**(非 Lock):防止 `mutate_project` 内的 `fn` 间接再次进入同 pid 临界区时自死锁。
- `_apply_safe_defaults` 仍留在 `projects.py`,经 `mutate_project(..., normalize=_apply_safe_defaults)` 注入,避免 `project_store` ← `projects.py` 循环导入。
- **锁注册表无上限增长**:桌面应用项目数为数十量级,可忽略(YAGNI,不做淘汰)。

## 4. 各问题的修复

### 问题 1 — pid 校验

- **HTTP 路由**:FastAPI 路径参数声明式约束 `pid: str = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")`,不匹配自动返回 422。零散落代码。覆盖 `projects.py` 与 `translate.py` 全部 `{pid}` 路由。
- **纵深防御**:`project_dir()` 内部 `validate_pid` + `is_relative_to`,覆盖 WebSocket 路由 `ws_progress`、`main.py:download_video`、以及一切内部调用。
- 现有 8 位十六进制 pid(`uuid.uuid4().hex[:8]`)均通过正则,无向后兼容问题。
- `delete_project` 的 `shutil.rmtree(project_dir(pid))` 因此天然受保护。

### 问题 2 — `active_tasks` 加锁

`translate.py` 中:
```python
_tasks_lock = threading.Lock()

def try_register_task(pid: str, factory: Callable[[], threading.Thread]) -> threading.Thread:
    with _tasks_lock:
        if pid in active_tasks:
            raise TaskAlreadyRunning(pid)   # API 层转 HTTPException(409)
        t = factory()
        active_tasks[pid] = t
    return t   # 调用方在锁外 t.start()

def unregister_task(pid: str) -> None:
    with _tasks_lock:
        active_tasks.pop(pid, None)
```
- 4 个端点(start-asr / start-translate / start-full / start-burn)的 `if pid in active_tasks` 检查 + 插入收敛到 `try_register_task`。
- 全部 worker 的 `finally: active_tasks.pop(pid, None)` 改为 `unregister_task(pid)`。
- 注册在锁内、`start()` 在锁外且在注册之后 —— 消除 check-then-act 与 worker `pop` 的竞争。

### 问题 3 — 原子写入

- `projects.py:_save_project` → 内部用 `atomic_write_json`(或直接被 `mutate_project` 取代)。
- `config.py:Config.save` → `atomic_write_json`。
- `knowledge.py:KnowledgeBase.save` → `atomic_write_json`。
- `atomic_write_json` 失败时原文件保持不变(核心保证),并清理残留 `.tmp`。

### 问题 4 — 读改写收敛到 `mutate_project`

- `translate.py` 15+ 处 `_load_project` / `_save_project` 配对(行 146/160/244/252/268/336/344/453/461/490 等)改为:
  ```python
  mutate_project(pid, lambda p: p.update({"status": "translating", ...}),
                 normalize=_apply_safe_defaults)
  ```
  或对复杂修改传命名函数。
- `trailer_pipeline.py:_save_partial`(行 83-87)改用 `mutate_project`。
- `projects.py:patch_project` 的 load→改→save 改用 `mutate_project`。
- 纯读路径(`get_project`、`export_srt`、`get_subtitles` 等)改用 `load_project`,不加锁。
- `projects.py` 保留 `_load_project`/`_save_project` 作为薄封装(向后兼容现有导入方),内部委托给 `project_store`。

## 5. 调用点清单(迁移目标)

| 文件 | 迁移内容 |
|---|---|
| `app/api/projects.py` | `_load_project`/`_save_project` 委托 `project_store`;`patch_project` 用 `mutate_project`;所有 `{pid}` 路由加 `Path(pattern=...)` |
| `app/api/translate.py` | 15+ load/save → `mutate_project`;`active_tasks` → `try_register_task`/`unregister_task`;路由加 pid 校验 |
| `app/engines/trailer_pipeline.py` | `_save_partial` → `mutate_project` |
| `app/config.py` | `Config.save` → `atomic_write_json` |
| `app/engines/knowledge.py` | `save` → `atomic_write_json` |
| `app/main.py` | `download_video`、`ws_progress` 经 `project_dir`/`load_project` 获得 pid 校验 |

## 6. 测试策略(TDD)

每个修复**先写能复现 bug 的失败测试,再写修复使其转绿**。

| 新增/扩展测试 | 验证 |
|---|---|
| `tests/test_project_store.py` | `validate_pid` 拒绝 `../`、绝对路径、超长、空串;`project_dir` 逃逸检测 |
| 同上 | `atomic_write_json`:成功后无残留 `.tmp`;monkeypatch `json.dump` 中途抛异常 → 原文件内容完好、`.tmp` 已清理 |
| 同上 | `mutate_project` 串行化:N 个线程各对计数器字段自增 M 次,最终值 == N×M(证明无丢失更新) |
| `tests/test_task_registration.py` | 用 `threading.Barrier` 强制两个 `try_register_task` 同 pid 并发 → 恰好一个成功、一个抛 `TaskAlreadyRunning` |
| `tests/test_project_patch.py`(扩展) | `get`/`delete`/`patch`/`export` 路由对非法 pid 返回 422 |
| 全量 `pytest tests/` | 现有 42 个测试无回归(重点 `test_scheduler_*`、`test_startup_progress_restore`、`test_projects_loader`、`test_create_trailer_project`) |

## 7. 错误处理

- `validate_pid` 抛 `ValueError`;HTTP 路由由 FastAPI `Path(pattern=...)` 拦截为 422;内部调用方按需 `try/except`。
- `load_project` 文件缺失抛 `FileNotFoundError`;`projects.py` 薄封装捕获并转 `HTTPException(404)`,保持现有行为。
- `atomic_write_json` 写失败:异常向上传播,**原文件不变**;`finally` 清理 `.tmp`。
- `mutate_project` 中 `fn` 抛异常:不写盘,异常向上传播,锁正常释放(`with` 块)。
- `TaskAlreadyRunning` 为新自定义异常;`translate.py` 端点捕获转 `HTTPException(409)`。

## 8. 向后兼容

- 现有 8 位十六进制 pid 全部通过新正则。
- `progress.json` 不改动。
- `projects.py` 保留 `_load_project`/`_save_project` 名称(薄封装),`trailer_pipeline.py` 等现有导入不破。

## 9. 验收标准

1. 非法 pid(`../`、绝对路径)在所有 `{pid}` 路由被拒,`delete_project` 无法删除 `PROJECTS_DIR` 外目录。
2. 对同一项目并发发起两次 `start-*`,恰有一次 409,只启动一条流水线。
3. 任意 JSON 写入被中途打断后,原文件仍可正常 `json.load`。
4. 并发 `mutate_project` 无丢失更新(计数器测试通过)。
5. 全量 `pytest tests/` 通过,新增测试全绿。
