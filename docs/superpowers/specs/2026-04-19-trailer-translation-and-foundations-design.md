# AI_Sub_Pro — 预告片翻译 + 基础设施完善（Phase 1）

**Date**: 2026-04-19
**Scope**: Phase 1 of a 4-phase plan. This spec covers the new trailer-translation feature AND the foundational refactors/bugfixes that unblock it.

---

## 1. 目标

1. 新增**预告片翻译**端到端功能：用户输入 TMDB ID 或剧名（可带季号）→ 选择候选 → 自动下载 → ASR → 翻译 → 烧录中英双语硬字幕 MP4。
2. 新增 **Claude Code CLI 翻译通道**（通过 `claude-agent-sdk` Python 包，使用本机 Claude Code 订阅配额，无需 API key）—— 作为通用翻译 provider，所有翻译场景都能切到它。
3. 重构翻译引擎为可扩展的 **Provider 抽象**，利用 Claude 1M 上下文实现**全量一次性翻译模式**（大幅提升术语/风格一致性）。
4. 顺便修掉当前阻塞新功能的几个严重 bug 和脆弱性。

## 2. 范围

### 本次包含（Phase 1）
- 翻译引擎 Provider 抽象重构 + Claude CLI provider + 全量模式
- 预告片下载/翻译/烧录端到端功能（TMDB + yt-dlp + 双 SRT 烧录）
- Project 模型扩展 + 全局 semaphore + progress_store 加锁 + progress.json 持久化 + 协作式取消
- 前端：首页入口、预告片向导、Settings provider 条件渲染、TMDB key 输入
- 关键 bug 修复清单（§8）
- 关键日志补齐（§9）、关键安全加固（§10）

### 本次不包含（后续独立 spec）
- **Phase 2 —— 知识库重设计**：当前 `KnowledgeBase.match([])` 永远传空列表，整个知识库是死代码。重设计需独立 spec（per-project 分类 + 实际注入翻译 prompt + `learn()` 实装）。
- **Phase 3 —— UI 深度打磨**：inline CSS → `app.css` 抽出、骨架 loading、焦点环、字幕表格搜索/批量编辑、可折叠 settings。部分轻量项顺带做（见 §7），重构留到 Phase 3。
- **Phase 4 —— 工程基础加固**：完整替换 `except: pass`、依赖锁文件、日志轮转、测试骨架、（可选）config 加密。

---

## 3. 架构总览

```
首页 ──┬── [既有] 上传视频 ─────────────────────────┐
      └── [新] 预告翻译卡片 → 向导                 │
                              ↓                    ↓
                  TMDB search → 候选 → yt-dlp 下载
                              ↓
                       create_trailer_project
                              ↓
                 ┌────── Project (既有 + 扩展字段) ──────┐
                 │                                       │
                 │  Scheduler（semaphore + lock + cancel）
                 │                                       │
                 │   ┌── ASR (既有，修语言 bug + VAD)
                 │   │
                 │   ├── Translator（重构：providers/* + full-doc）
                 │   │     ├── OpenAICompatProvider
                 │   │     └── ClaudeCliProvider (Agent SDK)
                 │   │
                 │   └── Burn（扩展：双 SRT 双语）
                 └────────────────────────────────────────┘
```

**三处核心改动都是加法**：
- `app/engines/providers/` 新目录（翻译 provider 抽象）
- `app/engines/tmdb.py` + `app/engines/trailer_downloader.py` + `app/engines/trailer_pipeline.py` + `app/api/trailer.py`（预告片模块）
- 其他子系统做最小必要扩展（字段增补、加锁、加 semaphore、烧录支持多 SRT track）

---

## 4. 配置与数据模型扩展

### 4.1 `DEFAULT_CONFIG` 新增（`app/config.py`）

```python
DEFAULT_CONFIG = {
    "api_keys": { "openai": "", "deepseek": "", "gemini": "" },  # 既有
    "tmdb": {
        "api_key": "",
        "language": "zh-CN",      # 查询元数据时用的语言
    },
    "translation": {
        # 既有字段保留...
        "primary_provider": "openai",       # 新增合法值: "claude_cli"
        "primary_model": "gpt-4o",
        "full_doc_mode": False,             # 新增：true 时 batch_size 忽略，整文件一次性翻译（仅 Claude）
        "batch_size": 10,
        # ...
    },
    "providers": {
        "claude_cli": {
            "enabled": True,                # 功能开关（rollback 用）
            "model": "claude-opus-4-7",     # claude-opus-4-7 / claude-sonnet-4-6 / claude-haiku-4-5
            "timeout_sec": 180,
        }
    },
    "concurrency": {                         # 新增：并发上限
        "asr": 2,
        "translate": 4,
        "download": 3,
        "burn": 1,
    },
    "general": { "max_workers": 4, "theme": "dark" },  # 既有
}
```

**向后兼容**：`_deep_merge(DEFAULT_CONFIG, saved)` 在 config.py 已经正确处理缺失键 —— 用户首次升级时，新字段自动填入默认值，旧字段保留。前端读取 settings 时对未知字段使用可选链访问（`settings.providers?.claude_cli?.model`）。

### 4.2 `project.json` 新增字段（`app/api/projects.py`）

```python
{
  # 既有字段保留
  "id": "abc1def2",
  "name": "...",
  "video_path": "...",
  "status": "created|processing|asr_done|translated|completed|error",
  "progress": 0,
  "asr_language": "auto",
  # ...

  # 新增字段（legacy 项目加载时默认填入）
  "source_type": "upload" | "trailer",   # 缺省 = "upload"
  "tmdb_id": None,
  "tmdb_type": None,                      # "tv" | "movie"
  "season_number": None,
  "tmdb_video_key": None,                 # YouTube video id
  "youtube_url": None,
  "original_language": None,              # ISO 639-1，从 TMDB `original_language` 取
  "auto_run": False,                      # true → 创建后自动跑完整流水线
  "parent_project_id": None,              # 同一剧多预告的分组（可为 null）
  "pipeline_stage": None,                 # "download" | "asr" | "translate" | "burn" | None
  "archived": False,                      # 预留给 retention
}
```

**Project 加载安全默认**（`api/projects.py` 的 `_load_project`）：
```python
project.setdefault("source_type", "upload")
project.setdefault("auto_run", False)
project.setdefault("original_language", None)
# ... 其余新字段默认 None/False
```

---

## 5. 翻译引擎重构

### 5.1 目录结构（新）

```
app/engines/
├── providers/
│   ├── __init__.py        # 注册内置 providers
│   ├── base.py            # BaseProvider 抽象类
│   ├── factory.py         # get_provider() 工厂
│   ├── openai_compat.py   # OpenAI/DeepSeek/Gemini 合并为一个类
│   └── claude_cli.py      # Claude Agent SDK 实现
├── translator.py          # 既有文件，改为调用 factory；保留 TranslationProvider 别名
└── ...
```

### 5.2 `BaseProvider` 契约（`providers/base.py`）

```python
from abc import ABC, abstractmethod

class BaseProvider(ABC):
    @abstractmethod
    def translate_batch(
        self, items: list[dict], system_prompt: str, retries: int = 3
    ) -> list[dict]:
        """
        items: [{"id": int, "original": str}, ...]
        返回: [{"id": int, "translation": str, "error": str}, ...]
              —— 失败时 translation="" + error="原因"，不再静默丢块
        """

    @abstractmethod
    def test_connection(self) -> bool: ...

    @property
    @abstractmethod
    def supports_full_document_mode(self) -> bool: ...

    @property
    @abstractmethod
    def context_window_tokens(self) -> int:
        """approximate, 用于智能 fallback 到 batch"""
```

### 5.3 Provider factory（`providers/factory.py`）

```python
_REGISTRY: dict[str, type[BaseProvider]] = {}

def register(name: str, cls: type[BaseProvider]): _REGISTRY[name] = cls

def get_provider(name: str, config: dict) -> BaseProvider:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown provider: {name}")
    return _REGISTRY[name](config)

def list_providers() -> list[str]: return sorted(_REGISTRY.keys())
```

内置注册：`register("openai", OpenAICompatProvider)`（同样 deepseek/gemini 共用），`register("claude_cli", ClaudeCliProvider)`。

### 5.4 `OpenAICompatProvider`（`providers/openai_compat.py`）

把现有 `engines/translator.py` 的 `TranslationProvider` 类搬过来，按 `BaseProvider` 签名改造：
- `translate_batch` 失败时返回错误携带 dict（不再返 `[]`）
- `supports_full_document_mode = True`
- `context_window_tokens` 根据 model 字符串估计（gpt-4 系列 128k，deepseek 64k，gemini 1M）

**向后兼容**：在 `engines/translator.py` 末尾加一行 `TranslationProvider = OpenAICompatProvider`，这样外部引用旧名字的代码不破。

### 5.5 `ClaudeCliProvider`（`providers/claude_cli.py`）

```python
import asyncio, subprocess, json, re, logging
from claude_agent_sdk import query, ClaudeAgentOptions
from .base import BaseProvider

log = logging.getLogger(__name__)

class ClaudeCliProvider(BaseProvider):
    def __init__(self, config: dict):
        self.model = config.get("model", "claude-opus-4-7")
        self.timeout = config.get("timeout_sec", 180)

    @staticmethod
    def check_cli_available() -> bool:
        try:
            r = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def check_logged_in() -> bool:
        """查 claude auth status（命令随 CLI 版本而定；若失败回退到 --version 存在性）"""
        try:
            r = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=5)
            return r.returncode == 0 and ("logged in" in (r.stdout + r.stderr).lower()
                                          or "authenticated" in (r.stdout + r.stderr).lower())
        except Exception:
            return False

    def test_connection(self) -> bool:
        return self.check_cli_available() and self.check_logged_in()

    @property
    def supports_full_document_mode(self) -> bool: return True

    @property
    def context_window_tokens(self) -> int: return 1_000_000

    def translate_batch(self, items, system_prompt, retries=3):
        if not self.check_cli_available():
            return [self._err_item(i, "Claude Code CLI 未安装或不在 PATH") for i in items]
        if not self.check_logged_in():
            return [self._err_item(i, "Claude Code 未登录：请运行 `claude` 完成登录") for i in items]

        for attempt in range(retries):
            try:
                return asyncio.run(self._translate_async(items, system_prompt))
            except Exception as e:
                log.warning("Claude CLI attempt %d failed: %s", attempt + 1, e)
                if attempt == retries - 1:
                    return [self._err_item(i, f"Claude CLI 调用失败: {str(e)[:100]}") for i in items]

    async def _translate_async(self, items, system_prompt):
        user_content = json.dumps(items, ensure_ascii=False)
        opts = ClaudeAgentOptions(model=self.model, system_prompt=system_prompt)
        chunks = []
        async for msg in query(prompt=user_content, options=opts):
            if hasattr(msg, "content"): chunks.append(msg.content)
            elif hasattr(msg, "text"): chunks.append(msg.text)
        text = "".join(chunks)
        return self._parse(text, items)

    def _parse(self, text: str, items: list) -> list:
        text = re.sub(r"```(?:json)?", "", text, flags=re.I).strip()
        try:
            parsed = json.loads(re.sub(r",\s*([\]}])", r"\1", text))
        except Exception:
            m = re.search(r"\[.*\]", text, re.DOTALL)
            parsed = json.loads(m.group()) if m else []

        by_id = {str(r.get("id")): r for r in parsed if isinstance(r, dict)}
        out = []
        for it in items:
            r = by_id.get(str(it["id"]))
            if r and r.get("translation"):
                out.append({"id": it["id"], "translation": r["translation"], "error": ""})
            else:
                out.append(self._err_item(it, "response missing or empty"))
        return out

    @staticmethod
    def _err_item(it, msg): return {"id": it["id"], "translation": "", "error": msg}
```

**Async 桥接决策**：Agent SDK 仅提供异步 `query()`。translator 是 sync 的，所以在 `translate_batch` 里用 `asyncio.run()` 为每次批量翻译起一个临时事件循环。**不把整个 translator 改成 async**（后续重写代价太大，Phase 3/4 再考虑），现在的方案仅限于 provider 内部。

### 5.6 全量翻译模式（`engines/translator.py`）

```python
def translate(self, blocks, target_lang, ...):
    batch_size = self.config["translation"].get("batch_size", 10)
    full_doc = self.config["translation"].get("full_doc_mode", False)
    if (batch_size == 0 or full_doc) and self.primary.supports_full_document_mode:
        return self._translate_full_document(blocks, target_lang, ...)
    return self._translate_batched(blocks, target_lang, ...)

def _translate_full_document(self, blocks, target_lang, ...):
    active = [b for b in blocks if not b.filtered and b.text.strip()]
    items = [{"id": b.index, "original": b.text} for b in active]
    system_prompt = self._build_prompt(target_lang, ...)

    # Token 粗估，超出 context_window 的 80% 就回退到 batched
    est_tokens = sum(len(it["original"]) for it in items) // 2
    if est_tokens > self.primary.context_window_tokens * 0.8:
        log.warning("Full-doc 估 %d tokens，超出 80%% 阈值，回退到 batched", est_tokens)
        return self._translate_batched(blocks, target_lang, ...)

    results = self.primary.translate_batch(items, system_prompt)
    self._apply_results(blocks, results)
    return blocks
```

### 5.7 错误透明化

- `translate_batch` 永远返回与 `items` 等长的列表，失败时用 `error` 字段填原因
- 上游 `_translate_batched` / `_translate_full_document` 统计成功/失败块，通过 `progress_callback` 上报 `{"progress": pct, "errors": [...]}` 给 WebSocket
- UI 在项目详情页显示"X 条翻译失败，点击重试"

### 5.8 Bug 修复（本节内）

- `translator.py` 原 line 199 `ctx_end = min(total, batch_end + 2)` → `ctx_end = min(total, batch_end + self.context_window)`

---

## 6. 预告片模块

### 6.1 `engines/tmdb.py`（新）

```python
async def search_multi(query: str, language: str = "zh-CN") -> list[dict]
async def search_tv(query: str, year: int | None = None) -> list[dict]
async def search_movie(query: str, year: int | None = None) -> list[dict]
async def get_tv_videos(tmdb_id: int, season: int | None = None) -> list[dict]
async def get_movie_videos(tmdb_id: int) -> list[dict]
async def get_show_details(tmdb_id: int, media_type: str) -> dict  # 含 original_language
```

- HTTP 层：`httpx.AsyncClient`（项目整体向 async 方向迁移；trailer 模块作为试点）
- Key 从 `Config.get("tmdb", "api_key")`；无 key 时返回 401 错误上抛，UI 跳 Settings
- 候选排序：`type=Trailer && official=true` 优先，其次 `Teaser`，按 `published_at` 降序
- 429 限流：简单重试一次（2s 延迟），再失败返错误 —— 不做复杂队列

### 6.2 `engines/trailer_downloader.py`（新）

```python
import yt_dlp

async def download_trailer(
    youtube_url: str,
    output_path: str,
    progress_callback: Callable[[float, str], None] | None = None
) -> str:
    """返回下载好的 mp4 本地路径"""
```

yt-dlp 选项：
- `format = "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best"`
- `outtmpl = output_path`（`<project_dir>/original.mp4`）
- `progress_hooks = [_hook]` —— 在 hook 里把 `downloaded_bytes / total_bytes` 映射成本阶段进度 `pct`，调 `progress_callback(pct, msg)`
- 超时 60s，失败重试 1 次
- **URL 白名单校验**：必须是 `www.youtube.com`、`youtube.com`、`youtu.be` 之一，否则拒绝（防 TMDB 返回异常 key 被滥用）

### 6.3 `engines/trailer_pipeline.py`（新）

编排器负责：
1. 接受 `{tmdb_id, tmdb_type, season, video_keys, original_language}`
2. 对每个 `video_key`：
   - 创建 trailer project（`create_trailer_project()` in `api/projects.py`）
   - 起后台 thread 串行跑：download → ASR → translate → burn
   - 每阶段前申请对应 semaphore，完成后释放
   - 异常时 `status="error"` + `error="阶段 X 失败: 原因"`，**不会卡在某个阶段无限不动**
3. 多个 video_keys 串行处理，避免 semaphore 队列风暴

ASR 阶段调用时 `language=original_language`（覆盖 auto 默认，修掉"永远当日语"的 bug）。

### 6.4 `api/trailer.py`（新）

```python
@router.post("/api/trailer/search")
async def search(query: str, media_type: str | None = None) -> list[dict]

@router.get("/api/trailer/videos/{tmdb_id}")
async def videos(tmdb_id: int, type: str = "tv", season: int | None = None) -> list[dict]

@router.post("/api/trailer/start")
async def start(body: TrailerStartReq) -> {"pids": [...], "status": "submitted"}

# body:
class TrailerStartReq(BaseModel):
    tmdb_id: int
    tmdb_type: Literal["tv", "movie"]
    season: int | None = None
    video_keys: list[str]
    original_language: str
```

### 6.5 边界情况

| 情况 | 行为 |
|------|------|
| TMDB 未配置 key | API 返 400 `{"error": "TMDB_KEY_MISSING"}`，UI 跳 Settings |
| TMDB 无结果 | 返 `[]`，UI 显示"未找到" |
| YouTube 视频被删/区域封锁 | yt-dlp 异常 → project `status="error"`，其他 video_keys 继续 |
| 全音乐预告（无对白）| ASR 返空 → 生成空 SRT → 烧录跳过 zh/en 两个 track → 输出无字幕 mp4 |
| Vimeo/其他站点 | yt-dlp 也支持，照常跑；不支持站点捕获异常后 error |

---

## 7. 并发控制 + 进度持久化 + 取消

### 7.1 全局 semaphore（新建 `engines/scheduler.py`）

```python
import threading
from app.config import Config

_cfg = Config.get("concurrency", default={}) or {}
SEM_ASR       = threading.BoundedSemaphore(_cfg.get("asr", 2))
SEM_TRANSLATE = threading.BoundedSemaphore(_cfg.get("translate", 4))
SEM_DOWNLOAD  = threading.BoundedSemaphore(_cfg.get("download", 3))
SEM_BURN      = threading.BoundedSemaphore(_cfg.get("burn", 1))

@contextmanager
def slot(sem, pid, stage):
    log.info("semaphore[%s] acquiring for pid=%s", stage, pid)
    sem.acquire()
    try:
        yield
    finally:
        sem.release()
```

调用方：
```python
with slot(SEM_ASR, pid, "asr"):
    run_asr(...)
```

**说明**：不同阶段互不争用（ASR semaphore 和 download semaphore 独立）；同一阶段最多 N 个任务并发。预告片批量下载不会挤占 ASR 队列 —— 它们用的是不同的 semaphore。

### 7.2 progress_store 加锁 + 持久化

`api/translate.py` 改造：

```python
_progress_lock = threading.Lock()
progress_store: dict[str, dict] = {}

def update_progress(pid: str, stage: str, local_pct: int, msg: str):
    global_pct = _map_global(stage, local_pct)  # 见 §7.4
    with _progress_lock:
        progress_store[pid] = {
            "progress": global_pct,
            "stage": stage,
            "message": msg,
            "updated_at": datetime.utcnow().isoformat(),
        }
        _persist(pid, progress_store[pid])

def _persist(pid: str, payload: dict):
    try:
        d = PROJECTS_DIR / pid
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "progress.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        log.warning("persist progress failed pid=%s: %s", pid, e)
```

**WebSocket 读**：在持锁内读 `progress_store[pid]`，释放后推送。**启动时**：扫描 `data/projects/*/progress.json` 恢复到内存，让 crash 后前端能立刻看到最后状态。

### 7.3 协作式取消

```python
cancel_events: dict[str, threading.Event] = {}

def request_cancel(pid):
    ev = cancel_events.get(pid)
    if ev: ev.set()
```

- ASR：每处理一个音频 segment 后检查 `ev.is_set()` → `raise CancelledError`
- Translate：每个 batch 开始前检查
- Burn：ffmpeg 子进程每次读到 `frame=` 输出行后检查，`ev.is_set()` 时 `proc.terminate()`

status 切到 `cancelled`。

### 7.4 多阶段全局进度映射

| Stage | 全局范围 |
|------|---------|
| download | 0–15% |
| asr      | 15–40% |
| translate| 40–75% |
| burn     | 75–100% |

```python
_STAGE_RANGES = {"download": (0, 15), "asr": (15, 40), "translate": (40, 75), "burn": (75, 100)}
def _map_global(stage, local_pct):
    lo, hi = _STAGE_RANGES.get(stage, (0, 100))
    return lo + int((hi - lo) * (local_pct / 100))
```

非 trailer 项目（upload 源）不走 download 阶段，起始就在 asr，映射仍然用上表（显示进度从 15% 起）。

---

## 8. 双语硬字幕烧录

### 8.1 `SubtitleTrack` dataclass（`app/utils/media.py`）

```python
from dataclasses import dataclass

@dataclass
class SubtitleTrack:
    path: str
    font_name: str = "Helvetica"
    font_size: int = 20
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    outline_width: float = 1.5
    margin_v: int = 30
    alignment: int = 2  # bottom-center
```

### 8.2 `burn_subtitles()` 扩展签名

```python
def burn_subtitles(
    video_path: str,
    tracks: list[SubtitleTrack] | str,   # 字符串 = 旧签名（单 SRT 路径）
    output_path: str,
    callback=None
) -> bool:
    if isinstance(tracks, str):         # 向后兼容
        tracks = [SubtitleTrack(path=tracks)]
    ...
```

### 8.3 zh.srt / en.srt 生成

在 `api/translate.py` 翻译完成后追加一步：

```python
def _write_bilingual_srts(pdir: Path, blocks: list[SubtitleBlock]):
    zh = [b for b in blocks if not b.filtered and (b.translation or "").strip()]
    en = [b for b in blocks if not b.filtered]
    write_srt(zh, pdir / "zh.srt", use_translation=True)
    write_srt(en, pdir / "en.srt", use_translation=False)
```

只对 `source_type="trailer"` 的项目生成；或当 `config.translation.bilingual_burn=True` 时对所有项目生成（Phase 1 只给 trailer 启用）。

### 8.4 ffmpeg filter 模板

```python
def build_filter_chain(tracks: list[SubtitleTrack]) -> str:
    parts = []
    for t in tracks:
        style = (
            f"FontName={t.font_name},FontSize={t.font_size},"
            f"PrimaryColour={t.primary_color},OutlineColour={t.outline_color},"
            f"Outline={t.outline_width},Shadow=0,"
            f"Alignment={t.alignment},MarginV={t.margin_v}"
        )
        parts.append(f"subtitles='{_escape(t.path)}':force_style='{style}'")
    return ",".join(parts)

def _escape(path: str) -> str:
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
```

完整 ffmpeg 命令：
```
ffmpeg -i input.mp4 -vf "<filter_chain>" -c:v libx264 -preset medium -crf 20 -c:a copy output.mp4
```
（若音频非 aac 则 `-c:a aac -b:a 192k`）

### 8.5 动态字号 + 字体 fallback

```python
import platform

def compute_font_sizes(video_height: int) -> tuple[int, int]:
    zh = max(18, int(video_height * 0.055))
    en = int(zh * 0.7)
    return zh, en

def resolve_font(lang: str) -> str:
    sys = platform.system()
    if lang == "zh":
        return {"Darwin": "PingFang SC", "Windows": "Microsoft YaHei"}.get(sys, "DejaVu Sans")
    return {"Windows": "Arial"}.get(sys, "Helvetica")
```

预告片双语 track 构造：
```python
zh_size, en_size = compute_font_sizes(video_height)
tracks = [
    SubtitleTrack(path=zh_srt, font_name=resolve_font("zh"), font_size=zh_size,
                  outline_width=2.0, margin_v=70),
    SubtitleTrack(path=en_srt, font_name=resolve_font("en"), font_size=en_size,
                  outline_width=1.5, margin_v=30),
]
```

### 8.6 进度解析

ffmpeg stderr 按行读，正则 `r"time=(\d+):(\d+):(\d+\.\d+)"` → 秒数 → `local_pct = min(100, int(elapsed / duration * 100))` → `update_progress(pid, "burn", local_pct, ...)`。

---

## 9. 前端 UI

### 9.0 UI 风格重设计（2026-04-19 追加）

用户反馈现有 glass morphism 风格"比较丑"，允许切换其他风格。实施时先做 **UI 风格方案探索**：

- 派 UI 设计 agent 输出 **2–3 个候选风格**的静态 HTML mockup（单文件展示首页 + 项目列表 + Settings + 预告向导 Step 4）
- 候选方向建议（由 agent 细化，具体可调）：
  - **A. Linear/Raycast 风格** —— 深色优先、neutral 调色、密排、字体偏小、键盘导航优先、专业感强（字幕工具匹配度高）
  - **B. Notion/Obsidian 风格** —— 浅色优先、温暖、更多留白、圆角中等、阅读舒适
  - **C. 保留 glass morphism 但强化** —— 优化信息层级、减少视觉噪音（最小变更）
- 用户在 mockup 间选一个，然后按选定风格重写 `<style>` 块
- 同时完成 inline CSS/JS → `static/css/app.css` + `static/js/app.js` 抽出（Phase 3 原计划的清理顺便做了，因为反正要重写）

这一步放到 §14 实施顺序的 Step 10.5（在前端 view 开发之前）。

### 9.1 Alpine 状态新增（`app()` data）

```js
view: 'home' | 'projects' | 'settings' | 'knowledge' | 'trailer',

// 预告片向导
trailerStep: 1,                // 1..5
trailerSearchMode: 'title',    // 'title' | 'tmdb_id'
trailerSearchQuery: '',
trailerSearchResults: [],
trailerSelectedShow: null,
trailerSeasons: [],
trailerSelectedSeasons: [],
trailerVideos: [],
trailerSelectedVideos: [],
trailerError: null,

// Settings 新增
showKeys: { primary: false, polish: false, tmdb: false },
claudeCliStatus: null,  // 'ok' | 'not_installed' | 'not_logged_in'
```

### 9.2 首页入口卡片

在既有拖拽区下方加 2 列栅格：

- **完整翻译**（既有功能入口 icon 📹，copy "上传本地视频，自动识别+翻译+烧录字幕"）
- **预告翻译**（新，icon 🎬，copy "输入剧名或 TMDB ID，自动下载并翻译预告片"）→ `@click="view='trailer'; trailerStep=1"`

### 9.3 预告片向导（5 步）

- **Step 1 — 搜索输入**：radio `按名称 / 按 TMDB ID` + 文本框 + "搜索"按钮
- **Step 2 — 候选剧集**：poster 154px + 中文名 + 原名 + 年份 + overview excerpt，点击选中进 Step 3
- **Step 3 — 选季**（仅 TV）：季号 chips 多选 + "整部剧"按钮。电影跳过此步直接到 4。
- **Step 4 — 预告候选**：YouTube thumbnail + 名称 + type badge（Trailer/Teaser）+ 发布日期 + 官方 ✓ + checkbox 多选。底部"开始翻译（N 个预告）"按钮 → POST `/api/trailer/start`
- **Step 5 — 跳回项目列表**：刚创建的项目在顶部，带 "下载中/识别中/翻译中/烧录中" badge

每步顶部：返回按钮 + 进度条 + 关闭按钮（回首页）。每步底部：错误状态面板（TMDB key 缺失时带"去设置"链接）。

### 9.4 Settings 条件渲染

**主翻译服务 select** 加 `claude_cli` 选项。条件块：

- `primary_provider !== 'claude_cli'` → 显示 API key 输入（既有）
- `primary_provider === 'claude_cli'` → 隐藏 API key；显示：
  - 模型 dropdown（`claude-opus-4-7` / `claude-sonnet-4-6` / `claude-haiku-4-5`）
  - 琥珀色警告面板：**"⚠️ 需要本机已安装并登录 Claude Code：运行 `claude` 命令完成登录即可。未登录时翻译会失败。"**
  - "检查登录状态"按钮 → `GET /api/settings/claude-cli/status` → 返 `{"installed": bool, "logged_in": bool}` → 面板变色反馈

**TMDB 新节**：API key 输入 + 眼睛图标显隐 + "测试"按钮 + 链接到 `themoviedb.org/settings/api`

**全量翻译 toggle**（仅 `claude_cli` 时显示）：`一次性全量翻译（利用 Claude 长上下文）`

### 9.5 项目卡片 stage badge

加字段 `pipeline_stage` 的徽章：下载中（橙）/ 识别中（紫）/ 翻译中（蓝）/ 烧录中（绿）/ 已完成（success）/ 失败（red）。

### 9.6 CSS/JS 抽出（轻量，本次只做预告片相关新增那部分）

- 既有 inline 样式保留，**不做 Phase 3 级别的大重构**
- 新增的预告片向导样式直接用现有 `glass` 类
- 新增 alpine methods（`searchTrailers`、`fetchTrailerVideos`、`startTrailerTranslation`、`checkClaudeCliStatus`）加进既有 `app()` data 对象

---

## 10. Bug 修复清单

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| B1 | `api/translate.py:122` | `detected_lang = ... if lang != "auto" else "ja"` 永远假设日语 | 改为：auto 时从 project.original_language（trailer 有）或 `detect_language_hint(blocks)` 推导；都没有才回退 ja |
| B2 | `engines/translator.py:199` | context window hardcoded `+2` | `+self.context_window` |
| B3 | `engines/translator.py` `translate_batch` | 失败返 `[]` 静默丢块 | 返与 items 等长的错误携带 dict |
| B4 | `engines/asr.py` | `vad_filter` 配置不生效 | 传给 openai-whisper；mlx_whisper 若 API 不支持则在日志里注明 |
| B5 | `engines/asr.py` mlx 分支 | `beam_size` 被忽略 | 如 mlx_whisper 支持则传入；否则文档说明 |
| B6 | `api/translate.py` | `progress_store` 无锁 | §7.2 加 `_progress_lock` + 持久化 |
| B7 | `api/translate.py` | 无并发上限 | §7.1 Semaphore |
| B8 | 多处 | `except Exception: pass` | 最少替换**本次改动路径**上的（translator、api/translate、api/trailer、scheduler、trailer_pipeline），改为 `log.exception(...)`。非改动路径留给 Phase 4 统一扫。 |

---

## 11. 观测性（新增关键日志）

| Level | 场景 |
|-------|------|
| INFO  | `trailer download start pid=X key=Y url=Z` |
| INFO  | `ASR start pid=X lang=Y use_demucs=Z` |
| INFO  | `translate start pid=X provider=Y model=Z full_doc=bool blocks=N` |
| INFO  | `burn start pid=X tracks=[zh,en] fonts=[...]` |
| WARN  | `TMDB 429; retry in 2s` |
| WARN  | `Claude CLI not logged in; translation will fail` |
| WARN  | `semaphore[asr] queue depth=N`（采样） |
| ERROR | `stage=X failed pid=Y: <exception with traceback>` |
| ERROR | `Claude CLI JSON parse failed: <last 200 chars>` |

---

## 12. 安全

- **yt-dlp URL 白名单**：必须在 {`youtube.com`, `www.youtube.com`, `youtu.be`}，否则 `raise ValueError`
- **TMDB query 转义**：`urllib.parse.quote(user_input)`（httpx 的 params= 参数会自动做，保险起见再显式一遍）
- **TMDB key**：存明文（和既有 api_keys 一致），Phase 4 考虑加密
- **日志脱敏**：永远不打印 TMDB key / API key，只打印 `***<last4>`

---

## 13. 测试策略

### 13.1 单元测试（新建 `tests/` 目录）

- `test_providers.py`
  - `OpenAICompatProvider` 成功/失败路径（mock openai client）
  - `ClaudeCliProvider` CLI 不存在 → 错误 item；未登录 → 错误 item；mock Agent SDK 的 async query → 成功解析
  - Factory 注册/查找
- `test_translator_full_doc.py`
  - full_doc 模式 batch 次数 = 1；token 估算超限自动回退到 batched
- `test_tmdb.py`（mock httpx）
  - search/videos 解析正确；官方预告排在前
- `test_trailer_downloader.py`（mock yt-dlp）
  - URL 白名单拒绝非 YouTube；正确格式选择
- `test_burn.py`
  - `_escape` 路径转义（空格、冒号、单引号）
  - `compute_font_sizes`（多个 video_height）
  - filter chain 字符串生成无引号污染
- `test_scheduler.py`
  - 5 个任务 + asr_semaphore=2 → 验证最多 2 并发
  - `cancel_events` 设置后任务 raise CancelledError

### 13.2 E2E 场景（手动或半自动）

1. **Legacy upload 回归**：升级后打开老项目，能打开/编辑/重翻译，输出 mp4 正确
2. **Trailer 名称搜索 → 翻译全流程**：搜"权力的游戏" → 选一季 → 勾 2 个 trailer → 等 10 分钟 → 两个 mp4 都正常双语
3. **Trailer TMDB ID 直搜**：输入一个已知的电影 tmdb_id → 候选 → 选一个 → 完成
4. **Config 首启**：删 `config.json` → 重启 → Settings 页所有字段有默认值
5. **并发压力**：同时起 5 个上传 + 2 个 trailer → 都完成；观察 semaphore 日志
6. **Claude CLI 未登录**：在设置里切到 claude_cli → 起翻译 → UI 看到明确错误"未登录"
7. **全音乐预告**：选一个纯音乐预告 → 完成（SRT 空，mp4 无字幕但不崩）

---

## 14. 实施顺序（严格依赖）

```
Step 1. 配置与数据模型（§4）       ← 所有后续的基础
Step 2. Bug 修复 B1/B2/B3（§10）   ← 翻译重构前先修干净
Step 3. Scheduler + 进度持久化（§7）
Step 4. 翻译引擎 Provider 抽象（§5.1–5.5）
Step 5. 翻译全量模式 + OpenAICompat 收敛（§5.6–5.8）
Step 6. Claude CLI provider 单测通过（§5.5）
Step 7. 双语烧录（§8）              ← 独立，可与 4–6 并行
Step 8. TMDB + yt-dlp 模块（§6.1–6.2）
Step 9. trailer_pipeline 编排器（§6.3–6.5）
Step 10. trailer API + Settings 新接口（§6.4 + §9.4）
Step 10.5. UI 风格方案探索（§9.0）—— 2–3 个 mockup，用户选定后再进 Step 11
Step 11. 前端重写：按选定风格写 CSS + 抽出到 app.css/app.js + 首页卡片 + 预告向导（§9.1–9.3）
Step 12. 前端 Settings 条件渲染 + stage badge（§9.4–9.5）
Step 13. E2E 回归 + 场景 1/2/5/6（§13.2）
```

**每个 Step 完成后**按偏好的工作流，派 2–3 个独立 audit agent 对该 Step 的改动做只读审查，通过后再进入下一 Step。

---

## 15. 风险与回滚

| 风险 | 可能性 | 影响 | 缓解/回滚 |
|-----|--------|------|----------|
| Agent SDK 接口与设想不符（query 返回结构、系统 prompt 支持方式） | 中 | 高 | 实施 Step 6 时先写一个最小探测脚本验证 API；如不匹配，fallback 到 subprocess `claude -p --output-format stream-json` 方案 |
| Claude CLI 订阅 5 小时窗口额度耗尽 | 低 | 中 | UI 清晰错误；用户切回其他 provider 即可；全量模式相比 batch 其实省配额（一次调用） |
| yt-dlp 升级破坏 format 选择 | 低 | 中 | 钉版本；失败时降级到 `best[ext=mp4]` |
| 双 SRT 字体未解析（libass 默认兜底） | 中 | 低 | §8.5 的 fallback 表 + 启动时 `ffprobe` 预检 |
| Semaphore 死锁 | 低 | 高 | 只用 contextmanager + BoundedSemaphore（自动释放）+ 不嵌套跨阶段 |
| 老项目迁移问题 | 低 | 高 | §4.2 `setdefault` 全字段；单独 E2E 场景 1 验证 |
| Electron 打包时 `claude-agent-sdk` 依赖问题 | 中 | 中 | requirements.txt 钉版本；PyInstaller spec 显式 hidden-import；CI 可先跑本地 python app/main.py 验证 |

**功能级 rollback**：
- Claude CLI 坏 → `config.providers.claude_cli.enabled = false` → UI 不显示该选项
- Trailer 模块坏 → `main.py` 不 include trailer_router → 功能消失但不影响其余
- 双语烧录坏 → `burn_subtitles` 收到单 track 走老路径

---

## 16. 产物清单

**新文件**：
- `app/engines/providers/__init__.py`
- `app/engines/providers/base.py`
- `app/engines/providers/factory.py`
- `app/engines/providers/openai_compat.py`
- `app/engines/providers/claude_cli.py`
- `app/engines/tmdb.py`
- `app/engines/trailer_downloader.py`
- `app/engines/trailer_pipeline.py`
- `app/engines/scheduler.py`
- `app/api/trailer.py`
- `tests/test_providers.py`
- `tests/test_translator_full_doc.py`
- `tests/test_tmdb.py`
- `tests/test_trailer_downloader.py`
- `tests/test_burn.py`
- `tests/test_scheduler.py`

**修改文件**：
- `app/config.py`（DEFAULT_CONFIG 扩展）
- `app/engines/translator.py`（factory 接入 + full-doc 分支 + bug 修复 + TranslationProvider 别名）
- `app/engines/asr.py`（VAD/beam 传参 + language 修复）
- `app/utils/media.py`（`SubtitleTrack` + 多 track burn）
- `app/api/projects.py`（load 安全默认 + `create_trailer_project`）
- `app/api/translate.py`（progress lock + 持久化 + semaphore 接入 + B1 语言修复）
- `app/api/settings.py`（`/api/settings/claude-cli/status` + `/api/settings/tmdb/test`）
- `app/main.py`（include trailer_router）
- `app/static/index.html`（首页卡片 + trailer 向导 view + Settings 条件块 + stage badge）
- `requirements.txt`（加 `yt-dlp`、`claude-agent-sdk`，钉版本）

**新依赖**：
- `yt-dlp>=2025.0.0`（或当前稳定版钉一个具体小版本）
- `claude-agent-sdk>=0.1.0`（具体版本待 Step 6 实施时确认）

---

## 17. 参考

- emby-monitor 的 TMDB 实现：`/Users/gaopengxiang/Desktop/emby-monitor/services/tmdb.py` —— 可复用 client 结构，但本项目用 AI_Sub_Pro 自己的 `config.json` 存 key（不共用 sqlite）。
- 既有 AI_Sub_Pro 架构：FastAPI + Alpine.js + TailwindCSS（CDN）单页应用，Electron 壳，PyInstaller Mac 打包。
