"""Report builders for translation quality evaluation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def build_report(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": {
            "case_count": len(case_results),
            "terminology_hit_rate": _avg(
                [case["terminology"]["hit_rate"] for case in case_results]
            ),
            "missing_translation_rate": _avg(
                [case["missing_translation"]["rate"] for case in case_results]
            ),
            "row_alignment_rate": _avg(
                [case["row_alignment"]["rate"] for case in case_results]
            ),
            "format_breakage_rate": _avg(
                [case["format"]["breakage_rate"] for case in case_results]
            ),
        },
        "cases": case_results,
        "manual_scores": [
            {"case_id": case["case_id"], "score": None, "notes": ""}
            for case in case_results
        ],
    }


def write_json_report(report: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_markdown_report(report: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(_markdown(report), encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Translation Quality Evaluation",
        "",
        "## Summary",
        "",
        f"- Case count: {summary['case_count']}",
        f"- Terminology hit rate: {_format_rate(summary['terminology_hit_rate'])}",
        f"- Missing translation rate: {_format_rate(summary['missing_translation_rate'])}",
        f"- Row alignment rate: {_format_rate(summary['row_alignment_rate'])}",
        f"- Format breakage rate: {_format_rate(summary['format_breakage_rate'])}",
        "",
        "## Case Details",
        "",
    ]

    for case in report["cases"]:
        terminology = case["terminology"]
        missing_translation = case["missing_translation"]
        row_alignment = case["row_alignment"]
        format_result = case["format"]

        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- Tags: {_format_ids(case.get('tags', []))}",
                f"- Terminology hit rate: {_format_rate(terminology['hit_rate'])}",
                "- Missing translation IDs: "
                f"{_format_ids(missing_translation.get('missing_ids', []))}",
                "- Source missing translation IDs: "
                f"{_format_ids(missing_translation.get('source_missing_ids', []))}",
                "- Row alignment missing IDs: "
                f"{_format_ids(row_alignment.get('missing_ids', []))}",
                "- Row alignment extra IDs: "
                f"{_format_ids(row_alignment.get('extra_ids', []))}",
                f"- Format broken IDs: {_format_ids(format_result.get('broken_ids', []))}",
                "",
            ]
        )

    lines.extend(
        [
            "## Manual scoring",
            "",
            "| Case ID | Score | Notes |",
            "| --- | --- | --- |",
        ]
    )
    for manual_score in report["manual_scores"]:
        lines.append(f"| {manual_score['case_id']} |  |  |")
    lines.append("")
    return "\n".join(lines)


def _format_rate(value: Any) -> str:
    return f"{float(value):.4f}"


def _format_ids(values: list[Any]) -> str:
    if not values:
        return "None"
    return ", ".join(str(value) for value in values)
