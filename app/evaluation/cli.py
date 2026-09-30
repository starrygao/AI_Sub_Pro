"""Command line entry point for translation quality evaluation."""
from __future__ import annotations

import argparse
from pathlib import Path

from app.evaluation.corpus import load_corpus_file
from app.evaluation.metrics import evaluate_case
from app.evaluation.reports import (
    build_report,
    write_json_report,
    write_markdown_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a golden translation corpus and write reports."
    )
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--markdown-out", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="Run the production translator; may use paid provider calls")
    parser.add_argument("--provider", choices=["omp_cli", "openai", "deepseek", "gemini", "claude_cli", "codex_cli"])
    parser.add_argument("--model")
    parser.add_argument("--effort", default="auto", choices=["auto", "off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"])
    parser.add_argument("--baseline", type=Path, help="Compare deterministic metrics with a previous JSON report")
    args = parser.parse_args(argv)
    if args.execute and not (args.provider and args.model):
        parser.error("--execute requires --provider and --model")

    corpus = load_corpus_file(args.corpus)
    if args.execute:
        import copy
        from app.config import Config
        from app.engines.translator import SubtitleTranslator
        from app.evaluation.runner import run_corpus
        Config.load()
        config = copy.deepcopy(Config.to_dict())
        config["translation"].update(primary_provider=args.provider, primary_model=args.model,
                                     primary_effort=args.effort, polish_provider="", full_doc_mode=True,
                                     use_translation_memory=False, use_phrase_library=False)
        report = run_corpus(corpus, lambda case: SubtitleTranslator(config),
                            run_label=f"{args.provider}/{args.model}/{args.effort}")
    else:
        report = build_report([evaluate_case(case) for case in corpus.cases])
        report["run"] = {"mode": "stored_candidates", "label": "rule regression; no model executed"}
    if args.baseline:
        import json
        baseline = json.loads(args.baseline.read_text())
        if [c['case_id'] for c in baseline['cases']] != [c['case_id'] for c in report['cases']]:
            parser.error("Baseline must use the same ordered corpus cases")
        report['baseline_deltas'] = {k: round(v - baseline['summary'][k], 4)
                                     for k, v in report['summary'].items()
                                     if k.endswith('_rate') and k in baseline['summary']}
    case_results = report['cases']
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    write_json_report(report, args.json_out)
    write_markdown_report(report, args.markdown_out)

    print(
        "Wrote translation quality reports "
        f"for {len(case_results)} cases: {args.json_out} and {args.markdown_out}"
    )
    return 1 if report["summary"].get("execution_failure_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
