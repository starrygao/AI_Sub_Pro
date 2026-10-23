"""Read-only dashboard statistics over one consistent discovery-ledger snapshot."""
import json
import math
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.library.guard import map_path


def present_task(row, host_path_maps):
    """Share task actions, progress and safe image links with the processing list."""
    from app.library.artwork import artwork_links
    row.pop('detection',None)  # Probe metadata stays in the ledger, not the browser response.
    row.update(artwork_links(row))
    from app.library.control import TaskControls
    row['available_actions']=TaskControls.actions(row)
    row['control_revision']=TaskControls.revision(row)
    mappings=host_path_maps
    if row['state'] not in {'done','skipped','native_language','historical','cancelled'}:
        from app.library.publish import bilingual_sidecar_path
        row['output_path']=str(bilingual_sidecar_path(row['path']))
    row['server_source_path']=map_path(row['path'],mappings)
    row['server_output_path']=map_path(row.get('output_path',''),mappings)
    if row['state'] in {'waiting','ready'}:
        # Retained project progress belongs to the previous attempt, not this queue entry.
        row['progress']=None
    elif row.get('preparation_progress'):
        row['progress']=row['preparation_progress']
    elif row.get('project_id'):
        from app.engines.scheduler import get_progress
        row['progress']=get_progress(row['project_id'])
    return row


def _models(settings):
    response = settings.read()
    state = response['state']
    desired = response['settings'].get('translation', {})
    current_keys = {'primary_provider': 'current_provider', 'primary_model': 'current_model',
                    'primary_effort': 'current_effort'}
    fields = [f'{stage}_{field}' for stage in ('primary', 'polish', 'review')
              for field in ('provider', 'model', 'effort')]
    return {'current': {key: state.get(current_keys.get(key, 'current_' + key)) for key in fields},
            'desired': {key: desired.get(key) for key in fields},
            'pending': bool(state.get('pending')), 'error': state.get('error', '')}


def build_overview(worker, timezone='UTC'):
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('时区无效，请使用 IANA 时区名称') from None
    now = time.time()
    today = datetime.fromtimestamp(now, zone).date()
    dates = {str(today - timedelta(days=ago)): 0 for ago in range(6, -1, -1)}
    total = undated = 0
    with worker.store.db() as db:
        db.execute('BEGIN')
        counts = dict(db.execute("SELECT state,count(*) FROM media WHERE state!='deleted' GROUP BY state"))
        for completed, kind in db.execute("SELECT json_extract(payload,'$.completed_at'), "
                "json_type(payload,'$.completed_at') FROM media WHERE state='done'"):
            valid = kind in ('integer', 'real') and math.isfinite(completed) and 0 < completed <= now
            try:
                date = str(datetime.fromtimestamp(completed, zone).date()) if valid else None
            except (OverflowError, OSError, ValueError):
                date = None
            if date is None:
                undated += 1
                continue
            total += 1
            if date in dates:
                dates[date] += 1
        def rows(states, order):
            query = "SELECT json_remove(payload,'$.detection') FROM media WHERE state IN (" + ','.join('?' for _ in states) + ') ORDER BY ' + order + ', path ASC LIMIT 3'
            return [json.loads(row[0]) for row in db.execute(query, states)]
        active = rows(('translating', 'publishing', 'pausing', 'cancelling'), 'updated DESC')
        queue = rows(('ready',), "COALESCE(json_extract(payload,'$.priority'),0) DESC, updated ASC")
        attention = rows(('error', 'changed', 'missing'), 'updated DESC')
    mappings = worker.config.get('host_path_maps', {})
    return {'counts': counts,
            'active': [present_task(row, mappings) for row in active],
            'queue': [present_task(row, mappings) for row in queue],
            'attention': {'counts': {key: counts.get(key, 0) for key in ('error', 'changed', 'missing')},
                          'items': [present_task(row, mappings) for row in attention]},
            'deliveries': {'timezone': timezone, 'days': [{'date': date, 'count': count} for date, count in dates.items()],
                           'total': total, 'undated': undated},
            'models': _models(worker.model_settings), 'generated_at': now}
