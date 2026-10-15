"""Read-only public digest view. Never serialize processing inputs or account data."""
from urllib.parse import urlsplit
from .core import iso


def public_digest(digest):
    data = digest.data
    events = {event['event_id']: event for event in data.get('events', [])}
    items = []
    for item in data.get('items', []):
        event = events.get(item['event_id'], {})
        sources = []
        for source in event.get('sources', []):
            url = source.get('url', '')
            if urlsplit(url).scheme not in ('http', 'https'):
                continue
            sources.append({key: source.get(key) for key in
                ('source', 'url', 'published_at', 'updated_at')})
        items.append({
            'id': item['event_id'], 'title': item['title']['text'],
            'summary': [line['text'] for line in item.get('summary', [])],
            'consequences': item['consequences']['text'],
            'sources': sources,
            'status_notes': [note['text'] for note in event.get('status_notes', [])],
            'selection_reason': event.get('ranking', {}).get('reason', ''),
            'is_update': bool(event.get('is_update')),
        })
    return {
        'id': digest.id, 'revision': digest.revision, 'status': digest.status,
        'created_at': iso(digest.created_at),
        **{key: data.get(key, '') for key in
           ('title', 'subject', 'period', 'control_time', 'full', 'post', 'zero_events_reason')},
        'items': items,
    }
