from app.evaluation.corpus import load_corpus_file


def test_runner_evaluates_generated_output_and_records_rework():
    from app.evaluation.runner import run_corpus
    from app.engines.translator import SubtitleTranslator
    from unittest.mock import patch
    class Provider:
        model = 'offline-fixture'
        supports_full_document_mode = True
        context_window_tokens = 100000
        def __init__(self): self.calls = 0
        def translate_batch(self, items, system_prompt, retries=3):
            self.calls += 1
            return [{'id': item['id'], 'translation': '' if self.calls == 1 else '新的译文'} for item in items]
    def factory(case):
        with patch('app.engines.translator.get_provider', return_value=Provider()):
            return SubtitleTranslator({'translation': {'primary_provider':'openai','primary_model':'offline-fixture','polish_provider':'','full_doc_mode':True,'use_translation_memory':False,'use_phrase_library':False,'missing_translation_retries':1}})
    corpus = load_corpus_file('tests/fixtures/golden_corpus/milestone1.json')
    report = run_corpus(corpus, factory, run_label='offline-fixture')
    first = report['cases'][0]
    assert first['runtime']['provider_batch_calls'] >= 2
    assert first['runtime']['rework_block_rate'] == 1
    assert all(b['translation'] == '新的译文' for b in first['candidate_blocks'])
    assert first['runtime']['elapsed_seconds'] >= 0
    assert report['run']['label'] == 'offline-fixture'
    assert report['manual_scores'][0]['score'] is None
