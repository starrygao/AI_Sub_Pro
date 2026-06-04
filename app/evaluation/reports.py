"""Report serializers for translation evaluation."""
from __future__ import annotations

import json


def report_to_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def report_to_markdown(report: dict) -> str:
    lines = [
        "# Translation Evaluation Report",
        "",
        f"- Cases: {report.get('case_count', 0)}",
        "",
        "## Metrics",
    ]
    metrics = report.get("metrics", {})
    if isinstance(metrics, dict):
        for key in sorted(metrics):
            lines.append(f"- {key}: {metrics[key]}")
    cases = report.get("cases", [])
    if isinstance(cases, list) and cases:
        lines.append("")
        lines.append("## Cases")
        for case in cases:
            if not isinstance(case, dict):
                continue
            lines.append(
                f"- {case.get('id')}: missing={case.get('missing_translation_count')}, "
                f"english={case.get('english_residue_count')}, "
                f"length={case.get('length_violation_count')}, "
                f"alignment={case.get('alignment_ok')}"
            )
    return "\n".join(lines) + "\n"
