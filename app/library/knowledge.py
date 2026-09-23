"""Read-only knowledge inventory and host storage locations for the server console."""
import os
from pathlib import Path
import sqlite3


def summary(store):
    from app.config import DATA_DIR,Config
    from app.engines.knowledge import _get_singleton
    from app.engines.kb_suggestions import load_suggestions
    root=Path(DATA_DIR)
    def count(filename,table):
        path=root/filename
        if not path.exists():return 0
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            return db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    kb=_get_singleton().list_projects()
    terms=sum(len(getattr(p,field)) for p in kb.values() for field in ['characters','places','brands','slang'])
    pending=[]
    for row in store.rows(['done','cancelled','error','translating','publishing','paused','pausing','cancelling'],limit=100):
        pid=row.get('project_id')
        if not pid:continue
        suggestions=load_suggestions(root/'projects'/pid/'kb_suggestions.json')
        amount=sum(s.status=='pending' for s in suggestions)
        if amount:pending.append({'project_id':pid,'name':Path(row['path']).name,'count':amount})
    data=os.environ.get('AISUBPRO_HOST_DATA_DIR',str(root))
    return {'projects':len(kb),'terms':terms,'memory_entries':count('translation_memory.sqlite3','translation_memory'),
            'phrase_entries':count('phrase_library.sqlite3','phrase_examples'),'pending':pending,
            'memory_enabled':Config.get('translation',default={}).get('use_translation_memory',True),
            'storage':{'data':data,'knowledge':str(Path(data)/'knowledge.json'),'projects':str(Path(data)/'projects'),
                       'temporary':os.environ.get('AISUBPRO_HOST_TEMP_DIR',os.environ.get('TMPDIR','/tmp')),
                       'models':os.environ.get('AISUBPRO_HOST_MODEL_DIR',os.environ.get('HF_HOME','/models'))}}
