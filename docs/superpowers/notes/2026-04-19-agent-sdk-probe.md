# claude-agent-sdk install + API-shape probe

- **Date**: 2026-04-19
- **Task**: Phase 2 plan, Task 0
- **Repo HEAD at probe time**: `fb07f41`
- **Target Python**: system `python3` = **3.9.6**

## TL;DR

- **Install on system Python 3.9.6: FAILED.** Every published version of
  `claude-agent-sdk` (currently up to **0.1.63**) declares
  `Requires-Python >= 3.10`. pip reports: "Could not find a version that
  satisfies the requirement claude-agent-sdk".
- **Install on Homebrew Python 3.13 (via an isolated venv): SUCCESS.**
  Version resolved: **0.1.63**. End-to-end `query(...)` call returned
  `PROBE_OK` from a live `claude-haiku-4-5` session, so the SDK works and
  auth is already configured on this machine.
- **Recommendation: subprocess fallback (option b).** The system Python the
  app currently ships on (3.9.6) cannot install the SDK. Rather than bump
  the whole project's Python floor to 3.10+ just for one provider, spawn
  the `claude` CLI as a subprocess from the translator. The CLI is already
  working locally (the probe proved so). We revisit using the SDK directly
  if/when the project migrates to Python >= 3.10.

## Step 1 — install attempt on Python 3.9.6

```
$ python3 -m pip install claude-agent-sdk 2>&1 | tail -15
ERROR: Ignored the following versions that require a different python version:
  0.0.23 Requires-Python >=3.10; 0.1.0 Requires-Python >=3.10; ...
  0.1.63 Requires-Python >=3.10
ERROR: Could not find a version that satisfies the requirement claude-agent-sdk
  (from versions: none)
ERROR: No matching distribution found for claude-agent-sdk
```

Every version from `0.0.23` through `0.1.63` is gated on Python >= 3.10.
There is no 3.9-compatible release.

This is a hard blocker for using the SDK on the current app runtime —
but **only for the SDK package**. The `claude` CLI itself is a Node
binary and is unaffected by the Python version, which makes the
subprocess path viable.

## Step 2 — API-shape probe (Python 3.13 venv)

To still get the API shape that Phase 2 needs for design decisions, the
probe was repeated in a throwaway venv (`/opt/homebrew/bin/python3.13
-m venv ...`). Both venv and probe script were deleted afterwards — no
changes to the repo's own environment.

### Installed version

```
Name: claude-agent-sdk
Version: 0.1.63
Summary: Python SDK for Claude Code
Home-page: https://github.com/anthropics/claude-agent-sdk-python
```

### `ClaudeAgentOptions` signature (fields we care about)

The dataclass has many fields; highlights relevant to our translator:

- `model: str | None = None` — e.g. `"claude-haiku-4-5"`.
- `fallback_model: str | None = None`.
- `system_prompt: str | SystemPromptPreset | SystemPromptFile | None`.
- `tools: list[str] | ToolsPreset | None`, `allowed_tools: list[str]`,
  `disallowed_tools: list[str]`.
- `permission_mode: Literal['default','acceptEdits','plan',
  'bypassPermissions','dontAsk','auto'] | None`.
- `max_turns: int | None`, `max_budget_usd: float | None`.
- `cwd: str | Path | None`, `cli_path: str | Path | None`,
  `env: dict[str,str]`, `extra_args: dict[str,str|None]`.
- `continue_conversation: bool`, `resume: str | None`,
  `session_id: str | None`, `fork_session: bool`.
- `can_use_tool` callback, `hooks` dict, `plugins: list[SdkPluginConfig]`,
  `skills: list[str] | Literal['all'] | None`,
  `setting_sources: list[Literal['user','project','local']] | None`,
  `sandbox: SandboxSettings | None`.
- Thinking / effort: `max_thinking_tokens: int | None`,
  `thinking: ThinkingConfig{Adaptive,Enabled,Disabled} | None`,
  `effort: Literal['low','medium','high','max'] | None`.
- I/O: `output_format: dict | None`, `include_partial_messages: bool`,
  `max_buffer_size: int | None`, `stderr` callback,
  `debug_stderr: TextIOWrapper`.
- Agents/tasks: `agents: dict[str, AgentDefinition] | None`,
  `task_budget: TaskBudget | None`,
  `enable_file_checkpointing: bool`.
- `user: str | None`, `betas: list[Literal['context-1m-2025-08-07']]`.

For the translator's needs the short list is: `model`, `system_prompt`,
`max_turns=1`, `permission_mode="bypassPermissions"` (or `'dontAsk'`),
`allowed_tools=[]` / `disallowed_tools`, and `cwd`.

### Message event types observed

Calling `async for msg in query(prompt=..., options=opts)` yielded, in
order:

1. `SystemMessage` (x3 — init/session setup). Attributes: `data`,
   `subtype`.
2. `AssistantMessage`. Attributes: `content`, `error`, `message_id`,
   `model`, `parent_tool_use_id`, `session_id`, `stop_reason`, `usage`,
   `uuid`. `content` is a list of blocks — first a `ThinkingBlock`
   (since extended thinking was on by default for Haiku 4.5), then a
   `TextBlock(text='PROBE_OK')`.
3. `RateLimitEvent`. Attributes: `rate_limit_info`, `session_id`,
   `uuid`.
4. `ResultMessage` (terminal). Attributes: `duration_api_ms`,
   `duration_ms`, `errors`, `is_error`, `model_usage`, `num_turns`,
   `permission_denials`, `result`, `session_id`, `stop_reason`,
   `structured_output`, `subtype`, `total_cost_usd`, `usage`, `uuid`.
   `result` was the literal string `'PROBE_OK'`.

Practical takeaways for the translator:

- The simplest "I just want the final text" integration is to iterate
  until `ResultMessage` and read `.result`. This also gives cost and
  usage in the same event.
- For streaming UX, handle `AssistantMessage` incrementally: iterate
  `msg.content` and only pick `TextBlock` (and skip `ThinkingBlock`
  unless we want to show a "thinking…" indicator).
- `is_error` on `ResultMessage` is the canonical success/failure flag.

## Step 3 — path-forward recommendation

**Recommendation: (b) subprocess fallback**, plus a clean abstraction
seam so we can swap to (a) the SDK later without touching the
translator call sites.

Why not (a) Agent SDK directly now:

- App runs on Python 3.9.6. Bumping the project's Python floor to 3.10+
  just to use one translator provider is a large, unrelated yak-shave
  (CI, packaging, PyInstaller build scripts, frozen deps, the Electron
  wrapper, etc.).
- The `claude` CLI is already installed and authed on this machine, as
  the probe proved (`ResultMessage.result == 'PROBE_OK'`). We get the
  same provider with zero Python-version risk.

Why not (c) escalate to controller:

- The blocker (Python version) is understood and has a concrete,
  minimal workaround (subprocess). Escalation would be appropriate if
  the CLI also didn't work, or if we had no way forward — neither is
  true.

Suggested implementation shape for Task 3 (subprocess provider):

- Module `app/translators/claude_cli_provider.py` exposing the same
  interface as the existing OpenAI-style providers.
- Under the hood: `subprocess.run(["claude", "-p", prompt, "--model",
  model, "--output-format", "json", "--max-turns", "1"], ...)` with a
  timeout and `check=False`; parse the JSON on stdout; surface
  `result` / `is_error` / cost to the caller.
- Honor an env-configurable `cli_path` (default: `claude` on PATH).
- When/if the project moves to Python >= 3.10, add a sibling
  `claude_sdk_provider.py` that uses `claude_agent_sdk.query` and the
  `ResultMessage.result` pattern above. Feature-flag between the two.

## Status

**DONE_WITH_CONCERNS** — SDK install failed on the project's runtime
Python (3.9.6) due to a hard `Requires-Python >= 3.10`. Not a blocker:
subprocess-against-the-CLI is viable and is the recommended Task 3
path. `requirements.txt` was intentionally **not** modified.
