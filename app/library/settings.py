"""Durable settings edits applied between library jobs, after subtitle publication."""
import copy
import threading
import functools
from fastapi import HTTPException
from app.config import Config

FIELDS = {
    'translation': {'primary_provider', 'primary_model', 'primary_effort', 'polish_provider', 'polish_model',
                    'polish_effort', 'batch_size', 'semantic_qa_batch_size', 'full_doc_mode'},
    'asr': {'model_size', 'beam_size'},
}


def seal_completed_delivery(pid):
    """Keep an already certified library result readable after changing defaults."""
    from app.utils.project_store import load_project, mutate_project, project_dir
    from app.utils.translation_delivery import translation_delivery_lock
    from app.utils.translation_certification import validate_translation_delivery
    from app.utils.translation_configuration import capture_knowledge_context, translation_configuration_snapshot
    with translation_delivery_lock(pid, blocking=False) as acquired:
        if not acquired:
            return False
        try:
            project = load_project(pid)
        except FileNotFoundError:
            return True
        if project.get('library_status') != 'done' or not project.get('library_source_path'):
            return True
        has_config = bool(project.get('library_delivery_config') and project.get('library_delivery_run_id') == project.get('translation_quality_run_id'))
        if has_config and project.get('translation_knowledge_context'):
            return True
        pdir = project_dir(pid)
        delivery = validate_translation_delivery(project, pdir)
        if not (delivery.valid and delivery.expects_certification and delivery.passed):
            return True  # Never certify or repair an invalid historical result here.
        config = project['library_delivery_config'] if has_config else Config.to_dict()
        snapshot = translation_configuration_snapshot(project, config=config, project_path=pdir)
        frozen = {key: snapshot[key] for key in ('translation', 'providers')}
        context = project.get('translation_knowledge_context') or capture_knowledge_context(project, pdir)
        mutate_project(pid, lambda p: p.update(library_delivery_config=frozen,
                                              translation_knowledge_context=context,
                                              library_delivery_run_id=project.get('translation_quality_run_id')))
        return True


def preserve_delivered_knowledge(handler):
    """Upgrade valid historical deliveries before any KB or candidate edit.

    The global lock only covers capture and local edits. Delivery locks are tried
    non-blocking, so a reader/publisher can never deadlock waiting on this lock.
    Invalid historical deliveries remain invalid and are never re-certified.
    """
    @functools.wraps(handler)
    def guarded(*args, **kwargs):
        from app.utils import project_store
        from app.utils.translation_configuration import KNOWLEDGE_CONTEXT_LOCK
        with KNOWLEDGE_CONTEXT_LOCK:
            for path in project_store.PROJECTS_DIR.glob('*/project.json'):
                if path.parent.is_symlink() or path.is_symlink():
                    continue
                try:
                    project = project_store.load_project(path.parent.name)
                except (FileNotFoundError, ValueError):
                    continue
                if project.get('library_status') != 'done' or not project.get('library_source_path'):
                    continue
                if not seal_completed_delivery(path.parent.name):
                    raise HTTPException(409, '已完成字幕正在读取或保存，请稍后重试知识库修改')
            return handler(*args, **kwargs)
    return guarded


class LibrarySettings:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def state(self):
        with self.lock:
            return {'pending': bool(self.store.setting('pending_model_settings', {})),
                    'current_provider': Config.get('translation', 'primary_provider'),
                    'current_model': Config.get('translation', 'primary_model'),
                    'current_effort': Config.get('translation', 'primary_effort'),
                    'current_polish_provider': Config.get('translation', 'polish_provider'),
                    'current_polish_model': Config.get('translation', 'polish_model'),
                    'current_polish_effort': Config.get('translation', 'polish_effort'),
                    'error': self.store.setting('model_settings_error', '')}

    def read(self):
        with self.lock:
            settings = Config.public_dict()
            for section, values in self.store.setting('pending_model_settings', {}).items():
                settings.setdefault(section, {}).update(values)
            return {'settings': settings, 'state': self.state()}

    def queue(self, data):
        from app.api.settings import _validate_settings_update
        payload = copy.deepcopy(data)
        if not isinstance(payload, dict) or any(
            section not in FIELDS or not isinstance(values, dict) or set(values) - FIELDS[section]
            for section, values in payload.items()
        ):
            raise HTTPException(400, '只能修改控制台中的模型与字幕参数')
        _validate_settings_update(payload)
        with self.lock:
            desired = self.read()['settings']
            for section, values in payload.items():
                desired[section].update(values)
            current = Config.public_dict()
            patch = {section: {key: desired[section][key] for key in keys
                               if desired[section].get(key) != current[section].get(key)}
                     for section, keys in FIELDS.items()}
            self.store.set_setting('pending_model_settings', {s: v for s, v in patch.items() if v})
            self.store.set_setting('model_settings_error', '')
            return self.read()

    def apply(self):
        """Called by the monitor only; the task registry excludes concurrent launches."""
        from app.services.translation_tasks import run_when_tasks_idle
        def commit():
            with self.lock:
                patch = self.store.setting('pending_model_settings', {})
                if not patch or self.store.rows(['translating', 'publishing', 'pausing', 'cancelling'], limit=1):
                    return False
                offset = 0
                while True:
                    rows = self.store.rows(['done'], limit=100, offset=offset)
                    for row in rows:
                        if row.get('project_id') and not seal_completed_delivery(row['project_id']):
                            return False
                    if len(rows) < 100:
                        break
                    offset += len(rows)
                Config.update(patch)
                self.store.set_setting('pending_model_settings', {})
                self.store.set_setting('model_settings_error', '')
                return True
        return run_when_tasks_idle(commit)
