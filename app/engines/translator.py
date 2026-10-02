"""
Multi-model subtitle translation engine with context window support.
Uses OpenAI SDK for OpenAI-compat providers and subprocess for local CLI providers.
Provider construction is routed through the Phase 2 provider factory.
"""
import json
import logging
import re
from typing import List, Dict, Optional, Callable

from app.utils.srt import SubtitleBlock

# TranslationProvider was extracted to providers/openai_compat.py during the
# Phase 2 refactor. Keep the legacy name + helpers importable from here so
# external callers (api/settings.py, tests, knowledge.py) keep working.
from app.engines.providers.openai_compat import (  # noqa: F401
    OpenAICompatProvider as TranslationProvider,
    PROVIDER_URLS,
    _try_parse_json,
)

# Importing the providers package has the side-effect of registering
# openai/deepseek/gemini/claude_cli/codex_cli with the factory. Do it here so any
# caller that imports translator.py gets a populated registry.
import app.engines.providers  # noqa: F401  (registration side-effect)
from app.engines.providers.factory import get_provider, list_providers
from app.engines.providers.result_contract import (
    MISSING_ID_ERROR,
    MISSING_TRANSLATION_ERROR,
    reconcile_translation_results,
)
from app.engines.kb_trace import TranslationContextTrace, trace_for_project_kb
from app.engines.phrase_library import PhraseLibrary
from app.engines.translation_memory import TranslationMemoryStore, _lang as _memory_lang
from app.engines.content_profiles import (
    build_content_profile_prompt_snippet,
    infer_content_profiles,
)
from app.engines.domain_terms import (
    build_auto_scientific_prompt_snippet,
    build_domain_prompt_snippet,
    find_domain_terms_in_texts,
    find_scientific_terms_in_texts,
)
from app.engines.project_metadata import build_project_metadata_prompt_snippet
from app.engines.subtitle_style_profiles import build_subtitle_style_prompt_snippet
from app.engines.terminology_conflicts import collect_terminology_conflicts
from app.engines.translation_qa import (
    translation_candidate_contract_error, classify_subtitle_source,
)
from app.engines.discourse_links import (
    build_discourse_link_contexts,
    detect_possessive_echo_links,
    index_discourse_link_contexts,
    serialized_discourse_link_contexts_chars,
)

log = logging.getLogger(__name__)

# KB v2 singleton (loaded once at translator module import). Tests may
# monkey-patch `_shared_kb` to inject a controlled KnowledgeBase instance.
from app.engines.knowledge import KnowledgeBase, build_prompt_snippet as _kb_build_snippet
from app.utils.translation_configuration import project_knowledge

_shared_kb = KnowledgeBase()
try:
    _shared_kb.load()
except Exception as _e:  # pragma: no cover — best-effort load
    log.warning("KB load failed at translator import: %s", _e)

# Fallback batch size used when batch_size is configured as 0 (full-doc mode)
# but we need to fall back to the batched path (e.g. document too large for
# the primary provider's context window).
_FULL_DOC_FALLBACK_BATCH_SIZE = 10
_MISSING_TRANSLATION_RETRY_NOTE = (
    "补翻要求: 上一轮这些字幕缺失或格式无效。本轮只翻译当前输入 JSON 中的条目，"
    "每个输入 id 都必须返回非空译文；未识别的括号内容也要翻译，不得擅自留空。"
)
_SPEAKER_LINE_PROMPT_RULE = (
    "原文含两个或更多说话人行（每行以 -/–/— 开头，或以“姓名:”标注）时，"
    "每位说话人独占一行并保持原顺序和标记；不得合并说话人行，"
    "JSON 字符串中的换行必须写为 \\n。"
)

# Read-only evidence is bounded independently of mutable subtitle text. Keep
# raw SDH here: omitted sound captions can still disambiguate spoken dialogue.
_SUBTITLE_CONTEXT_CUES = 3
_SUBTITLE_CONTEXT_TEXT_CHARS = 800


def _subtitle_context_item(block) -> dict:
    item = {"id": getattr(block, "index", None)}
    for key, attr in (("original", "text"), ("draft", "translation")):
        text = getattr(block, attr, "")
        text = text if isinstance(text, str) else ""
        item[key] = text[:_SUBTITLE_CONTEXT_TEXT_CHARS]
        if len(text) > _SUBTITLE_CONTEXT_TEXT_CHARS:
            item[f"{key}_truncated"] = True
    return item


def _subtitle_context_window(
    blocks, position: int, radius: int = _SUBTITLE_CONTEXT_CUES, *, sound_only: bool = False,
):
    """Return bounded timeline neighbors, never promoting them to target IDs."""
    radius = max(0, min(radius, 50))

    def context(start, end):
        rows = []
        for block in blocks[start:end]:
            source = getattr(block, "text", "")
            if not isinstance(source, str) or not source.strip():
                continue
            block_id = getattr(block, "index", None)
            if not isinstance(block_id, int) or isinstance(block_id, bool):
                continue
            if sound_only and classify_subtitle_source(source).kind != "sound":
                continue
            # Filtered ads/credits are not dialogue evidence. Source-confirmed
            # sounds remain useful even when intentionally omitted from export.
            if getattr(block, "filtered", False) and classify_subtitle_source(source).kind != "sound":
                continue
            rows.append(_subtitle_context_item(block))
        return rows

    return (
        context(max(0, position - radius), position),
        context(position + 1, position + radius + 1),
    )

_PHRASE_CONTEXT_KEYWORDS = {
    "medical": {
        "medical", "medicine", "doctor", "hospital", "clinic", "patient",
        "surgery", "surgeon", "diagnosis", "neurology", "brilliant minds",
    },
    "crime": {
        "crime", "police", "detective", "murder", "homicide", "investigation",
        "case", "suspect", "witness", "fbi", "procedural",
    },
    "workplace": {
        "workplace", "office", "company", "startup", "client", "meeting",
        "deadline", "board", "budget", "presentation",
    },
    "school": {"school", "college", "campus", "student", "teacher", "class"},
    "party": {"party", "bar", "club", "after party", "night out"},
    "romance": {"romance", "date", "dating", "wedding", "love", "relationship"},
    "sci-fi": {"sci-fi", "science fiction", "alien", "spaceship", "robot", "android"},
    "fantasy": {"fantasy", "magic", "kingdom", "vampire", "witch", "dragon"},
    "interview": {"interview", "talk show", "podcast", "q&a", "qa"},
    "documentary": {"documentary", "docuseries", "unscripted", "non-fiction", "nonfiction"},
    "comedy": {"comedy", "sitcom", "stand-up", "standup"},
    "anime": {"anime", "animation", "アニメ"},
    "technical": {"tutorial", "course", "programming", "coding", "developer", "how-to"},
    "adult": {"adult", "av", "legal adult", "adult video"},
}

_ADULT_PHRASE_TAGS = {"adult", "explicit", "legal_adult"}


def _provider_context_window(provider, default: int = 32_000) -> int:
    raw = getattr(provider, "context_window_tokens", default) or default
    if isinstance(raw, bool):
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _provider_full_document_max_items(provider) -> Optional[int]:
    raw = getattr(provider, "full_document_max_items", None)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw > 0 else None


def _coerce_int_setting(value, default: int, *, min_value: int, max_value: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if parsed < min_value or parsed > max_value:
        return default
    return parsed


def _coerce_bool_setting(value, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_choice_setting(value, valid_choices: set[str], default: str) -> str:
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower()
    if normalized not in valid_choices:
        return default
    return normalized


def _coerce_bounded_int_setting(value, default: int, *, min_value: int, max_value: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(min_value, min(max_value, parsed))


def _dict_section(config: dict, key: str) -> dict:
    value = config.get(key, {}) if isinstance(config, dict) else {}
    return value if isinstance(value, dict) else {}


def _coerce_text_setting(value, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value or default


def _coerce_provider_name(value, default: str = "omp_cli", *, allow_empty: bool = False) -> str:
    if value is None:
        return "" if allow_empty else default
    if not isinstance(value, str):
        return default
    value = value.strip()
    if allow_empty and not value:
        return ""
    if value not in list_providers():
        return default
    return value


def _phrase_context_tags(meta_info: dict) -> set[str]:
    if not isinstance(meta_info, dict):
        return set()
    parts = []
    for key in (
        "name",
        "show_title",
        "title",
        "original_title",
        "plot",
        "overview",
        "tmdb_type",
    ):
        value = meta_info.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("genres", "genre", "tags"):
        value = meta_info.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(item for item in value if isinstance(item, str))
    text = " ".join(parts).lower()
    if not text:
        return set()

    tags = set()
    for tag, keywords in _PHRASE_CONTEXT_KEYWORDS.items():
        for keyword in keywords:
            pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
            if re.search(pattern, text):
                tags.add(tag)
                break
    return tags


def _allows_legal_adult_phrase_examples(meta_info: dict) -> bool:
    return any(profile.id == "legal_adult" for profile in infer_content_profiles(meta_info))


def _has_technical_tutorial_profile(meta_info: Optional[Dict]) -> bool:
    return any(
        profile.id == "technical_tutorial"
        for profile in infer_content_profiles(meta_info if isinstance(meta_info, dict) else {})
    )


def _is_legal_adult_phrase_hit(hit) -> bool:
    pack_id = str(getattr(hit, "pack_id", "") or "").casefold()
    tags = {
        tag
        for tag in re.split(r"[,;\s]+", str(getattr(hit, "tags", "") or "").casefold())
        if tag
    }
    return "domain_legal_adult" in pack_id or bool(tags & _ADULT_PHRASE_TAGS)


def _trace_hit_key(hit: dict) -> str:
    try:
        return json.dumps(hit, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(hit)


def _append_unique_trace_hit(target: list, hit: dict) -> None:
    if not isinstance(hit, dict):
        return
    key = _trace_hit_key(hit)
    if any(_trace_hit_key(existing) == key for existing in target if isinstance(existing, dict)):
        return
    target.append(hit)


def _extend_unique_trace_hits(target: list, hits: list[dict]) -> None:
    for hit in hits or []:
        _append_unique_trace_hit(target, hit)


def _clean_prompt_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _build_auto_kb_candidate_snippet(kb_data: Dict, limit: int = 30) -> tuple[str, list[dict]]:
    raw_items = kb_data.get("candidate_terms") if isinstance(kb_data, dict) else []
    if not isinstance(raw_items, list):
        return "", []

    lines: list[str] = []
    hits: list[dict] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        source = _clean_prompt_text(raw.get("source"))
        if not source:
            continue
        key = source.casefold()
        if key in seen:
            continue
        target = _clean_prompt_text(raw.get("target"))
        category = _clean_prompt_text(raw.get("category"))
        status = _clean_prompt_text(raw.get("status")) or "pending"
        confidence = raw.get("confidence")
        suffix = []
        if target:
            suffix.append(f"suggested target: {target}")
        if category:
            suffix.append(f"category: {category}")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            suffix.append(f"confidence: {float(confidence):.2f}")
        detail = f" ({'; '.join(suffix)})" if suffix else ""
        lines.append(f"  - {source}{detail}")
        hits.append({
            "scope": "auto_kb_candidate",
            "source": source,
            "target": target,
            "category": category,
            "status": status,
        })
        seen.add(key)
        if len(lines) >= limit:
            break

    if not lines:
        return "", []
    snippet = "\n".join([
        "自动知识库候选（未审定，低于正式项目知识库、手动术语和用户修订记忆）:",
        *lines,
        "使用方式: 将这些源词视为本片可能出现的专名/地点/术语，在语境匹配时保持译名一致；没有译名时请自行给出自然译法，不要把候选当作必须照抄的硬约束。",
    ])
    return snippet, hits


def _is_retryable_translation_result(result: dict, item: dict) -> bool:
    original = item.get("original") if isinstance(item, dict) else ""
    if isinstance(original, str) and not classify_subtitle_source(original).requires_translation:
        return False
    if not isinstance(result, dict):
        return False
    translation = result.get("translation")
    if isinstance(translation, str) and translation:
        return False
    error = result.get("error") if isinstance(result.get("error"), str) else ""
    if (
        error in {MISSING_ID_ERROR, MISSING_TRANSLATION_ERROR}
        or error.startswith("invalid translation type:")
    ):
        return True
    original = item.get("original") if isinstance(item, dict) else ""
    return bool(
        isinstance(translation, str)
        and translation == ""
        and isinstance(original, str)
        and original.strip()
        and classify_subtitle_source(original).requires_translation
    )


class SubtitleTranslator:
    """Main translation orchestrator with context window support."""

    def __init__(self, config: dict):
        self.config = config
        self.resume_existing = False
        self._kb_usage_trace = {"project": {}, "matches": []}
        trans_cfg = _dict_section(config, "translation")
        api_keys = _dict_section(config, "api_keys")
        providers_cfg = _dict_section(config, "providers")

        self.batch_size = _coerce_int_setting(
            trans_cfg.get("batch_size", 10),
            10,
            min_value=0,
            max_value=200,
        )
        self.context_window = _coerce_int_setting(
            trans_cfg.get("context_window", 3),
            3,
            min_value=0,
            max_value=50,
        )

        # Full-doc mode fires on explicit flag OR when batch_size is 0
        # (historical "no batching" sentinel now reinterpreted as full-doc).
        self.full_doc_mode = (
            _coerce_bool_setting(trans_cfg.get("full_doc_mode", False))
            or self.batch_size == 0
        )
        self.use_translation_memory = _coerce_bool_setting(
            trans_cfg.get("use_translation_memory", True),
            True,
        )
        self.use_phrase_library = _coerce_bool_setting(
            trans_cfg.get("use_phrase_library", True),
            True,
        )
        self.memory_retrieval_backend = _coerce_choice_setting(
            trans_cfg.get("memory_retrieval_backend", "auto"),
            {"auto", "fts5", "ngram"},
            "auto",
        )
        self.phrase_retrieval_backend = _coerce_choice_setting(
            trans_cfg.get("phrase_retrieval_backend", "auto"),
            {"auto", "fts5", "ngram"},
            "auto",
        )
        self.max_memory_examples = _coerce_bounded_int_setting(
            trans_cfg.get("max_memory_examples", 6),
            6,
            min_value=0,
            max_value=20,
        )
        self.max_phrase_examples = _coerce_bounded_int_setting(
            trans_cfg.get("max_phrase_examples", 6),
            6,
            min_value=0,
            max_value=20,
        )
        self.missing_translation_retries = _coerce_bounded_int_setting(
            trans_cfg.get("missing_translation_retries", 2),
            2,
            min_value=0,
            max_value=3,
        )
        self.missing_translation_retry_batch_size = _coerce_bounded_int_setting(
            trans_cfg.get("missing_translation_retry_batch_size", 5),
            5,
            min_value=1,
            max_value=50,
        )
        self.missing_translation_abort_min_blocks = _coerce_bounded_int_setting(
            trans_cfg.get("missing_translation_abort_min_blocks", 200),
            200,
            min_value=0,
            max_value=5000,
        )
        self.missing_translation_abort_missing_pct = _coerce_bounded_int_setting(
            trans_cfg.get("missing_translation_abort_missing_pct", 50),
            50,
            min_value=0,
            max_value=100,
        )
        self.last_quality_trace = TranslationContextTrace()
        self._accumulate_quality_trace = False

        # Primary provider — routed through the factory.
        primary_name = _coerce_provider_name(trans_cfg.get("primary_provider"), "omp_cli")
        primary_model = _coerce_text_setting(
            trans_cfg.get("primary_model"),
            "openai-codex/gpt-6-astra" if primary_name == "omp_cli" else "gpt-4o",
        )
        primary_effort = _coerce_choice_setting(
            trans_cfg.get("primary_effort"),
            {"auto", "off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"},
            "medium" if primary_name == "omp_cli" else "auto",
        )
        primary_config = self._build_provider_config(
            primary_name, primary_model, primary_effort, api_keys, providers_cfg
        )
        self.primary = get_provider(primary_name, primary_config)

        # Polish provider (optional) — same factory path.
        self.polish = None
        polish_name = _coerce_provider_name(
            trans_cfg.get("polish_provider"),
            "",
            allow_empty=True,
        )
        polish_model = _coerce_text_setting(trans_cfg.get("polish_model"), primary_model)
        polish_effort = _coerce_choice_setting(
            trans_cfg.get("polish_effort"),
            {"auto", "off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"},
            "auto",
        )
        if polish_name:
            polish_config = self._build_provider_config(
                polish_name, polish_model, polish_effort, api_keys, providers_cfg
            )
            try:
                self.polish = get_provider(polish_name, polish_config)
            except Exception as e:
                log.warning("Polish provider init failed (%s): %s", polish_name, e)
                self.polish = None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _build_provider_config(
        name: str,
        model: str,
        effort: str,
        api_keys: dict,
        providers_cfg: dict,
    ) -> dict:
        """Compose a provider config dict from the various config sections.

        Local CLI providers own their authentication — they take
        {model, effort, timeout_sec} and explicitly NO api_key. OpenAI-compat providers
        take {provider, model, api_key}.
        """
        if name in ("omp_cli", "claude_cli", "codex_cli"):
            raw_cli = providers_cfg.get(name)
            cli = raw_cli if isinstance(raw_cli, dict) else {}
            return {
                "model": model,
                "effort": effort,
                "timeout_sec": _coerce_int_setting(
                    cli.get("timeout_sec", 180),
                    180,
                    min_value=5,
                    max_value=3600,
                ),
            }
        return {
            "provider": name,
            "model": model,
            "effort": effort,
            "api_key": _coerce_text_setting(api_keys.get(name), ""),
        }

    # --------------------------------------------------------------- public API
    def translate(
        self,
        blocks: List[SubtitleBlock],
        target_lang: str = "简体中文",
        meta_info: Optional[Dict] = None,
        kb_data: Optional[Dict] = None,
        callback: Optional[Callable] = None,
    ) -> List[SubtitleBlock]:
        """Translate all non-filtered blocks.

        Two paths:
          * full-document mode — one call to the primary provider with all
            active blocks, when the provider supports it and the document fits
            within ~80% of its context window.
          * batched mode — the historical windowed-context path.
        """
        # A recovery is a sparse edit. Use contextual batches so retained
        # neighbors remain visible without sending their drafts for replacement.
        from app.engines.entity_registry import registry_for_blocks
        self._document_entity_registry = registry_for_blocks(blocks)
        if self.resume_existing and any(b.translation.strip() for b in blocks):
            return self._translate_batched(blocks, target_lang, meta_info, kb_data, callback)
        if self.full_doc_mode and getattr(self.primary, "supports_full_document_mode", False):
            if self._fits_full_doc(blocks):
                return self._translate_full_document(
                    blocks, target_lang, meta_info, kb_data, callback
                )
            log.info(
                "full_doc fallback to batched: document exceeds safe full-doc "
                "limits (context window=%s, max_items=%s)",
                getattr(self.primary, "context_window_tokens", "?"),
                _provider_full_document_max_items(self.primary) or "unbounded",
            )
        return self._translate_batched(blocks, target_lang, meta_info, kb_data, callback)

    def _needs_translation(self, block) -> bool:
        return (not block.filtered and bool(block.text.strip())
                and classify_subtitle_source(block.text).requires_translation
                and not (self.resume_existing and block.translation.strip()))

    def _quality_trace_for_prompt(self) -> TranslationContextTrace:
        if self._accumulate_quality_trace:
            trace = self.last_quality_trace
            if not isinstance(trace, TranslationContextTrace):
                trace = TranslationContextTrace()
                self.last_quality_trace = trace
            return trace
        trace = TranslationContextTrace()
        self.last_quality_trace = trace
        return trace

    def get_kb_usage_trace(self) -> dict:
        """Return a defensive copy of the latest KB usage trace."""
        trace = self._kb_usage_trace if isinstance(self._kb_usage_trace, dict) else {}
        project = trace.get("project") if isinstance(trace.get("project"), dict) else {}
        matches = trace.get("matches") if isinstance(trace.get("matches"), list) else []
        return {
            "project": dict(project),
            "matches": [dict(match) for match in matches if isinstance(match, dict)],
        }

    # ----------------------------------------------------------- full-doc path
    def _fallback_batch_size(self, blocks: List[SubtitleBlock]) -> int:
        """Compute a batch size to use when falling back from full-doc mode.

        We size batches so each batch's estimated tokens stay under ~40% of
        the provider's context window, bounded to [1, _FULL_DOC_FALLBACK_BATCH_SIZE].
        """
        active = [b for b in blocks if self._needs_translation(b)]
        if not active:
            return _FULL_DOC_FALLBACK_BATCH_SIZE
        window = _provider_context_window(self.primary)
        # Estimate the actual item payload, including bounded read-only windows.
        payload_chars = 0
        for position, block in enumerate(blocks):
            if not self._needs_translation(block):
                continue
            preceding, following = _subtitle_context_window(blocks, position, self.context_window)
            payload_chars += len(json.dumps({
                "id": block.index,
                "original": block.text,
                "preceding_context": preceding,
                "following_context": following,
            }, ensure_ascii=False))
        avg_tokens = max(1, (payload_chars // len(active)) // 2)
        target_tokens = max(1, int(window * 0.4))
        per_batch = max(1, target_tokens // avg_tokens)
        return max(1, min(_FULL_DOC_FALLBACK_BATCH_SIZE, per_batch))

    def _fits_full_doc(self, blocks: List[SubtitleBlock]) -> bool:
        active = [b for b in blocks if self._needs_translation(b)]
        max_items = _provider_full_document_max_items(self.primary)
        if max_items is not None and len(active) > max_items:
            return False
        # Rough token estimate: ~2 chars per token for mixed text.
        est_tokens = sum(len(b.text) for b in active) // 2
        # Every dialogue cue is already a top-level item in full-doc mode.
        # Count only omitted sound evidence, never duplicated dialogue windows.
        est_tokens += sum(
            len(json.dumps(row, ensure_ascii=False))
            for position, block in enumerate(blocks)
            if self._needs_translation(block)
            for side in _subtitle_context_window(
                blocks, position, self.context_window, sound_only=True
            )
            for row in side
        ) // 2
        active_ids = {block.index for block in active}
        discourse_contexts = build_discourse_link_contexts(
            blocks,
            focus_ids=active_ids,
            mutable_ids=active_ids,
        )
        # Each complete link is attached to two endpoint items and rendered
        # once in the prompt. Count all three serialized copies.
        est_tokens += (
            serialized_discourse_link_contexts_chars(discourse_contexts)
            * 3
        ) // 2
        # Add a little overhead for the system prompt and JSON envelope.
        est_tokens += 2000
        window = _provider_context_window(self.primary)
        return est_tokens < int(window * 0.8)

    def _translate_full_document(
        self,
        blocks: List[SubtitleBlock],
        target_lang: str,
        meta_info: Optional[Dict],
        kb_data: Optional[Dict],
        callback: Optional[Callable],
    ) -> List[SubtitleBlock]:
        meta_info = meta_info if isinstance(meta_info, dict) else {}
        kb_data = kb_data if isinstance(kb_data, dict) else {}

        active = [b for b in blocks if self._needs_translation(b)]
        if not active:
            log.warning("No blocks to translate")
            return blocks

        self.last_quality_trace = TranslationContextTrace()
        previous_accumulate = self._accumulate_quality_trace
        self._accumulate_quality_trace = True
        try:
            mutable_ids = {block.index for block in active}
            detected_discourse_links = detect_possessive_echo_links(blocks)
            discourse_contexts = build_discourse_link_contexts(
                blocks,
                focus_ids=mutable_ids,
                mutable_ids=mutable_ids,
                links=detected_discourse_links,
            )
            discourse_contexts_by_endpoint = index_discourse_link_contexts(
                discourse_contexts
            )
            position_by_id = {block.index: position for position, block in enumerate(blocks)}
            items = []
            for block in active:
                item = {"id": block.index, "original": block.text}
                preceding, following = _subtitle_context_window(
                    blocks, position_by_id[block.index], self.context_window, sound_only=True
                )
                if preceding:
                    item["preceding_context"] = preceding
                if following:
                    item["following_context"] = following
                item_discourse_links = discourse_contexts_by_endpoint.get(
                    block.index,
                    [],
                )
                if item_discourse_links:
                    item["discourse_links"] = item_discourse_links
                items.append(item)
            # Reuse the existing batch prompt builder with empty context windows —
            # in full-doc mode every block is visible in the single payload.
            system_prompt = self._build_prompt(target_lang, meta_info, kb_data, [], [], items=items)

            log.info("full_doc translate: %d blocks in one call", len(items))
            if callback:
                callback(5, f"全文翻译中: 1 批次 ({len(items)} 条)")

            raw_results = self.primary.translate_batch(items, system_prompt)
            normalized_results = reconcile_translation_results(
                raw_results if isinstance(raw_results, list) else [],
                items,
            )
            result_map = self._result_map_from_results(normalized_results)
            self._validate_result_map_candidates(
                result_map,
                items,
                target_lang,
            )
            self._retry_missing_primary_results(
                result_map,
                items,
                target_lang,
                meta_info,
                kb_data,
                [],
                [],
                callback=callback,
                progress_pct=90,
            )
            results = self._results_from_map(items, result_map)
        finally:
            self._accumulate_quality_trace = previous_accumulate

        # Optional polish pass over the full doc too.
        if self.polish and results:
            draft_map = {
                str(r.get("id")): r.get("translation", "")
                for r in results
                if isinstance(r, dict) and not r.get("error") and r.get("translation")
            }
            polish_items = [
                {"id": b.index, "original": b.text, "draft": draft_map.get(str(b.index), "")}
                for b in active
                if draft_map.get(str(b.index))
            ]
            if polish_items:
                polish_prompt = self._build_polish_prompt(target_lang, meta_info, kb_data)
                polish_results = self.polish.translate_batch(polish_items, polish_prompt)
                if polish_results:
                    polish_payload = []
                    for r in polish_results:
                        if isinstance(r, dict):
                            if "translation" not in r and "final" in r:
                                r = {**r, "translation": r.get("final")}
                            polish_payload.append(r)
                    normalized_polish = reconcile_translation_results(polish_payload, polish_items)
                    polished_map = {}
                    polish_item_by_id = {
                        str(item["id"]): item
                        for item in polish_items
                    }
                    for r in normalized_polish:
                        pid = str(r.get("id"))
                        ptxt = r.get("translation", "")
                        perr = r.get("error", "")
                        candidate_error = translation_candidate_contract_error(
                            polish_item_by_id.get(pid, {}).get("original", ""),
                            ptxt,
                            target_language=target_lang,
                        )
                        if candidate_error:
                            ptxt = ""
                            perr = candidate_error
                        polished_map[pid] = (ptxt, perr)
                    # Merge polished results into results by id.
                    for r in results:
                        if not isinstance(r, dict):
                            continue
                        rid = str(r.get("id", ""))
                        if rid in polished_map:
                            ptxt, perr = polished_map[rid]
                            if ptxt:
                                r["translation"] = ptxt
                                r["error"] = ""
                            elif perr and not r.get("translation"):
                                r["translation"] = ""
                                r["error"] = perr

        # Apply to `active` (not all `blocks`): results cover only active
        # blocks, so equal counts enable the positional fallback in
        # _apply_results. `active` items are the same objects as in `blocks`.
        self._apply_results(active, results)

        if callback:
            translated_count = sum(1 for b in blocks if b.translation)
            callback(100, f"翻译完成: {translated_count}/{len(active)} 条")
        return blocks

    # ------------------------------------------------------------- batched path
    def _translate_batched(
        self,
        blocks: List[SubtitleBlock],
        target_lang: str,
        meta_info: Optional[Dict],
        kb_data: Optional[Dict],
        callback: Optional[Callable],
    ) -> List[SubtitleBlock]:
        meta_info = meta_info if isinstance(meta_info, dict) else {}
        kb_data = kb_data if isinstance(kb_data, dict) else {}

        # Resolve effective batch_size. Callers may have configured 0 for
        # full-doc mode; if we ended up here we're in fallback and need a
        # safe default rather than a zero-step range(). When falling back
        # from full-doc we also cap the batch size by the provider's context
        # window so very large documents get split into small enough pieces
        # to actually fit.
        effective_batch_size = int(self.batch_size or 0)
        if effective_batch_size <= 0:
            effective_batch_size = self._fallback_batch_size(blocks)

        # Collect translatable blocks
        active_indices = [i for i, b in enumerate(blocks) if self._needs_translation(b)]
        total = len(active_indices)

        if total == 0:
            log.warning("No blocks to translate")
            return blocks

        self.last_quality_trace = TranslationContextTrace()
        previous_accumulate = self._accumulate_quality_trace
        self._accumulate_quality_trace = True
        detected_discourse_links = detect_possessive_echo_links(blocks)

        log.info(
            "Translating %d blocks (batch_size=%d, context=%d)",
            total,
            effective_batch_size,
            self.context_window,
        )

        try:
            # Process in batches
            for batch_start in range(0, total, effective_batch_size):
                batch_end = min(batch_start + effective_batch_size, total)
                batch_indices = active_indices[batch_start:batch_end]

                # Build batch items
                items = []
                mutable_ids = {
                    blocks[ci].index
                    for ci in batch_indices
                }
                discourse_contexts = build_discourse_link_contexts(
                    blocks,
                    focus_ids=mutable_ids,
                    mutable_ids=mutable_ids,
                    links=detected_discourse_links,
                )
                discourse_contexts_by_endpoint = (
                    index_discourse_link_contexts(discourse_contexts)
                )
                for ci in batch_indices:
                    b = blocks[ci]
                    item = {"id": b.index, "original": b.text}
                    item["preceding_context"], item["following_context"] = _subtitle_context_window(
                        blocks, ci, self.context_window
                    )
                    item_discourse_links = (
                        discourse_contexts_by_endpoint.get(b.index, [])
                    )
                    if item_discourse_links:
                        item["discourse_links"] = item_discourse_links
                    items.append(item)

                # Build system prompt
                system_prompt = self._build_prompt(
                    target_lang, meta_info, kb_data, [], [], items=items
                )

                # Primary translation
                if callback:
                    pct = int((batch_start / total) * 100)
                    callback(
                        pct,
                        f"翻译中: 批次 {batch_start // effective_batch_size + 1}/"
                        f"{(total + effective_batch_size - 1) // effective_batch_size}",
                    )

                results = self.primary.translate_batch(items, system_prompt)
                normalized_results = reconcile_translation_results(
                    results if isinstance(results, list) else [],
                    items,
                )
                result_map = self._result_map_from_results(normalized_results)
                self._validate_result_map_candidates(
                    result_map,
                    items,
                    target_lang,
                )
                self._retry_missing_primary_results(
                    result_map,
                    items,
                    target_lang,
                    meta_info,
                    kb_data,
                    [],
                    [],
                    callback=callback,
                    progress_pct=int((batch_start / total) * 100),
                )

                # Polish pass (optional) — only polish entries with a non-empty draft.
                if self.polish and result_map:
                    polish_items = []
                    for ci in batch_indices:
                        b = blocks[ci]
                        entry = result_map.get(str(b.index), {})
                        draft = entry.get("translation", "")
                        if draft:
                            polish_items.append({"id": b.index, "original": b.text, "draft": draft})

                    if polish_items:
                        polish_prompt = self._build_polish_prompt(target_lang, meta_info, kb_data)
                        polish_results = self.polish.translate_batch(polish_items, polish_prompt)
                        if polish_results:
                            polish_payload = []
                            for r in polish_results:
                                if isinstance(r, dict):
                                    if "translation" not in r and "final" in r:
                                        r = {**r, "translation": r.get("final")}
                                    polish_payload.append(r)
                            for r in reconcile_translation_results(polish_payload, polish_items):
                                rid = str(r.get("id", ""))
                                polished = r.get("translation", "")
                                perr = r.get("error", "")
                                polish_item = next(
                                    (
                                        item
                                        for item in polish_items
                                        if str(item.get("id", "")) == rid
                                    ),
                                    {},
                                )
                                candidate_error = (
                                    translation_candidate_contract_error(
                                        polish_item.get("original", ""),
                                        polished,
                                        target_language=target_lang,
                                    )
                                )
                                if candidate_error:
                                    polished = ""
                                    perr = candidate_error
                                if polished:
                                    # Polish succeeded — overwrite draft, clear any prior error.
                                    result_map[rid] = {"translation": polished, "error": ""}
                                elif perr and rid in result_map and not result_map[rid].get("translation"):
                                    # Polish failed AND primary had no draft — record polish error.
                                    result_map[rid] = {"translation": "", "error": perr}
                        self._validate_result_map_candidates(
                            result_map,
                            items,
                            target_lang,
                        )

                # Apply results to this batch's blocks.
                batch_blocks = [blocks[ci] for ci in batch_indices]
                self._apply_results(batch_blocks, self._results_from_map(items, result_map))

                processed_blocks = batch_end
                translated_processed = sum(1 for ci in active_indices[:batch_end] if blocks[ci].translation)
                missing_processed = processed_blocks - translated_processed
                if (
                    self.missing_translation_abort_min_blocks > 0
                    and processed_blocks >= self.missing_translation_abort_min_blocks
                    and self.missing_translation_abort_missing_pct < 100
                    and missing_processed * 100 >= processed_blocks * self.missing_translation_abort_missing_pct
                ):
                    raise RuntimeError(
                        "翻译服务返回大量空结果: "
                        f"{translated_processed}/{processed_blocks} 条成功，"
                        f"{missing_processed} 条缺失，已提前停止"
                    )

                # Report progress AFTER the batch completes (the pre-batch callback
                # above reflects work already done and doubles as the cancel
                # checkpoint; this one advances the bar as each batch finishes).
                if callback:
                    callback(int((batch_end / total) * 100), f"翻译中: {batch_end}/{total} 条")
        finally:
            self._accumulate_quality_trace = previous_accumulate

        if callback:
            translated_count = sum(1 for b in blocks if b.translation)
            callback(100, f"翻译完成: {translated_count}/{total} 条")

        return blocks

    @staticmethod
    def _result_map_from_results(results: List[Dict]) -> Dict[str, Dict[str, str]]:
        result_map: Dict[str, Dict[str, str]] = {}
        for r in results or []:
            if not isinstance(r, dict):
                continue
            rid = str(r.get("id", ""))
            result_map[rid] = {
                "translation": r.get("translation", "") if isinstance(r.get("translation", ""), str) else "",
                "error": r.get("error", "") if isinstance(r.get("error", ""), str) else "",
            }
        return result_map

    @staticmethod
    def _results_from_map(items: List[Dict], result_map: Dict[str, Dict[str, str]]) -> List[Dict]:
        return [
            {
                "id": item.get("id"),
                "translation": result_map.get(str(item.get("id")), {}).get("translation", ""),
                "error": result_map.get(str(item.get("id")), {}).get("error", ""),
            }
            for item in items
        ]

    def _retry_missing_primary_results(
        self,
        result_map: Dict[str, Dict[str, str]],
        items: List[Dict],
        target_lang: str,
        meta_info: Dict,
        kb_data: Dict,
        context_before: List[Dict],
        context_after: List[str],
        *,
        callback: Optional[Callable] = None,
        progress_pct: int = 0,
    ) -> None:
        if self.missing_translation_retries <= 0:
            return
        for round_index in range(self.missing_translation_retries):
            retry_items = [
                item for item in items
                if _is_retryable_translation_result(result_map.get(str(item.get("id")), {}), item)
            ]
            if not retry_items:
                return
            log.info(
                "retrying %d missing/invalid translation result(s), round %d/%d",
                len(retry_items),
                round_index + 1,
                self.missing_translation_retries,
            )
            if callback:
                callback(
                    progress_pct,
                    f"补翻缺失: 第 {round_index + 1}/{self.missing_translation_retries} 轮 "
                    f"({len(retry_items)} 条)",
                )
            for start in range(0, len(retry_items), self.missing_translation_retry_batch_size):
                retry_batch = retry_items[start:start + self.missing_translation_retry_batch_size]
                retry_prompt = self._build_prompt(
                    target_lang,
                    meta_info,
                    kb_data,
                    context_before,
                    context_after,
                    items=retry_batch,
                )
                retry_prompt = f"{retry_prompt}\n\n{_MISSING_TRANSLATION_RETRY_NOTE}"
                raw_retry_results = self.primary.translate_batch(retry_batch, retry_prompt)
                normalized_retry_results = reconcile_translation_results(
                    raw_retry_results if isinstance(raw_retry_results, list) else [],
                    retry_batch,
                )
                retry_result_map = self._result_map_from_results(
                    normalized_retry_results
                )
                self._validate_result_map_candidates(
                    retry_result_map,
                    retry_batch,
                    target_lang,
                )
                for retry_item in retry_batch:
                    rid = str(retry_item.get("id", ""))
                    result = retry_result_map.get(rid, {})
                    current = result_map.get(rid, {})
                    if current.get("translation"):
                        continue
                    result_map[rid] = {
                        "translation": (
                            result.get("translation", "")
                            if isinstance(result.get("translation", ""), str)
                            else ""
                        ),
                        "error": (
                            result.get("error", "")
                            if isinstance(result.get("error", ""), str)
                            else ""
                        ),
                    }

    @staticmethod
    def _validate_result_map_candidates(
        result_map: Dict[str, Dict[str, str]],
        items: List[Dict],
        target_lang: str,
    ) -> None:
        item_by_id = {
            str(item.get("id")): item
            for item in items
            if isinstance(item, dict)
        }
        for rid, result in result_map.items():
            if not isinstance(result, dict):
                continue
            translation = result.get("translation", "")
            if not isinstance(translation, str) or not translation:
                continue
            item = item_by_id.get(rid, {})
            error = translation_candidate_contract_error(
                item.get("original", ""),
                translation,
                target_language=target_lang,
            )
            if error:
                result["translation"] = ""
                result["error"] = error

    # -------------------------------------------------------------- result apply
    @staticmethod
    def _apply_one(b: SubtitleBlock, r: Dict) -> None:
        """Apply a single result dict to a block.

        Respects the B3 error field: if error present and translation empty,
        store translation_error and leave translation "" (do NOT treat as
        successfully translated to empty string).
        """
        err = r.get("error") if isinstance(r.get("error"), str) else ""
        if "translation" not in r:
            trans = ""
            err = err or MISSING_TRANSLATION_ERROR
        else:
            raw = r.get("translation")
            if isinstance(raw, str):
                trans = raw
            else:
                trans = ""
                err = err or f"invalid translation type: {type(raw).__name__}"
        if err and not trans:
            b.translation = ""
            b.translation_error = err
        else:
            b.translation = trans
            b.translation_error = ""

    def _apply_results(self, blocks: List[SubtitleBlock], results: List[Dict]) -> None:
        """Apply translator results to matching blocks, keyed by subtitle id.

        If NOT ONE result id matches any block but the counts are equal, the
        model likely renumbered the ids — fall back to applying results
        positionally rather than silently dropping the whole batch. Results
        whose id matches no block are logged so dropped translations are
        visible instead of silent.
        """
        if not results:
            return
        valid = [r for r in results if isinstance(r, dict)]
        if not valid:
            return
        by_index = {str(b.index): b for b in blocks}
        matched = 0
        unmatched = 0
        for r in valid:
            b = by_index.get(str(r.get("id", "")))
            if b is None:
                unmatched += 1
                continue
            matched += 1
            self._apply_one(b, r)
        if matched == 0 and len(valid) == len(blocks):
            log.warning(
                "_apply_results: no result id matched any block; applying %d "
                "results positionally (model likely renumbered ids)", len(blocks)
            )
            for b, r in zip(blocks, valid):
                self._apply_one(b, r)
        elif unmatched:
            log.warning(
                "_apply_results: %d result(s) had an id matching no block", unmatched
            )

    # ---------------------------------------------------------------- prompts
    def _build_prompt(
        self, target_lang: str, meta_info: Dict, kb_data: Optional[Dict],
        context_before: List[Dict], context_after: List[str],
        items: Optional[List[Dict]] = None,
    ) -> str:
        """Build translation system prompt with full context."""
        meta_info = meta_info if isinstance(meta_info, dict) else {}
        kb_data = kb_data if isinstance(kb_data, dict) else {}
        parts = [
            f"你是一位精通{target_lang}的专业字幕翻译。请将以下字幕翻译为{target_lang}。",
            "",
        ]
        from app.engines.entity_registry import entity_context_json, ENTITY_CONTEXT_RULE
        context_source = "\n".join(
            str(row.get("original", ""))
            for item in items or []
            for row in [item, *item.get("preceding_context", []), *item.get("following_context", [])]
        )
        entity_context = entity_context_json(
            getattr(self, "_document_entity_registry", []), relevant_source=context_source
        )
        if entity_context:
            parts.extend([ENTITY_CONTEXT_RULE, entity_context])

        # Meta info
        if meta_info.get("plot"):
            parts.append(f"剧情背景: {meta_info['plot']}")
        cast = meta_info.get("cast")
        if isinstance(cast, list):
            cast_items = [c.strip() for c in cast if isinstance(c, str) and c.strip()]
            cast_str = ", ".join(cast_items[:5])
        else:
            cast_str = ""
        if cast_str:
            parts.append(f"角色: {cast_str}")

        memory_snippet, phrase_snippet = self._build_retrieval_snippets(
            target_lang,
            meta_info,
            items or [],
        )
        if memory_snippet:
            parts.append(memory_snippet)

        # v2 KB injection: select by project metadata + inject as hard constraints.
        # Falls back to legacy kb_data only when v2 produces no snippet.
        kb_snippet = ""
        project_kb = None
        try:
            project_kb = project_knowledge(meta_info, _shared_kb)
            self._kb_usage_trace = trace_for_project_kb(project_kb)
            if project_kb is not None:
                kb_snippet = _kb_build_snippet(project_kb)
        except Exception as _e:  # pragma: no cover — defensive
            log.warning("KB v2 injection failed: %s", _e)
            kb_snippet = ""
            self._kb_usage_trace = trace_for_project_kb(None)

        if kb_snippet:
            parts.append(kb_snippet)
        elif kb_data:
            # Legacy fallback — preserve pre-v2 behavior when v2 KB is empty
            # but caller still supplies old-shape kb_data (style/terms dict).
            legacy_style = kb_data.get("style") or ""
            legacy_terms = kb_data.get("terms") or {}
            if legacy_style:
                parts.append(f"翻译风格: {legacy_style}")
            if legacy_terms:
                terms_str = json.dumps(legacy_terms, ensure_ascii=False)
                parts.append(f"术语表(严格遵守): {terms_str}")

        candidate_snippet, candidate_hits = _build_auto_kb_candidate_snippet(kb_data)
        if candidate_snippet:
            parts.append(candidate_snippet)
            _extend_unique_trace_hits(self.last_quality_trace.kb_hits, candidate_hits)

        metadata_snippet, metadata_hits = build_project_metadata_prompt_snippet(meta_info)
        if metadata_snippet:
            parts.append(metadata_snippet)
            _extend_unique_trace_hits(self.last_quality_trace.kb_hits, metadata_hits)

        domain_snippet, domain_hits = self._build_domain_terminology_snippet(
            items or [],
            project_kb,
            meta_info,
        )
        if domain_snippet:
            parts.append(domain_snippet)
            _extend_unique_trace_hits(self.last_quality_trace.kb_hits, domain_hits)

        style_snippet, style_hits = build_subtitle_style_prompt_snippet(target_lang, meta_info)
        if style_snippet:
            parts.append(style_snippet)
            _extend_unique_trace_hits(self.last_quality_trace.style_hits, style_hits)

        profile_snippet, profile_hits = build_content_profile_prompt_snippet(meta_info)
        if profile_snippet:
            parts.append(profile_snippet)
            _extend_unique_trace_hits(self.last_quality_trace.profile_hits, profile_hits)

        if phrase_snippet:
            parts.append(phrase_snippet)

        self.last_quality_trace.conflict_hits = collect_terminology_conflicts(
            project_kb=project_kb,
            trace=self.last_quality_trace.to_dict(),
        )

        # Context window
        if context_before:
            parts.append("\n上文及已有译稿(只读参考,可能尚未翻译):")
            for ctx in context_before[-self.context_window:]:
                parts.append(f"  原文: {ctx['original']}")
                parts.append(f"  译文: {ctx['translated']}")

        if context_after:
            parts.append("\n即将出现的下文(供参考):")
            for txt in context_after:
                parts.append(f"  {txt}")

        discourse_links = []
        seen_link_hashes = set()
        for item in items or []:
            for link in item.get("discourse_links", []):
                link_hash = link.get("link_hash")
                if not isinstance(link_hash, str) or link_hash in seen_link_hashes:
                    continue
                seen_link_hashes.add(link_hash)
                discourse_links.append(link)
        if discourse_links:
            parts.append(
                "\n局部话语链接（只用于当前批次消歧，不是术语表，"
                "不得创建全局译名或知识库命中）:"
            )
            for link in discourse_links:
                antecedent = link["antecedent"]
                echo = link["echo"]
                parts.append(
                    f"  {link['link_hash']} | "
                    f"#{antecedent['id']} 原文: {antecedent['original']} | "
                    f"当前译文: {antecedent['draft']}"
                )
                for bridge in link.get("bridge_context", []):
                    parts.append(
                        f"  只读 bridge #{bridge['id']}: "
                        f"{bridge['original']} | 当前译文: {bridge['draft']}"
                    )
                parts.append(
                    f"  echo #{echo['id']}: {echo['original']}；"
                    f"与 #{antecedent['id']} 指向同一局部对象，"
                    "只保持本处所有格关系，不要推广 noun 的全局译法。"
                )
                parts.append(
                    "  只读 id: "
                    + ", ".join(
                        f"#{block_id}"
                        for block_id in link.get("read_only_ids", [])
                    )
                )

        # Output rules
        parts.extend([
            "",
            "翻译规则:",
            "1. 仅输出JSON数组,格式: [{\"id\": N, \"translation\": \"译文\"}];"
            "id 必须原样照抄输入条目的 id,不得重新编号;每个输入条目都必须有且仅有一个对应输出",
            "2. 保持译文简洁自然,符合字幕表达习惯",
            "3. 不要保留原文语言,完全翻译为目标语言",
            "4. 已确认的纯音效已由程序排除。每个输入 id 必须返回非空译文；未知括号内容保留并翻译，混合内容必须保留对白和歌词。",
            "5. 保持上下文语气连贯",
            "   preceding_context/following_context 是只读的有界源译上下文，只翻译顶层输入 id；"
            "上下文 id 不得另行输出。带 truncated 标记的文本并不完整，不得据缺失部分推断语义。",
            "   连续字幕须逐条拼接后仍连贯；相邻音效/动作描述可用于区分 Cheers 等多义对白，"
            "但不必写进译文。原文省略的宾语、人称和性别没有明确上下文依据时不得擅自补出。",
            "6. 删除音乐装饰符号,不要输出 ♪、♫、♬、🎵、🎶",
            f"7. {_SPEAKER_LINE_PROMPT_RULE}",
            "8. 项目知识库和上下文选中的审定术语是硬约束；同一专名、地点或领域术语重复出现时必须使用同一译法",
            "9. 不要添加任何解释,只输出JSON",
        ])

        return "\n".join(parts)

    @staticmethod
    def _build_domain_terminology_snippet(
        items: List[Dict],
        project_kb,
        meta_info: Optional[Dict] = None,
    ) -> tuple[str, list[dict]]:
        texts = [
            item.get("original", "")
            for item in items
            if isinstance(item, dict) and isinstance(item.get("original"), str)
        ]
        curated_matches = find_domain_terms_in_texts(texts)
        curated_snippet, curated_hits = build_domain_prompt_snippet(curated_matches, project_kb)
        auto_snippet = ""
        auto_hits: list[dict] = []
        if not _has_technical_tutorial_profile(meta_info):
            auto_matches = find_scientific_terms_in_texts(texts)
            auto_snippet, auto_hits = build_auto_scientific_prompt_snippet(auto_matches, project_kb)
        snippets = [snippet for snippet in (curated_snippet, auto_snippet) if snippet]
        return "\n".join(snippets), [*curated_hits, *auto_hits]

    def _build_retrieval_snippets(
        self,
        target_lang: str,
        meta_info: Dict,
        items: List[Dict],
    ) -> tuple[str, str]:
        trace = self._quality_trace_for_prompt()
        if not items:
            return "", ""

        source_lang = _memory_lang(meta_info.get("original_language"), "en")
        target_code = _memory_lang(target_lang, "zh-CN")

        memory_lines = []
        if self.use_translation_memory and self.max_memory_examples > 0:
            seen_memory = set()
            per_item_limit = min(20, self.max_memory_examples)
            try:
                store = TranslationMemoryStore()
                for item in items:
                    original = item.get("original") if isinstance(item, dict) else ""
                    if not isinstance(original, str) or not original.strip():
                        continue
                    for hit in store.retrieve(
                        original,
                        source_language=source_lang,
                        target_language=target_code,
                        limit=per_item_limit,
                        backend=self.memory_retrieval_backend,
                    ):
                        key = (hit.source_text, hit.final_translation)
                        if key in seen_memory:
                            continue
                        seen_memory.add(key)
                        _append_unique_trace_hit(trace.memory_hits, {
                            "source_text": hit.source_text,
                            "final_translation": hit.final_translation,
                            "project_name": hit.project_name,
                            "score": hit.score,
                        })
                        memory_lines.append(
                            f"  - Original: {hit.source_text}\n"
                            f"    Previous machine translation: {hit.machine_translation}\n"
                            f"    User-approved translation: {hit.final_translation}"
                        )
                        if len(memory_lines) >= self.max_memory_examples:
                            break
                    if len(memory_lines) >= self.max_memory_examples:
                        break
            except Exception as e:
                log.warning("translation memory retrieval failed: %s", e)

        phrase_lines = []
        if self.use_phrase_library and self.max_phrase_examples > 0:
            seen_phrases = set()
            preferred_tags = _phrase_context_tags(meta_info)
            allow_adult_phrases = _allows_legal_adult_phrase_examples(meta_info)
            per_item_limit = min(20, self.max_phrase_examples)
            try:
                library = PhraseLibrary()
                for item in items:
                    original = item.get("original") if isinstance(item, dict) else ""
                    if not isinstance(original, str) or not original.strip():
                        continue
                    for hit in library.retrieve(
                        original,
                        source_language=source_lang,
                        target_language=target_code,
                        limit=per_item_limit,
                        preferred_tags=preferred_tags,
                        backend=self.phrase_retrieval_backend,
                    ):
                        if _is_legal_adult_phrase_hit(hit) and not allow_adult_phrases:
                            continue
                        key = (hit.source_text, hit.target_text)
                        if key in seen_phrases:
                            continue
                        seen_phrases.add(key)
                        _append_unique_trace_hit(trace.phrase_hits, {
                            "source_text": hit.source_text,
                            "target_text": hit.target_text,
                            "source_name": hit.source_name,
                            "license": hit.license,
                            "pack_id": hit.pack_id,
                            "tags": hit.tags,
                            "score": hit.score,
                        })
                        tag_text = f", tags: {hit.tags}" if hit.tags else ""
                        phrase_lines.append(
                            f"  - {hit.source_text} -> {hit.target_text}"
                            f"  (source: {hit.source_name or 'local'}, "
                            f"license: {hit.license or 'unspecified'}{tag_text})"
                        )
                        if len(phrase_lines) >= self.max_phrase_examples:
                            break
                    if len(phrase_lines) >= self.max_phrase_examples:
                        break
            except Exception as e:
                log.warning("phrase library retrieval failed: %s", e)

        memory_snippet = ""
        if memory_lines:
            memory_snippet = "\n".join([
                "User correction memory (highest priority, follow these user-approved rewrites when relevant):",
                *memory_lines,
            ])

        phrase_snippet = ""
        if phrase_lines:
            phrase_snippet = "\n".join([
                "Subtitle phrase examples (lower priority than project KB; use for natural phrasing only):",
                *phrase_lines,
            ])
        return memory_snippet, phrase_snippet

    def _build_polish_prompt(
        self,
        target_lang: str,
        meta_info: Optional[Dict] = None,
        kb_data: Optional[Dict] = None,
    ) -> str:
        """Build polish/refinement prompt.

        Accepts `meta_info` (new) so v2 KB selection can be performed. The
        legacy 2-arg form ``_build_polish_prompt(target_lang, kb_data)`` is
        still supported — when the second positional argument looks like a
        legacy kb_data dict (has "style" or "terms" keys), it is treated as
        kb_data with meta_info defaulted to None.
        """
        # Backward-compat shim: callers passing `(target_lang, kb_data)`
        # positionally land with kb_data in the `meta_info` slot. Detect
        # the legacy shape and shuffle.
        if kb_data is None and isinstance(meta_info, dict) and (
            "style" in meta_info or "terms" in meta_info
        ) and not (
            "name" in meta_info or "tmdb_id" in meta_info
            or "plot" in meta_info or "cast" in meta_info
        ):
            kb_data = meta_info
            meta_info = None
        meta_info = meta_info if isinstance(meta_info, dict) else {}
        kb_data = kb_data if isinstance(kb_data, dict) else {}

        parts = [
            f"你是{target_lang}字幕润色专家。请润色以下字幕翻译草稿。",
            "每条包含原文(original)和初稿(draft),请输出最终润色版本。",
            "",
        ]

        # v2 KB injection — same contract as _build_prompt
        kb_snippet = ""
        try:
            project_kb = project_knowledge(meta_info, _shared_kb)
            self._kb_usage_trace = trace_for_project_kb(project_kb)
            if project_kb is not None:
                kb_snippet = _kb_build_snippet(project_kb)
        except Exception as _e:  # pragma: no cover — defensive
            log.warning("KB v2 injection failed (polish): %s", _e)
            kb_snippet = ""
            self._kb_usage_trace = trace_for_project_kb(None)

        if kb_snippet:
            parts.append(kb_snippet)
        elif kb_data:
            if kb_data.get("style"):
                parts.append(f"风格要求: {kb_data['style']}")
            if kb_data.get("terms"):
                parts.append(f"术语表: {json.dumps(kb_data['terms'], ensure_ascii=False)}")
        candidate_snippet, _candidate_hits = _build_auto_kb_candidate_snippet(kb_data)
        if candidate_snippet:
            parts.append(candidate_snippet)
        parts.extend([
            "",
            "规则:",
            "1. 输出JSON数组: [{\"id\": N, \"translation\": \"润色后译文\"}];"
            "id 必须原样照抄输入条目的 id,不得重新编号或省略任何条目",
            "2. 修正不自然的表达,使其更流畅",
            "3. 确保项目知识库和上下文选中的审定术语统一；不得改写已指定的专名、地点或领域术语",
            f"4. {_SPEAKER_LINE_PROMPT_RULE}",
            "5. 只输出JSON,不要解释",
        ])
        return "\n".join(parts)
