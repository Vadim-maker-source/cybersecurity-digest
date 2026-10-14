import asyncio,copy,io,zipfile
from datetime import timedelta
import pytest
from app.fixtures import CASES,CONTROL,DEMO
from app.pipeline import process
from app.validators import parse_date,period_reason,count_chars,validate_quote
from app.parsers import public_address,parse_import,FetchError

@pytest.mark.asyncio
@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
async def test_mandatory(case):
    result=await process(case['articles'],CONTROL,'fixture')
    assert result['digest']['event_count']==case['expected']['count']
    assert result['validation']['passed'],result['validation']
    if case['expected'].get('reason'):
        assert any(d['reason_code']==case['expected']['reason'] for d in result['decisions'])
    if case['expected'].get('conflict'):
        assert '100' in result['digest']['post'] and '300' in result['digest']['post']
    for url in result['digest']['urls']:
        assert url in result['digest']['full'] and url in result['digest']['post']

def test_boundary():
    T,_=parse_date(CONTROL)
    a={'published_at':(T-timedelta(hours=24)).isoformat()}
    assert period_reason(a,T)=='OUT_OF_PERIOD'
    a['published_at']=(T-timedelta(hours=24)+timedelta(seconds=1)).isoformat()
    assert period_reason(a,T) is None
    a['published_at']=T.isoformat();assert period_reason(a,T) is None
    a['published_at']=(T+timedelta(seconds=1)).isoformat();assert period_reason(a,T)=='FUTURE_PUBLICATION'

def test_dates():
    assert parse_date('2026-10-14')[1]=='DATE_PRECISION_INSUFFICIENT'
    assert parse_date('2026-10-14T20:00:00')[0] is None
    assert parse_date('2026-10-14T20:00:00',True)[0]==parse_date('2026-10-14T17:00:00Z')[0]
    assert parse_date('invalid')[0] is None

def test_counter_unicode_exact_urls():
    url='https://fixture.invalid/a'
    assert count_chars('я😀 \n'+url,[url])==4
    assert count_chars(url+' '+url,[url])==1
    assert count_chars('https://unregistered.example/x',[url])>1
    assert count_chars('а'*4001,[])==4001
    assert count_chars(url+'-another',[url])==len(url+'-another')

@pytest.mark.asyncio
async def test_post_only_reuses_full_digest_sentences():
    result=await process(copy.deepcopy(DEMO),CONTROL,'fixture')
    for item in result['digest']['items']:
        assert item['summary'][0]['text'] in item['short']['text']
        full_ids=set(item['title']['claim_ids']+[c for s in item['summary'] for c in s['claim_ids']]+item['consequences']['claim_ids'])
        assert set(item['short']['claim_ids'])<=full_ids

@pytest.mark.asyncio
async def test_explicit_moscow_import_preserves_source_date():
    article=copy.deepcopy(DEMO[0]);article['published_at']='2026-10-14T12:00:00';article['assume_moscow']=True
    result=await process([article],CONTROL,'fixture')
    assert '14.10.2026 12:00 МСК' in result['digest']['full']
    assert result['decisions'][0]['date_verification_status']=='ASSUMED_MOSCOW'

def test_quote_and_number_guards():
    with pytest.raises(ValueError):validate_quote({'quote':'нет','text':'факт'},DEMO[0])
    with pytest.raises(ValueError):validate_quote({'quote':DEMO[0]['text'],'text':'Утекло 100 000 записей'},DEMO[0])

def test_evidence_whitespace_preserves_original_offsets():
    article={'text':'Начало. Утекло 12\u00a0000\nзаписей. Конец.'}
    fact={'quote':'Утекло 12 000 записей.','text':'Утекло 12 000 записей.'}
    start,end=validate_quote(fact,article)
    assert article['text'][start:end]==fact['quote']=='Утекло 12\u00a0000\nзаписей.'

@pytest.mark.parametrize('host',['127.0.0.1','::1','169.254.169.254','10.0.0.1','localhost'])
def test_ssrf(host):
    with pytest.raises(FetchError):public_address(host)

def test_zip_slip():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:archive.writestr('../evil.json','[]')
    with pytest.raises(ValueError):parse_import(stream.getvalue(),'files.zip')

@pytest.mark.asyncio
async def test_repeat_invariants():
    a=await process(copy.deepcopy(DEMO),CONTROL,'fixture')
    b=await process(copy.deepcopy(DEMO),CONTROL,'fixture')
    assert a['digest']['items']==b['digest']['items']
    assert a['decisions']==b['decisions']

@pytest.mark.asyncio
async def test_checkpoint_resumes_completed_extraction(monkeypatch):
    import json
    import app.pipeline as pipeline
    saved={}
    async def save_checkpoint(data):
        nonlocal saved
        saved=json.loads(json.dumps(data))
        if data['stage']=='verify':raise RuntimeError('simulated worker crash')
    with pytest.raises(RuntimeError):
        await pipeline.process(copy.deepcopy(DEMO),CONTROL,'fixture',save_checkpoint=save_checkpoint)
    def unexpected(_):raise AssertionError('completed extraction repeated')
    monkeypatch.setattr(pipeline,'fixture_extract',unexpected)
    result=await pipeline.process(copy.deepcopy(DEMO),CONTROL,'fixture',checkpoint=saved)
    assert result['digest']['event_count']==3
    assert all(len(d['event_group_ids'])==len(set(d['event_group_ids'])) for d in result['decisions'])
