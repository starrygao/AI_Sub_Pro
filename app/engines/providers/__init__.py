"""Provider registry initialization. Importing this package registers all builtins."""
from .factory import register
from .openai_compat import OpenAICompatProvider
from .claude_cli import ClaudeCliProvider
from .codex_cli import CodexCliProvider

# Three OpenAI-compatible providers share one class.
register("openai", OpenAICompatProvider)
register("deepseek", OpenAICompatProvider)
register("gemini", OpenAICompatProvider)

# Local CLI providers (subprocess-backed).
register("claude_cli", ClaudeCliProvider)
register("codex_cli", CodexCliProvider)
