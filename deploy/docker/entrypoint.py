"""Initialize only an empty server data volume, then start one application worker."""
import json
import os
from pathlib import Path

path=Path(os.environ['AI_SUB_PRO_DATA_DIR'])/'config.json'
path.parent.mkdir(parents=True,exist_ok=True)
if not path.exists():
    config={'translation':{'primary_provider':'codex_cli','primary_model':'gpt-5.5','primary_effort':'medium',
                           'polish_provider':'','batch_size':20,'full_doc_mode':True},
            'providers':{'codex_cli':{'timeout_sec':600}},
            'asr':{'backend':'faster_whisper','model_size':'small','use_demucs':False,'beam_size':3},
            'concurrency':{'asr':1,'translate':1,'download':1,'burn':1}}
    path.write_text(json.dumps(config,ensure_ascii=False));path.chmod(0o600)
import uvicorn
uvicorn.run('app.server:app',host=os.environ.get('AISUBPRO_SERVER_HOST','127.0.0.1'),port=int(os.environ.get('AISUBPRO_SERVER_PORT','18091')),workers=1,log_config=None)
