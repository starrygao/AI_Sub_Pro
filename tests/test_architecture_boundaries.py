import ast
from pathlib import Path


def test_trailer_and_scheduler_use_task_service_not_http_module():
    for name in ('trailer_pipeline', 'scheduler'):
        tree = ast.parse(Path(f'app/engines/{name}.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != 'app.api.translate'
                assert not (node.module == 'app.api' and any(a.name == 'translate' for a in node.names))


def test_http_pipeline_module_does_not_own_worker_implementation():
    tree = ast.parse(Path('app/api/translate.py').read_text())
    assert not any(isinstance(n, ast.FunctionDef) and n.name == '_run_translate_pipeline' for n in tree.body)
