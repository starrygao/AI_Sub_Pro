"""Evaluate fresh translations through the production translator.

Counters measure provider batch submissions (not hidden SDK retry attempts).
A repeated primary block is rework; polishing is counted separately.
"""
from dataclasses import replace
from datetime import timedelta
from time import perf_counter

from app.evaluation.metrics import evaluate_case
from app.evaluation.reports import build_report
from app.utils.srt import SubtitleBlock


def run_corpus(corpus, translator_factory, *, run_label):
    results = []
    for case in corpus.cases:
        translator = translator_factory(case)
        blocks = [SubtitleBlock(i, timedelta(seconds=i * 3), timedelta(seconds=i * 3 + 2), block['text'])
                  for i, block in enumerate(case.source_blocks, 1)]
        seen, reworked = set(), set()
        runtime = {'provider_batch_calls': 0, 'polish_batch_calls': 0}
        originals = []
        for role in ('primary', 'polish'):
            provider = getattr(translator, role, None)
            if provider is None:
                continue
            original = provider.translate_batch
            originals.append((provider, original))
            def counted(items, *args, _original=original, _role=role, **kwargs):
                runtime['provider_batch_calls'] += 1
                if _role == 'polish':
                    runtime['polish_batch_calls'] += 1
                else:
                    ids = {str(item['id']) for item in items}
                    reworked.update(ids & seen)
                    seen.update(ids)
                return _original(items, *args, **kwargs)
            provider.translate_batch = counted
        started = perf_counter()
        error = None
        try:
            translator.translate(blocks, case.target_language, meta_info=dict(case.project))
        except Exception as exc:
            # Raw provider exceptions can contain credentials or request bodies.
            error = type(exc).__name__
        finally:
            runtime['elapsed_seconds'] = round(perf_counter() - started, 4)
            for provider, original in originals:
                provider.translate_batch = original
        runtime['rework_block_rate'] = round(len(reworked) / len(blocks), 4) if blocks else 0
        runtime['reworked_block_count'] = len(reworked)
        runtime['source_block_count'] = len(blocks)
        runtime['primary_model'] = getattr(translator.primary, 'model', '')
        candidate = [{'id': source['id'], 'translation': block.translation}
                     for source, block in zip(case.source_blocks, blocks)]
        evaluated = evaluate_case(replace(case, candidate_blocks=candidate))
        evaluated.update(runtime=runtime, source_blocks=case.source_blocks,
                         candidate_blocks=candidate, reference_blocks=case.reference_blocks,
                         execution_error=error)
        results.append(evaluated)
    report = build_report(results)
    report['run'] = {'label': run_label, 'mode': 'generated',
                     'counter_unit': 'provider batch submissions; SDK internal retries excluded',
                     'scope': 'SubtitleTranslator including missing-result retries and optional polishing; project QA repair excluded'}
    report['summary'].update(
        elapsed_seconds=round(sum(c['runtime']['elapsed_seconds'] for c in results), 4),
        provider_batch_calls=sum(c['runtime']['provider_batch_calls'] for c in results),
        execution_failure_count=sum(c['execution_error'] is not None for c in results),
        rework_block_rate=round(sum(c['runtime']['reworked_block_count'] for c in results) /
                               max(1, sum(c['runtime']['source_block_count'] for c in results)), 4))
    return report
