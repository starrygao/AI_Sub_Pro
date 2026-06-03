"""
Multi-model subtitle translation engine with context window support.
Uses OpenAI SDK for OpenAI-compat providers and subprocess for local CLI providers.
Provider construction is routed through the Phase 2 provider factory.
"""
import json
import logging
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
    MISSING_TRANSLATION_ERROR,
    reconcile_translation_results,
)
from app.engines.kb_trace import trace_for_project_kb

log = logging.getLogger(__name__)

# KB v2 singleton (loaded once at translator module import). Tests may
# monkey-patch `_shared_kb` to inject a controlled KnowledgeBase instance.
from app.engines.knowledge import KnowledgeBase, build_prompt_snippet as _kb_build_snippet

_shared_kb = KnowledgeBase()
try:
    _shared_kb.load()
except Exception as _e:  # pragma: no cover — best-effort load
    log.warning("KB load failed at translator import: %s", _e)

# Fallback batch size used when batch_size is configured as 0 (full-doc mode)
# but we need to fall back to the batched path (e.g. document too large for
# the primary provider's context window).
_FULL_DOC_FALLBACK_BATCH_SIZE = 10


def _provider_context_window(provider, default: int = 32_000) -> int:
    raw = getattr(provider, "context_window_tokens", default) or default
    if isinstance(raw, bool):
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


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


def _dict_section(config: dict, key: str) -> dict:
    value = config.get(key, {}) if isinstance(config, dict) else {}
    return value if isinstance(value, dict) else {}


def _coerce_text_setting(value, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value or default


def _coerce_provider_name(value, default: str = "openai", *, allow_empty: bool = False) -> str:
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


class SubtitleTranslator:
    """Main translation orchestrator with context window support."""

    def __init__(self, config: dict):
        self.config = config
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

        # Primary provider — routed through the factory.
        primary_name = _coerce_provider_name(trans_cfg.get("primary_provider"), "openai")
        primary_model = _coerce_text_setting(trans_cfg.get("primary_model"), "gpt-4o")
        primary_config = self._build_provider_config(
            primary_name, primary_model, api_keys, providers_cfg
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
        if polish_name:
            polish_config = self._build_provider_config(
                polish_name, polish_model, api_keys, providers_cfg
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
        fallback_model: str,
        api_keys: dict,
        providers_cfg: dict,
    ) -> dict:
        """Compose a provider config dict from the various config sections.

        Local CLI providers are subscription-auth subprocess providers — they take
        {model, timeout_sec} and explicitly NO api_key. OpenAI-compat providers
        take {provider, model, api_key}.
        """
        if name in ("claude_cli", "codex_cli"):
            raw_cli = providers_cfg.get(name)
            cli = raw_cli if isinstance(raw_cli, dict) else {}
            return {
                "model": _coerce_text_setting(cli.get("model"), fallback_model),
                "timeout_sec": _coerce_int_setting(
                    cli.get("timeout_sec", 180),
                    180,
                    min_value=5,
                    max_value=3600,
                ),
            }
        return {
            "provider": name,
            "model": fallback_model,
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
        if self.full_doc_mode and getattr(self.primary, "supports_full_document_mode", False):
            if self._fits_full_doc(blocks):
                return self._translate_full_document(
                    blocks, target_lang, meta_info, kb_data, callback
                )
            log.info(
                "full_doc fallback to batched: estimated tokens exceed 80%% of "
                "context window (%s)",
                getattr(self.primary, "context_window_tokens", "?"),
            )
        return self._translate_batched(blocks, target_lang, meta_info, kb_data, callback)

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
        active = [b for b in blocks if not b.filtered and b.text.strip()]
        if not active:
            return _FULL_DOC_FALLBACK_BATCH_SIZE
        window = _provider_context_window(self.primary)
        # Mean chars per block -> approximate tokens per block (2 chars/token).
        avg_tokens = max(1, (sum(len(b.text) for b in active) // len(active)) // 2)
        target_tokens = max(1, int(window * 0.4))
        per_batch = max(1, target_tokens // avg_tokens)
        return max(1, min(_FULL_DOC_FALLBACK_BATCH_SIZE, per_batch))

    def _fits_full_doc(self, blocks: List[SubtitleBlock]) -> bool:
        active = [b for b in blocks if not b.filtered and b.text.strip()]
        # Rough token estimate: ~2 chars per token for mixed text.
        est_tokens = sum(len(b.text) for b in active) // 2
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

        active = [b for b in blocks if not b.filtered and b.text.strip()]
        if not active:
            log.warning("No blocks to translate")
            return blocks

        items = [{"id": b.index, "original": b.text} for b in active]
        # Reuse the existing batch prompt builder with empty context windows —
        # in full-doc mode every block is visible in the single payload.
        system_prompt = self._build_prompt(target_lang, meta_info, kb_data, [], [])

        log.info("full_doc translate: %d blocks in one call", len(items))
        if callback:
            callback(5, f"全文翻译中: 1 批次 ({len(items)} 条)")

        raw_results = self.primary.translate_batch(items, system_prompt)
        results = reconcile_translation_results(
            raw_results if isinstance(raw_results, list) else [],
            items,
        )

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
                    for r in normalized_polish:
                        pid = str(r.get("id"))
                        ptxt = r.get("translation", "")
                        perr = r.get("error", "")
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
        active_indices = [i for i, b in enumerate(blocks) if not b.filtered and b.text.strip()]
        total = len(active_indices)

        if total == 0:
            log.warning("No blocks to translate")
            return blocks

        log.info(
            "Translating %d blocks (batch_size=%d, context=%d)",
            total,
            effective_batch_size,
            self.context_window,
        )

        # Process in batches
        for batch_start in range(0, total, effective_batch_size):
            batch_end = min(batch_start + effective_batch_size, total)
            batch_indices = active_indices[batch_start:batch_end]

            # Build context
            context_before = []
            if batch_start > 0:
                ctx_start = max(0, batch_start - self.context_window)
                for ci in active_indices[ctx_start:batch_start]:
                    b = blocks[ci]
                    if b.translation:
                        context_before.append({"original": b.text, "translated": b.translation})

            context_after = []
            if batch_end < total:
                ctx_end = min(total, batch_end + self.context_window)
                for ci in active_indices[batch_end:ctx_end]:
                    context_after.append(blocks[ci].text)

            # Build batch items
            items = []
            for ci in batch_indices:
                b = blocks[ci]
                items.append({"id": b.index, "original": b.text})

            # Build system prompt
            system_prompt = self._build_prompt(
                target_lang, meta_info, kb_data, context_before, context_after
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
            # Map id -> (translation, error). Error is propagated from B3 error items.
            result_map: Dict[str, Dict[str, str]] = {}
            for r in normalized_results:
                rid = str(r.get("id", ""))
                result_map[rid] = {
                    "translation": r.get("translation", ""),
                    "error": r.get("error", ""),
                }

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
                            if polished:
                                # Polish succeeded — overwrite draft, clear any prior error.
                                result_map[rid] = {"translation": polished, "error": ""}
                            elif perr and rid in result_map and not result_map[rid].get("translation"):
                                # Polish failed AND primary had no draft — record polish error.
                                result_map[rid] = {"translation": "", "error": perr}

            # Apply results to this batch's blocks.
            batch_blocks = [blocks[ci] for ci in batch_indices]
            # Flatten result_map back to a list for _apply_results().
            flat_results = [
                {"id": bid, "translation": v.get("translation", ""), "error": v.get("error", "")}
                for bid, v in result_map.items()
            ]
            self._apply_results(batch_blocks, flat_results)

            # Report progress AFTER the batch completes (the pre-batch callback
            # above reflects work already done and doubles as the cancel
            # checkpoint; this one advances the bar as each batch finishes).
            if callback:
                callback(int((batch_end / total) * 100), f"翻译中: {batch_end}/{total} 条")

        if callback:
            translated_count = sum(1 for b in blocks if b.translation)
            callback(100, f"翻译完成: {translated_count}/{total} 条")

        return blocks

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
    ) -> str:
        """Build translation system prompt with full context."""
        meta_info = meta_info if isinstance(meta_info, dict) else {}
        kb_data = kb_data if isinstance(kb_data, dict) else {}
        parts = [
            f"你是一位精通{target_lang}的专业字幕翻译。请将以下字幕翻译为{target_lang}。",
            "",
        ]

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

        # v2 KB injection: select by project metadata + inject as hard constraints.
        # Falls back to legacy kb_data only when v2 produces no snippet.
        kb_snippet = ""
        try:
            project_kb = _shared_kb.select_for_project(meta_info)
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

        # Context window
        if context_before:
            parts.append("\n已翻译的上文(供参考,保持连贯):")
            for ctx in context_before[-self.context_window:]:
                parts.append(f"  原文: {ctx['original']}")
                parts.append(f"  译文: {ctx['translated']}")

        if context_after:
            parts.append("\n即将出现的下文(供参考):")
            for txt in context_after:
                parts.append(f"  {txt}")

        # Output rules
        parts.extend([
            "",
            "翻译规则:",
            "1. 仅输出JSON数组,格式: [{\"id\": N, \"translation\": \"译文\"}];"
            "id 必须原样照抄输入条目的 id,不得重新编号;每个输入条目都必须有且仅有一个对应输出",
            "2. 保持译文简洁自然,符合字幕表达习惯",
            "3. 不要保留原文语言,完全翻译为目标语言",
            "4. [sound]等环境音标记不翻译,留空",
            "5. 保持上下文语气连贯",
            "6. 不要添加任何解释,只输出JSON",
        ])

        return "\n".join(parts)

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
            project_kb = _shared_kb.select_for_project(meta_info)
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
        parts.extend([
            "",
            "规则:",
            "1. 输出JSON数组: [{\"id\": N, \"translation\": \"润色后译文\"}];"
            "id 必须原样照抄输入条目的 id,不得重新编号或省略任何条目",
            "2. 修正不自然的表达,使其更流畅",
            "3. 确保术语统一",
            "4. 只输出JSON,不要解释",
        ])
        return "\n".join(parts)
