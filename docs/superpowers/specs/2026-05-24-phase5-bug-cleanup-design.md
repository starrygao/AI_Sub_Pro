# Phase 5 — Bug fixes + 清理（2026-05-22 审计的高 ROI 子集）

**日期**：2026-05-24
**前序**：延续 Phase 1-4（project_store concurrency / subprocess robustness / pipeline correctness / input validation）
**范围**：审计列表里"已实现但有真实 bug 或半成品"的 6 项；不含 UX 新功能、不含基础设施改造。

## 动机

2026-05-22 的全项目审计在四类发现里产出最高 ROI 的就是"现有功能里露出来的真实问题"：

- 一个会让 UI 显示空白的索引错位 bug；
- 长期使用会吞硬盘的音频中间产物未清理；
- 三个永远 noop 但仍占据 KnowledgeBase 公共接口的 stub；
- 两处文档/schema 与实际行为不一致；
- 一处缺失的 defense-in-depth pid 校验。

这些项彼此独立、改动小、风险低，适合打包成一个 Phase 走完整 spec→plan→implement→review→merge 流程。

## 范围（明确列举，未列出的项不在本轮）

| 编号 | 问题 | 来源 |
|---|---|---|
| C-1 | 前端 `describeSubtitleTrack` 用全 subtitle 索引去取过滤后的数组 → 字幕标签 UI 显示空白 | 审计 C 节 #1 |
| C-2 | `_pick_subtitle_track` docstring 与返回值口径不一致 | 审计 C 节 #2 |
| C-3 | `_PROJECT_SAFE_DEFAULTS` 未包含 trailer pipeline 写入的 `asr_skipped` 字段 | 审计 C 节 #3 |
| C-4 | `raw_audio.wav` + `demucs_out/` 不清理，长期占盘 | 审计 C 节 #4 |
| C-5 | `app/api/translate.py::_load_project` 走裸 `PROJECTS_DIR / pid`，未走 `validate_pid` | 审计 C 节 #5 |
| B   | `KnowledgeBase.match` / `learn` / `feedback` 三个 stub 在生产 0 调用，应删除 | 审计 B 节 |

**明确不在本轮**：UX 新功能（重试 / 归档 / 重命名按钮、trailer 批量队列、subtitle 编辑器加行删行）、infra（TMDB key 外置、`build/dist` 取消 git 跟踪、KB 并发锁）。

## 设计

### C-1 前端索引错位修复

后端 `_pick_subtitle_track` 返回的是相对**所有 subtitle stream** 的 0-based 索引（与 ffmpeg `-map 0:s:N` 一致）。前端 `describeSubtitleTrack` 在 `app/static/js/app.js` 错误地先把 `subtitle_tracks` 过滤成 text-only，再用同一个索引去取——含图形字幕的视频会取到 undefined。

**修法**：前端不再过滤，直接 `project.subtitle_tracks[idx]`。后端契约不变，不增 API 字段。

### C-2 docstring 修正

把 `_pick_subtitle_track` 文档里"0-based among text-based subtitle streams"改为"0-based among ALL subtitle streams, suitable for ffmpeg `-map 0:s:N`"。

### C-3 schema 默认值补全

`_PROJECT_SAFE_DEFAULTS` 加 `"asr_skipped": False`。trailer pipeline 已经在 `_download_stage` 里写这个字段，但 `_apply_safe_defaults` 没有声明，导致 reload 旧 project 时该字段不存在；当前代码 `proj.get("asr_skipped")` 走默认 None 分支仍正确，但闭合 schema 防止以后误用。

### C-4 音频中间产物清理（核心改动）

**触发时机**：`_run_burn_pipeline` 成功（status=completed）后立即清理。烒录失败、ASR-only 流水线、用户取消——均不清理（保留供调试 / 重跑）。

**新增 helper**：`app/engines/audio.py::cleanup_intermediate(output_dir: str)` —— 静默删除 `raw_audio.wav` 和 `demucs_out/` 整个子树；任何 OSError 仅 log.warning，不抛。

**调用点**：
- `app/api/translate.py::_run_burn_pipeline` 在 `mutate_project(... status=completed ...)` 成功分支后调用
- `app/api/translate.py::start_burn._burn_task` 的成功分支同样调用（独立烒录路径）

### C-5 defense-in-depth pid 校验

`app/api/translate.py::_load_project` 改为调用 `app.utils.project_store.load_project`（已有 `validate_pid` + `project_dir` 路径围栏），保持与 `app/api/projects.py::_load_project` 一致。失败把 `FileNotFoundError` / `ValueError` 翻译为 HTTPException 404 / 400。

### B 删除 KB legacy stubs

`app/engines/knowledge.py` 里三个方法已确认零生产调用（grep 全仓只有 `tests/test_knowledge_base_v2.py::test_match_legacy_shim` 测试这个 shim 存在）：

```
KnowledgeBase.match(self, tags) -> Tuple[str, dict]    # 永远返回 ("通用", {...空字典...})
KnowledgeBase.learn(self, content, meta, provider=None) -> bool   # return False
KnowledgeBase.feedback(self, orig_path, final_path, category, provider=None) -> int   # return 0
```

**删除** 这三个方法，同步**删除** `tests/test_knowledge_base_v2.py::test_match_legacy_shim`。

## 数据流影响

只有 C-4 改变运行时副作用：每个项目完成后，磁盘减少 ~10-100MB（取决于音频时长 + 是否启用 demucs）。其他 5 项不改变行为，只改契约口径或代码组织。

## 错误处理

- **C-4 清理失败**：log.warning 后吞掉异常。绝不能因为清不掉中间文件而把"已完成"项目降级到"错误"——主要价值（带字幕的视频）已经在手。
- **C-5 pid 不合法**：复用 `ValueError` → HTTP 400 的现有翻译路径（projects.py 已是这个模式）。

## 测试策略

每项至少一个新测试（C-2 / C-3 / B 是契约级别，C-1 是前端但通过 Python 测试覆盖**后端契约的稳定性**作为兜底）：

| 编号 | 新增/修改测试 | 文件 |
|---|---|---|
| C-1 | 后端契约级 case（PGS+SRT 混合 → 返回值是相对全部 subtitle 的 0-based 索引）；前端纯展示，由人工冒烟 | `tests/test_subtitle_picker.py`（既有）加 1 个 case |
| C-2 | 无运行时测试（纯 docstring） | — |
| C-3 | `_apply_safe_defaults({})` 包含 `asr_skipped=False` | `tests/test_translate_loader_defaults.py` 加 1 个 case |
| C-4 | 3 个独立测试函数：（a）烒录成功后 `raw_audio.wav` + `demucs_out/` 消失；（b）烒录失败保留中间产物；（c）`cleanup_intermediate` 对不存在路径不抛 | 新建 `tests/test_audio_cleanup.py` |
| C-5 | 非法 pid 通过 `_load_project` 应该返回 HTTP 400，不应该让裸 open 暴露文件系统错误 | `tests/test_pipeline_correctness.py` 加 1 个 case |
| B   | 删 `test_match_legacy_shim`；其它 KB 测试不动 | `tests/test_knowledge_base_v2.py` |

**全套测试基线**：当前 216 通过。Phase 5 预期：删 1 + 加 6 → **221 通过**（C-1:1 + C-3:1 + C-4:3 + C-5:1）。

## 实施 / 合并节奏

- 单分支 `fix/phase5-audit-bug-cleanup`，6 项各自一个原子 commit
- 提交顺序：B → C-2 → C-3 → C-5 → C-1 → C-4（按风险升序，便于 bisect）
- `--no-ff` 合并到 main，保持与 Phase 1-4 一致的 merge commit 痕迹
- merge commit 描述写明 Phase 5 范围 + 测试基线变化（216 → 219）

## 不做的事（明确）

- 不动 build/dist git 跟踪
- 不动 TMDB embedded API key
- 不加 UI 新按钮（retry / archive / rename）
- 不改 trailer 批量提交并发模型
- 不引入 KB-level 并发锁
- 不重命名任何符号
