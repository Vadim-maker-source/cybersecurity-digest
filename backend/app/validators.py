import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

MOSCOW = ZoneInfo('Europe/Moscow')

def parse_date(raw, assume_moscow=False):
    if not raw: return None,'DATE_UNVERIFIED'
    value=str(raw).strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}',value): return None,'DATE_PRECISION_INSUFFICIENT'
    try:
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        if date.tzinfo is None:
            if not assume_moscow: return None,'DATE_UNVERIFIED'
            date=date.replace(tzinfo=MOSCOW)
            return date.astimezone(timezone.utc),'ASSUMED_MOSCOW'
        return date.astimezone(timezone.utc),'CONFIRMED'
    except (ValueError,TypeError): return None,'DATE_UNVERIFIED'

def period_reason(article,T):
    date,reason=parse_date(article.get('published_at'),article.get('assume_moscow',False))
    if article.get('date_conflict'): return 'DATE_UNVERIFIED'
    if date is None: return reason
    if date > T: return 'FUTURE_PUBLICATION'
    if date <= T-timedelta(hours=24):
        update,status=parse_date(article.get('updated_at'))
        if update and T-timedelta(hours=24)<update<=T and article.get('update_evidence'):
            return 'UPDATE_CANDIDATE'
        return 'OUT_OF_PERIOD'
    return None

def safe_display_url(url):
    try:
        value=urlsplit(url)
        return value.scheme in ('http','https') and bool(value.hostname) and not value.username and not value.password
    except ValueError: return False

def count_chars(text,urls):
    for url in sorted(set(urls),key=len,reverse=True):
        text=re.sub(r'(?<![\w/:?&%#=+~.\-])'+re.escape(url)+r'(?![\w/:?&%#=+~.\-])','',text)
    return len(text)

def validate_quote(fact,article):
    text=article['text']; quote=fact['quote']; start=text.find(quote)
    if quote and start<0:
        normalized=[];positions=[];last_space=False
        for i,char in enumerate(text):
            if char.isspace():
                if not last_space:normalized.append(' ');positions.append(i)
                last_space=True
            else:normalized.append(char);positions.append(i);last_space=False
        normalized_quote=re.sub(r'\s+',' ',quote).strip()
        offset=''.join(normalized).find(normalized_quote) if normalized_quote else -1
        if offset>=0:
            start=positions[offset];end=positions[offset+len(normalized_quote)-1]+1
            quote=text[start:end];fact['quote']=quote
    if not quote or start<0: raise ValueError('EVIDENCE_NOT_SUPPORTED: цитата отсутствует')
    original_numbers=set(re.findall(r'\d+(?:[.,]\d+)?',quote))
    claim_numbers=set(re.findall(r'\d+(?:[.,]\d+)?',fact['text']))
    if not claim_numbers<=original_numbers: raise ValueError('EVIDENCE_NOT_SUPPORTED: новое число в утверждении')
    return start,start+len(quote)

def validate_composition(items,events):
    if [x['event_id'] for x in items]!=[x['event_id'] for x in events]: raise ValueError('EVENT_SET_MISMATCH')
    for item,event in zip(items,events):
        claims={c['claim_id']:c for c in event['claims']}
        for sentence in [item['title'],*item['summary'],item['consequences'],item['short']]:
            if not set(sentence['claim_ids'])<=set(claims): raise ValueError('UNKNOWN_CLAIM_ID')
            if not sentence['claim_ids'] and 'не указ' not in sentence['text'].lower(): raise ValueError('MISSING_EVIDENCE')
            evidence=' '.join(claims[c]['quote'] for c in sentence['claim_ids'])
            checked_text=sentence['text']
            for source in event['sources']:checked_text=checked_text.replace(source['source'],'')
            if not set(re.findall(r'\d+(?:[.,]\d+)?',checked_text))<=set(re.findall(r'\d+(?:[.,]\d+)?',evidence)):
                missing=set(re.findall(r'\d+(?:[.,]\d+)?',checked_text))-set(re.findall(r'\d+(?:[.,]\d+)?',evidence))
                raise ValueError('UNSUPPORTED_NUMBER: '+', '.join(sorted(missing))+' в предложении '+sentence['text']+'. Удали числа/дату, которых нет в подтверждающих цитатах. Дата публикации не равна дате события.')
            if '\u2014' in sentence['text']: raise ValueError('LONG_DASH')

def checked_compositions(items,events):
    """After model repair attempts, retain only individually grounded events."""
    if [i['event_id'] for i in items]!=[e['event_id'] for e in events]:
        raise ValueError('EVENT_SET_MISMATCH')
    accepted=[];selected=[];rejected={}
    for item,event in zip(items,events):
        try:validate_composition([item],[event])
        except ValueError as exc:rejected[event['event_id']]=str(exc)
        else:accepted.append(item);selected.append(event)
    return accepted,selected,rejected
