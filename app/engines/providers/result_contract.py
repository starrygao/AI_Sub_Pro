"""Shared normalization contract for provider translation results."""
from typing import Dict, List

from app.utils.errors import redact_error_message

MISSING_ID_ERROR = "missing in model response"
MISSING_TRANSLATION_ERROR = "missing translation in model response"
INVALID_RESULT_SHAPE_ERROR = "invalid item in model response"
DUPLICATE_RESULT_ID_ERROR = "duplicate id in model response"
UNEXPECTED_RESULT_ID_ERROR = "unexpected id in model response"
DUPLICATE_REQUEST_ID_ERROR = "duplicate id in translation request"
_STRUCTURED_RESULT_FIELDS = (
    "verdict",
    "taxonomy",
    "source_evidence",
    "target_evidence",
)


def provider_response_instruction(system_prompt: str) -> str:
    """Preserve a richer response schema already declared by the caller."""
    prompt = system_prompt if isinstance(system_prompt, str) else ""
    targeted_fields = (
        "verdict",
        "taxonomy",
        "source_evidence",
        "target_evidence",
    )
    if all(field in prompt for field in targeted_fields):
        return (
            "Follow the response contract declared above exactly. Reply with "
            "ONLY its JSON array, preserve every declared field, add no prose. "
        )
    return (
        "Reply with ONLY a JSON array of "
        '{"id": N, "translation": "..."} objects, no prose. '
    )


def reconcile_translation_results(parsed_list: List[Dict], items: List[Dict]) -> List[Dict]:
    """Return exactly one normalized result per input item.

    Providers can receive model output in slightly different wrappers, but once
    a JSON list is available the downstream contract is the same: match by id,
    preserve intentional empty-string translations, retain only the structured
    semantic-review fields understood downstream, and surface malformed values
    as explicit per-block errors.
    """
    def batch_error(message: str) -> List[Dict]:
        return [
            {"id": item.get("id"), "translation": "", "error": message}
            for item in items
        ]

    requested_ids = [str(item.get("id")) for item in items]
    if len(set(requested_ids)) != len(requested_ids):
        return batch_error(DUPLICATE_REQUEST_ID_ERROR)
    if any(
        not isinstance(result, dict) or "id" not in result
        for result in parsed_list
    ):
        return batch_error(INVALID_RESULT_SHAPE_ERROR)

    returned_ids = [str(result.get("id")) for result in parsed_list]
    if len(set(returned_ids)) != len(returned_ids):
        return batch_error(DUPLICATE_RESULT_ID_ERROR)
    requested_id_set = set(requested_ids)
    if any(result_id not in requested_id_set for result_id in returned_ids):
        return batch_error(UNEXPECTED_RESULT_ID_ERROR)

    by_id = {str(result.get("id")): result for result in parsed_list}
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
            normalized = {
                "id": item_id,
                "translation": value,
                "error": provided_error if not value else "",
            }
            normalized.update({
                field: r[field]
                for field in _STRUCTURED_RESULT_FIELDS
                if field in r
            })
            out.append(normalized)
        else:
            out.append({
                "id": item_id,
                "translation": "",
                "error": f"invalid translation type: {type(value).__name__}",
            })
    return out
