import copy
import pytest
from app.validators import checked_compositions,validate_composition


def test_unconfirmed_cve_does_not_block_other_supported_events():
    sentence={'text':'Сервис остановлен','claim_ids':['c']}
    event={'event_id':'good','claims':[{'claim_id':'c','quote':'Сервис остановлен'}],'sources':[]}
    item={'event_id':'good','title':copy.deepcopy(sentence),'summary':[copy.deepcopy(sentence)],
        'consequences':copy.deepcopy(sentence),'short':copy.deepcopy(sentence)}
    bad_event={**copy.deepcopy(event),'event_id':'bad'}
    bad_item={**copy.deepcopy(item),'event_id':'bad'}
    bad_item['title']['text']='Уязвимость CVE-2026-76418'
    items,events,rejected=checked_compositions([bad_item,item],[bad_event,event])
    assert [x['event_id'] for x in items]==['good']
    assert 'UNSUPPORTED_NUMBER' in rejected['bad']
    validate_composition(items,events)
    assert bad_item['title']['text']=='Уязвимость CVE-2026-76418'


def test_mismatched_event_set_is_not_silently_discarded():
    with pytest.raises(ValueError,match='EVENT_SET_MISMATCH'):
        checked_compositions([{'event_id':'other'}],[{'event_id':'expected'}])


@pytest.mark.asyncio
async def test_resume_preserves_exclusion_and_valid_remaining_digest():
    from app.fixtures import DEMO,CONTROL
    from app.pipeline import process
    saved={}
    async def checkpoint(value):saved.update(copy.deepcopy(value))
    original=await process(DEMO,CONTROL,'fixture',save_checkpoint=checkpoint)
    rejected=original['digest']['items'][0]['event_id']
    saved['items']=[i for i in saved['items'] if i['event_id']!=rejected]
    saved['composition_rejections']={rejected:'UNSUPPORTED_NUMBER'}
    resumed=await process(DEMO,CONTROL,'fixture',checkpoint=saved)
    assert resumed['validation']['passed']
    assert resumed['digest']['event_count']==original['digest']['event_count']-1
    assert not next(e for e in resumed['events'] if e['event_id']==rejected)['selected']
    assert any(d['reason_code']=='COMPOSITION_VALIDATION_FAILED' for d in resumed['decisions'])
