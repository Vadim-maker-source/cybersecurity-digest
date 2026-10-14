from .schemas import Verification

async def verify_sources(model,items,events,articles,control_time):
    """Check each event against its original text, including omitted caveats."""
    by_id={str(a['id']):a for a in articles}
    results=[]
    for item,event in zip(items,events):
        documents=[{'id':s['id'],'title':by_id[str(s['id'])].get('title',''),
                    'text':by_id[str(s['id'])].get('text',''),
                    'published_at':by_id[str(s['id'])].get('published_at')}
                   for s in event['sources'] if str(s['id']) in by_id]
        if len(documents)!=len(event['sources']) or not all(d['text'] for d in documents):
            result={'supported':False,'problems':['Не найден полный текст одного из источников']}
        elif sum(len(d['text']) for d in documents)>32000:
            result={'supported':False,'problems':['Полные тексты превышают лимит смысловой проверки; нужна отдельная редакторская обработка']}
        else:
            result=(await model.call('verify',{'items':[item],'events':[event],
                'source_documents':documents,'control_time':control_time},Verification)).model_dump()
        result['supported']=result['supported'] and not result['problems']
        results.append({'event_id':event['event_id'],**result})
    return {'supported':all(r['supported'] for r in results),
            'problems':[r['event_id']+': '+p for r in results for p in r['problems']],
            'per_event':results,'provider':'GigaChat: полные тексты источников'}

def restrict_consequences(items,events):
    repairs=[]
    for item,event in zip(items,events):
        claims={c['claim_id']:c for c in event['claims']}
        ids=item['consequences'].get('claim_ids',[])
        if ids and not any(claims.get(cid,{}).get('kind')=='impact' for cid in ids):
            item['consequences']={'text':'В подтверждённых фрагментах последствия не указаны.','claim_ids':[]}
            repairs.append({'event_id':event['event_id'],'field':'consequences','reason':'Нет извлечённого факта типа impact; прогноз не подменяет описанное последствие.'})
    return repairs
