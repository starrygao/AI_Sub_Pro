"""Shared normalization contract for provider translation results."""
from typing import Dict, List

from app.utils.errors import redact_error_message

MISSING_ID_ERROR = "missing in model response"
MISSING_TRANSLATION_ERROR = "missing translation in model response"


def reconcile_translation_results(parsed_list: List[Dict], items: List[Dict]) -> List[Dict]:
    """Return exactly one normalized result per input item.

    Providers can receive model output in slightly different wrappers, but once
    a JSON list is available the downstream contract is the same: match by id,
    preserve intentional empty-string translations, and surface malformed
    values as explicit per-block errors.
    """
    by_id = {str(r.get("id")): r for r in parsed_list if isinstance(r, dict)}
    out: List[Dict] = []
    for it in items:
        item_id = it.get("id")
        r = by_id.get(str(item_id))
        if r is None:
            out.append({"id": item_id, "translation": "", "error": MISSING_ID_ERROR})
            continue

        if "translation" not in r:
            out.append({"id": item_id, "translation": "", "error": MISSING_TRANSLATION_ERROR})
            continue

        value = r["translation"]
        provided_error = r.get("error") if isinstance(r.get("error"), str) else ""
        if isinstance(value, str):
            out.append({
                "id": item_id,
                "translation": value,
                "error": provided_error if not value else "",
            })
        else:
            out.append({
                "id": item_id,
                "translation": "",
                "error": f"invalid translation type: {type(value).__name__}",
            })
    return out
