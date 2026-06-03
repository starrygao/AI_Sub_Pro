# Phase 2 — Translator Refactor + Claude CLI Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the translation engine into a pluggable provider architecture, add a new `ClaudeCliProvider` that uses the local Claude Code CLI via the Agent SDK (subscription auth, no API key), and enable full-document translation mode that exploits Claude's 1M context window for cross-subtitle consistency. Also fix B4 (VAD passthrough) and B5 (mlx beam_size) carry-overs from Plan 1.

**Architecture:** New `app/engines/providers/` package with `base.py` (ABC), `factory.py` (registry), `openai_compat.py` (unifies openai/deepseek/gemini), `claude_cli.py` (Agent SDK). `translator.py` refactored to use factory; existing `TranslationProvider` kept as alias for back-compat. Full-doc mode triggers when `batch_size=0` or `full_doc_mode=True` AND provider supports it.

**Tech Stack:** Python 3.9 (system) — note Claude Agent SDK requires ≥3.10; Task 0 will verify and document any version constraint. New deps: `claude-agent-sdk`. Existing: openai SDK, pytest.

**Spec reference:** `docs/superpowers/specs/2026-04-19-trailer-translation-and-foundations-design.md` §5 (translator), §10 B4/B5 (ASR bugs).

**Out of scope (later plans):**
- Trailer module + TMDB + yt-dlp → Plan 3
- Bilingual hard-subtitle burn → Plan 3
- UI changes (settings panels for claude_cli, full-doc toggle) → Plan 4
- Knowledge base redesign → Phase 2 (independent)

---

## Prerequisites

Phase 1 complete; `phase1-foundations-complete` tag exists. 30 tests passing. Working dir is a git repo.

---

## Task 0: Verify claude-agent-sdk install + Python compat

**Files:** none (probe only)

### Steps

- [ ] **Step 1: Try to install**

```bash
python3 -m pip install claude-agent-sdk 2>&1 | tail -10
```

If install succeeds, note the version: `python3 -c "import claude_agent_sdk; print(claude_agent_sdk.__version__)"` (or similar — may not have `__version__`).

If install fails with Python version error: note the required minimum. The system Python is 3.9 — if SDK requires ≥3.10, we have two paths:
- (a) Find a newer Python 3.10+ and recommend AI_Sub_Pro switch (large change)
- (b) Use subprocess fallback (`claude -p` directly) — keep `ClaudeCliProvider` interface, change only the inner implementation

- [ ] **Step 2: Smoke-test query**

If install succeeded, write a tiny script `_probe_sdk.py` (delete after):

```python
from claude_agent_sdk import query, ClaudeAgentOptions
import asyncio

async def main():
    opts = ClaudeAgentOptions(model="claude-haiku-4-5")
    chunks = []
    async for msg in query(prompt="Reply with the literal text: PROBE_OK", options=opts):
        chunks.append(repr(msg)[:200])
    print("\n".join(chunks))

asyncio.run(main())
```

Run: `python3 _probe_sdk.py`. We don't need the model to actually respond (would require login); we want to learn the API shape (event types, attributes, etc.).

- [ ] **Step 3: Document findings + decide path**

Write a single file `docs/superpowers/notes/2026-04-19-agent-sdk-probe.md` with:
- SDK version installed
- Python version requirement
- Top-level event/message types observed (e.g. `AssistantMessage`, `ToolResultMessage`, etc.)
- How to read text content from a message
- Whether system_prompt is a parameter, kwarg, or in options

If SDK won't install on 3.9, document the path forward and STOP — escalate to controller.

- [ ] **Step 4: Commit notes (if SDK installed) or escalate**

```bash
git add docs/superpowers/notes/2026-04-19-agent-sdk-probe.md
git add requirements.txt  # if you append claude-agent-sdk to it
git commit -m "chore(deps): probe claude-agent-sdk install + document API shape"
```

If escalation: leave repo untouched and report BLOCKED with the install error.

---

## Task 1: BaseProvider abstract class + factory

**Files:**
- Create: `app/engines/providers/__init__.py` (empty for now; populated in Task 4)
- Create: `app/engines/providers/base.py`
- Create: `app/engines/providers/factory.py`
- Test: `tests/test_provider_factory.py`

### Steps

- [ ] **Step 1: Create empty package marker**

```bash
mkdir -p app/engines/providers
touch app/engines/providers/__init__.py
```

- [ ] **Step 2: Write failing test `tests/test_provider_factory.py`**

```python
import pytest


def test_base_provider_is_abstract():
    from app.engines.providers.base import BaseProvider
    with pytest.raises(TypeError):
        BaseProvider()  # cannot instantiate abstract


def test_factory_register_and_get():
    from app.engines.providers.base import BaseProvider
    from app.engines.providers.factory import register, get_provider, list_providers, _REGISTRY

    class FakeProvider(BaseProvider):
        def __init__(self, config): self.config = config
        def translate_batch(self, items, system_prompt, retries=3): return []
        def test_connection(self): return True
        @property
        def supports_full_document_mode(self): return False
        @property
        def context_window_tokens(self): return 8000

    _REGISTRY.pop("fake", None)  # clean
    register("fake", FakeProvider)
    assert "fake" in list_providers()
    p = get_provider("fake", {"model": "x"})
    assert isinstance(p, FakeProvider)
    assert p.config == {"model": "x"}


def test_factory_unknown_raises():
    from app.engines.providers.factory import get_provider
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("never-registered", {})
```

- [ ] **Step 3: Run, verify FAIL (ImportError)**

`python3 -m pytest tests/test_provider_factory.py -v`

- [ ] **Step 4: Write `app/engines/providers/base.py`**

```python
"""Abstract base class for translation providers."""
from abc import ABC, abstractmethod
from typing import List, Dict


class BaseProvider(ABC):
    """Contract for any translation backend (OpenAI-compatible, Claude CLI, etc.).

    All providers must accept a config dict at __init__ and implement
    the four abstract methods/properties below. Implementations should be
    safe to call from worker threads.
    """

    @abstractmethod
    def translate_batch(
        self,
        items: List[Dict],
        system_prompt: str,
        retries: int = 3,
    ) -> List[Dict]:
        """Translate items.

        items: [{"id": int, "original": str}, ...]
        Returns: [{"id": int, "translation": str, "error": str}, ...] of equal length.
                 On failure, translation == "" and error contains a non-empty reason.
        """

    @abstractmethod
    def test_connection(self) -> bool:
        """Quickly verify the provider is reachable / authenticated."""

    @property
    @abstractmethod
    def supports_full_document_mode(self) -> bool:
        """True if provider can ingest the entire subtitle file in one call."""

    @property
    @abstractmethod
    def context_window_tokens(self) -> int:
        """Approximate context window in tokens; used to fall back to batched mode."""
```

- [ ] **Step 5: Write `app/engines/providers/factory.py`**

```python
"""Provider registry and factory."""
from typing import Dict, List, Type

from .base import BaseProvider

_REGISTRY: Dict[str, Type[BaseProvider]] = {}


def register(name: str, cls: Type[BaseProvider]) -> None:
    """Register a provider class by name. Idempotent — re-register replaces."""
    _REGISTRY[name] = cls


def get_provider(name: str, config: dict) -> BaseProvider:
    """Instantiate a registered provider with the given config dict."""
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown provider: {name!r}. Registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name](config)


def list_providers() -> List[str]:
    return sorted(_REGISTRY)
```

- [ ] **Step 6: Run, verify PASS**

`python3 -m pytest tests/test_provider_factory.py -v` → 3 passed.

- [ ] **Step 7: Commit**

```bash
git add app/engines/providers/__init__.py app/engines/providers/base.py app/engines/providers/factory.py tests/test_provider_factory.py
git commit -m "feat(providers): BaseProvider abstract class + factory registry"
```

---

## Task 2: OpenAICompatProvider — extract existing TranslationProvider

**Files:**
- Create: `app/engines/providers/openai_compat.py`
- Modify: `app/engines/translator.py` (keep `TranslationProvider` as alias)
- Test: `tests/test_openai_compat_provider.py`

### Steps

- [ ] **Step 1: Inspect current TranslationProvider**

```bash
grep -n "class TranslationProvider\|def __init__\|def translate_batch\|def test_connection" app/engines/translator.py
```

The current class lives in translator.py. Read it (~lines 33-150).

- [ ] **Step 2: Write failing test `tests/test_openai_compat_provider.py`**

```python
from unittest.mock import patch


def test_openai_compat_provider_basic_call():
    from app.engines.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider({
        "provider": "openai",
        "api_key": "sk-test",
        "model": "gpt-4o",
    })
    items = [{"id": 1, "original": "hello"}]

    class FakeResp:
        class C:
            class M:
                content = '[{"id": 1, "translation": "你好"}]'
            message = M()
        choices = [C()]

    with patch.object(p.client.chat.completions, "create", return_value=FakeResp()):
        result = p.translate_batch(items, "sys", retries=1)
    assert result == [{"id": 1, "translation": "你好"}]


def test_openai_compat_provider_supports_full_document():
    from app.engines.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o"})
    assert p.supports_full_document_mode is True
    assert p.context_window_tokens > 0


def test_translation_provider_alias_still_imports():
    """Backward-compat: legacy import path still works."""
    from app.engines.translator import TranslationProvider
    from app.engines.providers.openai_compat import OpenAICompatProvider
    assert TranslationProvider is OpenAICompatProvider
```

- [ ] **Step 3: Run, verify FAIL**

- [ ] **Step 4: Create `app/engines/providers/openai_compat.py`**

This is the main extraction. The file should contain a `OpenAICompatProvider` class that:
1. Implements `BaseProvider` interface
2. Accepts a `config` dict with keys: `provider` (openai/deepseek/gemini), `api_key`, `model`, optional `base_url`
3. Internally constructs an `openai.OpenAI` client
4. `translate_batch` does the same retry + JSON parse + DeepSeek `response_format` handling as the current code
5. On retry exhaustion, returns equal-length list with `{"id", "translation": "", "error": str}` — same B3 contract from Plan 1
6. `supports_full_document_mode = True`
7. `context_window_tokens` returns model-aware estimate

Translate the existing `TranslationProvider` class line-by-line into this new structure. Keep the `_try_parse_json` helper (paste it as a module-level function or static method).

```python
"""OpenAI-compatible provider for openai/deepseek/gemini via the openai SDK."""
import json
import logging
import re
import time
from typing import List, Dict, Optional

from openai import OpenAI

from .base import BaseProvider

log = logging.getLogger(__name__)

PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

_CONTEXT_WINDOWS = {
    # crude per-model estimates; used only to decide whether full-doc mode is feasible
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_384,
    "deepseek-chat": 64_000,
    "gemini-2.0-flash": 1_048_576,
    "gemini-2.5-pro": 2_097_152,
}


def _try_parse_json(text: str):
    """Robust JSON parse: strips markdown, handles trailing commas, extracts arrays."""
    if not text:
        return None
    text = re.sub(r"```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(re.sub(r",\s*([\]}])", r"\1", text))
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    log.warning("Failed to parse JSON: %s...", text[:100])
    return None


class OpenAICompatProvider(BaseProvider):
    """One class for openai / deepseek / gemini via the openai SDK."""

    def __init__(self, config: dict):
        self.provider_name = config.get("provider", "openai")
        self.model = config["model"]
        api_key = config["api_key"]
        base_url = config.get("base_url") or PROVIDER_URLS.get(self.provider_name, PROVIDER_URLS["openai"])
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.is_deepseek = self.provider_name == "deepseek"

    def translate_batch(
        self,
        items: List[Dict],
        system_prompt: str,
        retries: int = 3,
    ) -> List[Dict]:
        user_content = json.dumps(items, ensure_ascii=False)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        last_exc: Optional[Exception] = None
        last_parse_error: str = ""

        for attempt in range(retries):
            try:
                kwargs = {"model": self.model, "messages": messages, "temperature": 0.3}
                if self.is_deepseek:
                    kwargs["response_format"] = {"type": "json_object"}
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                parsed = _try_parse_json(content)
                if parsed is None:
                    last_parse_error = (content or "")[:200]
                    log.warning("Attempt %d: JSON parse failed", attempt + 1)
                    if attempt < retries - 1:
                        time.sleep(1 * (attempt + 1))
                    continue
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    for key in ["translations", "items", "results", "data"]:
                        if key in parsed and isinstance(parsed[key], list):
                            return parsed[key]
                    if "id" in parsed and "translation" in parsed:
                        return [parsed]
                last_parse_error = f"unrecognized JSON shape: {str(parsed)[:200]}"
                if attempt < retries - 1:
                    time.sleep(1 * (attempt + 1))
            except Exception as e:
                last_exc = e
                log.warning("Attempt %d failed: %s", attempt + 1, str(e)[:100])
                if attempt < retries - 1:
                    time.sleep(1 * (attempt + 1))

        bits = []
        if last_exc is not None:
            bits.append(f"{type(last_exc).__name__}: {str(last_exc)[:120]}")
        if last_parse_error:
            bits.append(f"parse: {last_parse_error[:120]}")
        err = " | ".join(bits) if bits else "unknown failure after retries"
        return [{"id": it.get("id"), "translation": "", "error": err} for it in items]

    def test_connection(self) -> bool:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=10,
            )
            return bool(response.choices)
        except Exception as e:
            log.warning("test_connection failed: %s", e)
            return False

    @property
    def supports_full_document_mode(self) -> bool:
        return True

    @property
    def context_window_tokens(self) -> int:
        for prefix, n in _CONTEXT_WINDOWS.items():
            if prefix in self.model.lower():
                return n
        return 32_000
```

- [ ] **Step 5: Add backward-compat alias in translator.py**

In `app/engines/translator.py`, REPLACE the existing `TranslationProvider` class definition with an alias:

```python
# Old TranslationProvider class moved to providers/openai_compat.py — keep alias for back-compat.
from app.engines.providers.openai_compat import OpenAICompatProvider as TranslationProvider
```

Make sure to remove the original class body (and its imports if duplicated — `OpenAI`, `json`, etc. should remain only if other code in translator.py uses them).

⚠️ Some existing translator.py code may reference `_try_parse_json` from the old class. That helper now lives in `providers/openai_compat.py`. If translator.py still uses it, import it from there too.

- [ ] **Step 6: Run tests**

```bash
python3 -m pytest tests/test_openai_compat_provider.py tests/test_translator_failure.py tests/test_translator_context.py -v
```

All must pass. The B3 / B2 tests from Plan 1 are the regression guard for this extraction.

- [ ] **Step 7: Run full suite**

`python3 -m pytest -v` → expect 33 passed (30 + 3 new).

- [ ] **Step 8: Commit**

```bash
git add app/engines/providers/openai_compat.py app/engines/translator.py tests/test_openai_compat_provider.py
git commit -m "feat(providers): extract OpenAICompatProvider; keep TranslationProvider alias"
```

---

## Task 3: ClaudeCliProvider via Agent SDK (with mocked tests)

**Files:**
- Create: `app/engines/providers/claude_cli.py`
- Test: `tests/test_claude_cli_provider.py`

⚠️ Adjust this task based on Task 0's findings. If `claude-agent-sdk` won't install on 3.9, fall back to `subprocess.run(["claude", "-p", prompt, "--output-format", "json"], ...)` for the inner implementation. Public interface (`ClaudeCliProvider(config)`, `translate_batch`, `test_connection`, etc.) stays the same.

### Steps

- [ ] **Step 1: Write failing tests `tests/test_claude_cli_provider.py`**

```python
from unittest.mock import patch, MagicMock


def test_claude_cli_provider_cli_not_installed():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available", return_value=False):
        p = ClaudeCliProvider({"model": "claude-opus-4-7"})
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys")
    assert result[0]["translation"] == ""
    assert "未安装" in result[0]["error"] or "not installed" in result[0]["error"].lower()


def test_claude_cli_provider_not_logged_in():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available", return_value=True), \
         patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_logged_in", return_value=False):
        p = ClaudeCliProvider({"model": "claude-opus-4-7"})
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys")
    assert result[0]["translation"] == ""
    assert "登录" in result[0]["error"] or "login" in result[0]["error"].lower()


def test_claude_cli_provider_supports_full_document():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    assert p.supports_full_document_mode is True
    assert p.context_window_tokens >= 200_000


def test_claude_cli_provider_parse_response():
    """Internal _parse should map response items by id, fall back to error if missing."""
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]
    text = '[{"id": 1, "translation": "甲"}, {"id": 2, "translation": "乙"}]'
    out = p._parse(text, items)
    assert len(out) == 2
    assert out[0]["translation"] == "甲"
    assert out[1]["translation"] == "乙"


def test_claude_cli_provider_parse_handles_markdown_wrap():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    items = [{"id": 1, "original": "a"}]
    text = '```json\n[{"id": 1, "translation": "甲"}]\n```'
    out = p._parse(text, items)
    assert out[0]["translation"] == "甲"


def test_claude_cli_provider_parse_missing_id_returns_error_item():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]
    text = '[{"id": 1, "translation": "甲"}]'  # missing id 2
    out = p._parse(text, items)
    assert out[0]["translation"] == "甲"
    assert out[1]["translation"] == ""
    assert "missing" in out[1]["error"].lower() or "缺失" in out[1]["error"]
```

- [ ] **Step 2: Run, verify FAIL (ImportError or AttributeError)**

- [ ] **Step 3: Write `app/engines/providers/claude_cli.py`**

Use **Task 0's findings** to choose between Agent SDK and subprocess. Below is the Agent SDK form; adapt if needed.

```python
"""Claude Code CLI provider using the Agent SDK (subscription auth, no API key)."""
import asyncio
import json
import logging
import re
import subprocess
import time
from typing import List, Dict, Optional

from .base import BaseProvider

log = logging.getLogger(__name__)


class ClaudeCliProvider(BaseProvider):
    """Translation via local Claude Code CLI; uses user's subscription auth."""

    def __init__(self, config: dict):
        self.model = config.get("model", "claude-opus-4-7")
        self.timeout_sec = int(config.get("timeout_sec", 180))

    @staticmethod
    def check_cli_available() -> bool:
        try:
            r = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def check_logged_in() -> bool:
        """Best-effort login check. Falls back to assuming logged-in if probe is unreliable."""
        # Try a few candidate commands; CLI versions vary.
        for cmd in (["claude", "auth", "status"], ["claude", "auth", "whoami"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    out = (r.stdout + r.stderr).lower()
                    if any(s in out for s in ("logged in", "authenticated", "@")):
                        return True
            except Exception:
                continue
        # If no probe worked, optimistically return True so we surface real errors during translate
        return True

    def test_connection(self) -> bool:
        return self.check_cli_available() and self.check_logged_in()

    @property
    def supports_full_document_mode(self) -> bool:
        return True

    @property
    def context_window_tokens(self) -> int:
        return 1_000_000

    def translate_batch(self, items, system_prompt, retries: int = 3):
        if not self.check_cli_available():
            return [self._err(it, "Claude Code CLI 未安装或不在 PATH (Claude Code CLI not installed)") for it in items]
        if not self.check_logged_in():
            return [self._err(it, "Claude Code 未登录: 请运行 `claude` 完成登录 (not logged in)") for it in items]

        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            try:
                text = self._invoke(items, system_prompt)
                return self._parse(text, items)
            except Exception as e:
                last_exc = e
                log.warning("Claude CLI attempt %d failed: %s", attempt + 1, str(e)[:120])
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        err = f"{type(last_exc).__name__}: {str(last_exc)[:120]}" if last_exc else "Claude CLI failure"
        return [self._err(it, err) for it in items]

    def _invoke(self, items, system_prompt) -> str:
        """Run a single Claude CLI query and return the assistant text."""
        # Try Agent SDK first (preferred); fall back to subprocess if SDK absent
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions
            opts = ClaudeAgentOptions(model=self.model, system_prompt=system_prompt)
            user_content = json.dumps(items, ensure_ascii=False)
            chunks: List[str] = []

            async def _run():
                async for msg in query(prompt=user_content, options=opts):
                    text = self._extract_text(msg)
                    if text:
                        chunks.append(text)

            asyncio.run(asyncio.wait_for(_run(), timeout=self.timeout_sec))
            return "".join(chunks)
        except ImportError:
            return self._invoke_subprocess(items, system_prompt)

    def _invoke_subprocess(self, items, system_prompt) -> str:
        """Subprocess fallback when Agent SDK is unavailable."""
        prompt = system_prompt + "\n\n" + json.dumps(items, ensure_ascii=False)
        cmd = ["claude", "-p", prompt, "--model", self.model]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_sec)
        if r.returncode != 0:
            raise RuntimeError(f"claude CLI exit {r.returncode}: {r.stderr[:200]}")
        return r.stdout

    @staticmethod
    def _extract_text(msg) -> str:
        """Pull text content out of an Agent SDK message (shape varies by version)."""
        for attr in ("text", "content", "result", "output"):
            v = getattr(msg, attr, None)
            if isinstance(v, str):
                return v
            if isinstance(v, list):
                # content blocks: try .text on each
                parts = []
                for b in v:
                    bt = getattr(b, "text", None)
                    if isinstance(bt, str):
                        parts.append(bt)
                if parts:
                    return "".join(parts)
        return ""

    @staticmethod
    def _err(item, msg: str) -> dict:
        return {"id": item.get("id"), "translation": "", "error": msg}

    @staticmethod
    def _parse(text: str, items: List[Dict]) -> List[Dict]:
        """Map Claude's response back to per-item results."""
        if not text:
            return [ClaudeCliProvider._err(it, "empty response from Claude CLI") for it in items]
        cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"```", "", cleaned).strip()
        parsed = None
        try:
            parsed = json.loads(re.sub(r",\s*([\]}])", r"\1", cleaned))
        except Exception:
            m = re.search(r"\[.*\]", cleaned, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except Exception:
                    parsed = None

        if not isinstance(parsed, list):
            return [ClaudeCliProvider._err(it, f"unparseable response: {cleaned[:120]}") for it in items]

        by_id = {str(r.get("id")): r for r in parsed if isinstance(r, dict)}
        out = []
        for it in items:
            r = by_id.get(str(it.get("id")))
            if r and r.get("translation"):
                out.append({"id": it.get("id"), "translation": r["translation"], "error": ""})
            else:
                out.append(ClaudeCliProvider._err(it, "missing or empty in response"))
        return out
```

- [ ] **Step 4: Run, verify PASS**

`python3 -m pytest tests/test_claude_cli_provider.py -v` → 6 passed.

- [ ] **Step 5: Run full suite**

`python3 -m pytest -v` → expect 39 passed (33 + 6).

- [ ] **Step 6: Commit**

```bash
git add app/engines/providers/claude_cli.py tests/test_claude_cli_provider.py
git commit -m "feat(providers): ClaudeCliProvider via Agent SDK (subscription auth)"
```

---

## Task 4: Register builtin providers + integration test

**Files:**
- Modify: `app/engines/providers/__init__.py`
- Test: `tests/test_provider_registration.py`

### Steps

- [ ] **Step 1: Write failing test**

```python
def test_builtin_providers_registered():
    import app.engines.providers  # triggers registration
    from app.engines.providers.factory import list_providers

    names = list_providers()
    assert "openai" in names
    assert "deepseek" in names
    assert "gemini" in names
    assert "claude_cli" in names


def test_get_openai_provider_via_factory():
    import app.engines.providers
    from app.engines.providers.factory import get_provider
    from app.engines.providers.openai_compat import OpenAICompatProvider

    p = get_provider("openai", {"provider": "openai", "api_key": "sk-x", "model": "gpt-4o"})
    assert isinstance(p, OpenAICompatProvider)


def test_get_claude_cli_provider_via_factory():
    import app.engines.providers
    from app.engines.providers.factory import get_provider
    from app.engines.providers.claude_cli import ClaudeCliProvider

    p = get_provider("claude_cli", {"model": "claude-opus-4-7"})
    assert isinstance(p, ClaudeCliProvider)
```

- [ ] **Step 2: Run, verify FAIL** (registry empty)

- [ ] **Step 3: Populate `app/engines/providers/__init__.py`**

```python
"""Provider registry initialization. Importing this package registers all builtins."""
from .factory import register
from .openai_compat import OpenAICompatProvider
from .claude_cli import ClaudeCliProvider

# Three OpenAI-compatible providers share one class (parametrized by provider name).
register("openai", OpenAICompatProvider)
register("deepseek", OpenAICompatProvider)
register("gemini", OpenAICompatProvider)

# Claude CLI (separate class, uses Agent SDK / subprocess).
register("claude_cli", ClaudeCliProvider)
```

- [ ] **Step 4: Run, verify PASS**

- [ ] **Step 5: Full suite**

`python3 -m pytest -v` → expect 42 passed.

- [ ] **Step 6: Commit**

```bash
git add app/engines/providers/__init__.py tests/test_provider_registration.py
git commit -m "feat(providers): register openai/deepseek/gemini/claude_cli at package import"
```

---

## Task 5: Wire translator.py to factory + full-document mode

**Files:**
- Modify: `app/engines/translator.py` (`SubtitleTranslator` class)
- Test: `tests/test_translator_full_doc.py`

### Steps

- [ ] **Step 1: Inspect SubtitleTranslator**

`grep -n "class SubtitleTranslator\|def __init__\|self.primary\|self.polish" app/engines/translator.py`

Note how the current `__init__` constructs `self.primary` and `self.polish` — currently it instantiates `TranslationProvider(...)` directly. We'll route through factory.

- [ ] **Step 2: Write failing tests**

```python
from unittest.mock import patch, MagicMock
from datetime import timedelta


def test_translator_uses_factory_for_primary(monkeypatch):
    """SubtitleTranslator should call get_provider() to build self.primary."""
    from app.engines import translator as tmod
    captured = {}

    def fake_get_provider(name, config):
        captured["name"] = name
        captured["config"] = config
        return MagicMock()

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
            "target_language": "简体中文",
        },
        "api_keys": {"openai": "sk-test"},
    }
    tmod.SubtitleTranslator(cfg)

    assert captured["name"] == "openai"
    assert captured["config"]["model"] == "gpt-4o"
    assert captured["config"]["api_key"] == "sk-test"


def test_full_doc_mode_sends_all_blocks_in_one_call(monkeypatch):
    """When batch_size=0 and provider supports full-doc, translate sends one big batch."""
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 0,           # 0 → full-doc mode
            "context_window": 3,
            "target_language": "简体中文",
            "full_doc_mode": True,
        },
        "api_keys": {"openai": "sk-test"},
    }
    captured = []

    def fake_translate_batch(items, system_prompt, retries=3):
        captured.append(len(items))
        return [{"id": it["id"], "translation": f"t-{it['id']}", "error": ""} for it in items]

    t = SubtitleTranslator(cfg)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)

    blocks = [SubtitleBlock(index=i, start=timedelta(seconds=i), end=timedelta(seconds=i+1), text=f"line {i}") for i in range(20)]
    t.translate(blocks, target_lang="简体中文")

    assert len(captured) == 1
    assert captured[0] == 20  # all blocks in one shot


def test_full_doc_falls_back_to_batched_if_too_large(monkeypatch):
    """If estimated tokens exceed 80% of context window, fall back to batched mode."""
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-3.5-turbo",  # 16k context
            "polish_provider": "",
            "batch_size": 0,
            "context_window": 3,
            "target_language": "简体中文",
            "full_doc_mode": True,
        },
        "api_keys": {"openai": "sk-test"},
    }
    captured = []
    def fake_translate_batch(items, system_prompt, retries=3):
        captured.append(len(items))
        return [{"id": it["id"], "translation": "t", "error": ""} for it in items]

    t = SubtitleTranslator(cfg)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)

    # Force fallback: very long text per block
    big_text = "x" * 50_000  # ~25k tokens per block
    blocks = [SubtitleBlock(index=i, start=timedelta(seconds=i), end=timedelta(seconds=i+1), text=big_text) for i in range(5)]
    t.translate(blocks, target_lang="简体中文")

    # Fell back to batched (multiple calls), not single full-doc
    assert len(captured) > 1
```

- [ ] **Step 3: Run, verify FAIL**

- [ ] **Step 4: Wire factory + full-doc into SubtitleTranslator**

In `app/engines/translator.py`:

a. Import factory at top:
```python
import app.engines.providers  # ensure builtins registered
from app.engines.providers.factory import get_provider
```

b. In `SubtitleTranslator.__init__`, replace direct `TranslationProvider(...)` with:
```python
trans_cfg = config.get("translation", {})
api_keys = config.get("api_keys", {})
providers_cfg = config.get("providers", {})

primary_name = trans_cfg.get("primary_provider", "openai")
primary_model = trans_cfg.get("primary_model", "gpt-4o")
primary_config = self._build_provider_config(primary_name, primary_model, api_keys, providers_cfg)
self.primary = get_provider(primary_name, primary_config)

polish_name = trans_cfg.get("polish_provider", "")
if polish_name:
    polish_model = trans_cfg.get("polish_model", primary_model)
    polish_config = self._build_provider_config(polish_name, polish_model, api_keys, providers_cfg)
    self.polish = get_provider(polish_name, polish_config)
else:
    self.polish = None

self.full_doc_mode = trans_cfg.get("full_doc_mode", False) or trans_cfg.get("batch_size", 10) == 0
```

c. Add a helper:
```python
@staticmethod
def _build_provider_config(name: str, model: str, api_keys: dict, providers_cfg: dict) -> dict:
    """Compose a provider config dict from various config sections."""
    if name == "claude_cli":
        cc = providers_cfg.get("claude_cli", {})
        return {"model": cc.get("model", model), "timeout_sec": cc.get("timeout_sec", 180)}
    return {
        "provider": name,
        "model": model,
        "api_key": api_keys.get(name, ""),
    }
```

d. Add full-doc translation entry point — modify `translate(blocks, target_lang, ...)`:
```python
def translate(self, blocks, target_lang, ...):
    if self.full_doc_mode and getattr(self.primary, "supports_full_document_mode", False):
        if self._fits_full_doc(blocks):
            return self._translate_full_document(blocks, target_lang, ...)
        else:
            log.info("full_doc fallback to batched: estimated tokens exceed 80%% of window")
    return self._translate_batched(blocks, target_lang, ...)  # existing path
```

e. Add `_fits_full_doc`:
```python
def _fits_full_doc(self, blocks) -> bool:
    active = [b for b in blocks if not b.filtered and b.text.strip()]
    est_tokens = sum(len(b.text) for b in active) // 2  # crude: ~2 chars per token
    return est_tokens < int(getattr(self.primary, "context_window_tokens", 32_000) * 0.8)
```

f. Add `_translate_full_document`:
```python
def _translate_full_document(self, blocks, target_lang, ...):
    active = [b for b in blocks if not b.filtered and b.text.strip()]
    items = [{"id": b.index, "original": b.text} for b in active]
    system_prompt = self._build_prompt(target_lang, ...)  # reuse existing prompt builder
    log.info("full_doc translate: %d blocks in one shot", len(items))
    results = self.primary.translate_batch(items, system_prompt)
    self._apply_results(blocks, results)
    return blocks
```

g. Refactor existing per-block apply code into `_apply_results(blocks, results)` (extract from current code path) and reuse from both batched and full-doc paths. Mind the B3 contract from Plan 1 (error field handling).

- [ ] **Step 5: Run tests**

`python3 -m pytest tests/test_translator_full_doc.py tests/test_translator_context.py tests/test_translator_failure.py -v`

All must pass.

- [ ] **Step 6: Run full suite**

`python3 -m pytest -v` → expect 45 passed (42 + 3).

- [ ] **Step 7: Commit**

```bash
git add app/engines/translator.py tests/test_translator_full_doc.py
git commit -m "feat(translator): route through provider factory + add full-document mode"
```

---

## Task 6: Bug B4 — VAD filter passthrough in ASR

**Files:**
- Modify: `app/engines/asr.py`
- Test: `tests/test_asr_vad.py`

### Steps

- [ ] **Step 1: Inspect current ASR**

```bash
grep -n "vad_filter\|transcribe\|beam_size\|model_size" app/engines/asr.py
```

Note: the openai-whisper backend doesn't support `vad_filter` natively (faster-whisper does). If AI_Sub_Pro uses openai-whisper or mlx_whisper, VAD may be a no-op for those backends — document this in code.

- [ ] **Step 2: Write failing test `tests/test_asr_vad.py`**

```python
from unittest.mock import patch, MagicMock


def test_vad_filter_config_passed_to_faster_whisper(monkeypatch):
    """If faster-whisper backend is used, vad_filter from config must be passed through."""
    from app.engines import asr

    config = {
        "asr": {"model_size": "small", "language": "auto", "vad_filter": True, "beam_size": 5, "use_demucs": False, "offset_ms": 0},
        "general": {},
    }

    captured = {}

    class FakeModel:
        def transcribe(self, audio_path, **kwargs):
            captured.update(kwargs)
            return iter([]), MagicMock(language="en")

    monkeypatch.setattr(asr, "_load_faster_whisper_model", lambda *a, **k: FakeModel(), raising=False)
    # If your ASR module uses a different loader, adapt the monkeypatch target

    # Pseudocode — call actual ASR entry point with config
    # This test may need adjustment depending on ASR module structure
    try:
        asr.run_asr("/fake/audio.wav", config)
    except Exception:
        pass  # we only care about kwargs captured

    assert captured.get("vad_filter") is True
```

⚠️ This test is a TEMPLATE — the actual ASR entry point name and faster-whisper integration shape vary. Read `app/engines/asr.py` first to determine correct test approach. If the codebase uses openai-whisper exclusively (no faster-whisper), document that VAD is unsupported and either:
- Mark the test xfail with explanation
- Replace test with one that asserts VAD is read from config and stored on the ASR object (even if not transmitted to whisper)

- [ ] **Step 3: Make VAD reach the whisper transcribe call**

In `app/engines/asr.py`:
- Read `vad_filter` from config (likely already done)
- Pass it as a kwarg to whatever `transcribe()` call exists, IF the backend supports it
- For openai-whisper and mlx_whisper: log a one-time warning that VAD is configured but not supported by the active backend

```python
opts = {...existing...}
if vad_filter and _backend_supports_vad():
    opts["vad_filter"] = True
elif vad_filter:
    log.info("vad_filter=True ignored: %s backend does not support it", _backend_name())
```

If the codebase doesn't have a backend abstraction, just hardwire the path that's most likely correct based on the imports.

- [ ] **Step 4: Run, verify PASS** (or xfail if backend doesn't support VAD)

- [ ] **Step 5: Commit**

```bash
git add app/engines/asr.py tests/test_asr_vad.py
git commit -m "fix(asr): B4 pass vad_filter to whisper backend (or warn when unsupported)"
```

---

## Task 7: Bug B5 — mlx_whisper beam_size

**Files:**
- Modify: `app/engines/asr.py`
- Test: extend `tests/test_asr_vad.py` (rename to `tests/test_asr_options.py` if making it broader)

### Steps

- [ ] **Step 1: Check mlx_whisper API**

```bash
python3 -c "import mlx_whisper; help(mlx_whisper.transcribe)" 2>&1 | head -40
```

If `transcribe` accepts `beam_size`, pass it. If not, log a warning when `beam_size != 5` (default) is configured.

- [ ] **Step 2: Add test (or skip if mlx_whisper unavailable)**

```python
import pytest


def test_mlx_beam_size_passed_when_supported():
    """If mlx_whisper.transcribe accepts beam_size, our caller must pass it."""
    pytest.importorskip("mlx_whisper")
    import inspect
    import mlx_whisper
    sig = inspect.signature(mlx_whisper.transcribe)
    if "beam_size" not in sig.parameters and "decode_options" not in sig.parameters:
        pytest.skip("mlx_whisper does not expose beam_size")
    # If supported, verify our ASR wrapper passes it
    # This test is implementation-dependent; adapt to actual ASR module
```

- [ ] **Step 3: Modify ASR mlx code path**

```python
if _USING_MLX:
    transcribe_kwargs = {}
    if "beam_size" in inspect.signature(mlx_whisper.transcribe).parameters:
        transcribe_kwargs["beam_size"] = beam_size
    elif beam_size != 5:
        log.info("mlx_whisper does not accept beam_size; ignoring config beam_size=%d", beam_size)
    result = mlx_whisper.transcribe(audio_path, **transcribe_kwargs)
```

- [ ] **Step 4: Run tests + commit**

```bash
git add app/engines/asr.py tests/test_asr_vad.py  # or tests/test_asr_options.py
git commit -m "fix(asr): B5 pass beam_size to mlx_whisper when supported"
```

---

## Task 8: Settings API — claude-cli status + extend test-key

**Files:**
- Modify: `app/api/settings.py`
- Test: `tests/test_settings_claude_cli.py`

### Steps

- [ ] **Step 1: Inspect existing settings.py**

```bash
grep -n "@router\|def test_" app/api/settings.py
```

- [ ] **Step 2: Write failing tests `tests/test_settings_claude_cli.py`**

```python
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_claude_cli_status_endpoint_reports_installed_and_logged_in():
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available", return_value=True), \
         patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_logged_in", return_value=True):
        r = client.get("/api/settings/claude-cli/status")
    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is True
    assert data["logged_in"] is True


def test_claude_cli_status_endpoint_reports_not_installed():
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.check_cli_available", return_value=False):
        r = client.get("/api/settings/claude-cli/status")
    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is False


def test_test_key_supports_claude_cli():
    """POST /api/settings/test-key should accept provider=claude_cli (no api_key needed)."""
    from app.main import app
    client = TestClient(app)

    with patch("app.engines.providers.claude_cli.ClaudeCliProvider.test_connection", return_value=True):
        r = client.post("/api/settings/test-key", json={"provider": "claude_cli", "model": "claude-opus-4-7"})
    assert r.status_code == 200
    assert r.json()["success"] is True
```

- [ ] **Step 3: Run, verify FAIL**

- [ ] **Step 4: Add endpoints in `app/api/settings.py`**

```python
from app.engines.providers.claude_cli import ClaudeCliProvider

@router.get("/settings/claude-cli/status")
def claude_cli_status():
    return {
        "installed": ClaudeCliProvider.check_cli_available(),
        "logged_in": ClaudeCliProvider.check_logged_in(),
    }
```

For `/test-key`, find the existing endpoint and add a `claude_cli` branch:

```python
@router.post("/settings/test-key")
def test_key(req: ...):
    if req.provider == "claude_cli":
        from app.engines.providers.claude_cli import ClaudeCliProvider
        p = ClaudeCliProvider({"model": req.model})
        ok = p.test_connection()
        return {"success": ok, "message": "OK" if ok else "Claude CLI 未安装或未登录"}
    # ...existing openai/deepseek/gemini path...
```

If the request model doesn't currently allow optional api_key, update the Pydantic model to make api_key optional.

- [ ] **Step 5: Run tests + commit**

```bash
python3 -m pytest tests/test_settings_claude_cli.py -v
python3 -m pytest -v  # expect 48 passed (45 + 3)
git add app/api/settings.py tests/test_settings_claude_cli.py
git commit -m "feat(settings): claude-cli status endpoint + extend test-key for claude_cli provider"
```

---

## Task 9: Phase 2 smoke + tag complete

**Files:** none

### Steps

- [ ] **Step 1: Full suite**

`python3 -m pytest -v` → ALL passing (~48 tests).

- [ ] **Step 2: Boot app, verify imports work**

```bash
python3 -c "from app.main import app; print('imports ok')"
```

- [ ] **Step 3: Tag**

```bash
git tag phase2-translator-claude-complete
```

- [ ] **Step 4: Audit gate** — controller dispatches 3 audit agents:
  - **Agent A**: Provider abstraction soundness (ABC, factory, no leaks of concrete provider details into translator.py)
  - **Agent B**: Full-document mode correctness (token estimation, fallback path, regression of batched mode)
  - **Agent C**: Backward compat — `TranslationProvider` alias still works; existing translation flows in `api/translate.py` unchanged

If any audit fails, fix before declaring Plan 2 complete.

---

## Out of this plan (Plan 3 / 4)

- **Plan 3**: TMDB + yt-dlp + trailer pipeline + bilingual burn (uses ClaudeCliProvider as default for trailer projects when configured)
- **Plan 4**: Settings UI for claude_cli (model dropdown + warning panel + status check button); homepage trailer entry; UI redesign
