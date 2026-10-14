import hashlib, json, re, time
from pathlib import Path
from datetime import timedelta
from .schemas import Extraction, Grouping, Ranking, Composition, Verification
from .validators import parse_date, period_reason, safe_display_url, validate_quote, validate_composition, count_chars, MOSCOW
from .llm import GigaChat, ModelError
from .core import ROOT
KEYWORDS=json.loads((ROOT/'config'/'keywords.json').read_text(encoding='utf-8'))['terms']

REASONS={
 'OUT_OF_TOPIC':'Материал не относится к кибербезопасности или не содержит значимого события.',
 'OUT_OF_PERIOD':'Дата не входит в суточный период; значимые новые факты не подтверждены.',
 'FUTURE_PUBLICATION':'Публикация позже контрольного времени.',
 'DATE_UNVERIFIED':'Дата не подтверждена либо источники времени расходятся.',
 'DATE_PRECISION_INSUFFICIENT':'Есть только календарная дата без достаточной точности.',
 'INSUFFICIENT_CONTENT':'Данных для пересказа недостаточно.',
 'MISSING_SOURCE_URL':'Нет допустимой ссылки на исходную публикацию.',
 'SOURCE_UNAVAILABLE':'Источник недоступен; остальные материалы обработаны.',
 'READ_ERROR':'Ошибка чтения отдельного материала.',
 'INCLUDED':'Событие вошло в выпуск по последствиям, масштабу и срочности.',
 'RELEVANT_NOT_SELECTED':'Релевантное событие не вошло в первые пять.',
}

def fixture_extract(article):
    text=article['text']
    sentences=[s.strip() for s in text.split('\n') if s.strip() and not re.search('игнорируй|отправь ключ|измени период',s,re.I)]
    return {'relevant':article.get('test_relevant',True),'reason':'Детерминированный тестовый провайдер; это не результат GigaChat.',
        'category':'incident','sufficient':len(text)>60 and len(sentences)>=2,'events':[{
        'title':article['title'],'facts':[{'text':s,'quote':s,'kind':'impact' if n else 'fact','certainty':'reported'} for n,s in enumerate(sentences)],
        'affected':[], 'cves':[], 'event_date':None, 'uncertainties':[], 'primary':article.get('test_primary',False),
        'origin_statement':article.get('test_event_key'),'is_old_event':False,'new_facts':[article.get('update_evidence')] if article.get('test_new_fact') else []}]}

def source_line(s):
    date,_=parse_date(s.get('published_at'))
    when=date.astimezone(MOSCOW).strftime('%d.%m.%Y %H:%M МСК') if date else 'дата не подтверждена'
    update,_=parse_date(s.get('updated_at'))
    if update:when+=' (обновление '+update.astimezone(MOSCOW).strftime('%d.%m.%Y %H:%M МСК')+')'
    return f"{s['source'] or 'Источник не указан'} · {when} · ID {s['id']}\n{s['url']}"

def align_formats(items,events):
    for item,event in zip(items,events):
        event['status_notes']=[{'text':c['text'].replace('\u2014','-'),'claim_ids':[c['claim_id']]} for c in event['claims']
            if c['kind'] in ('uncertainty','conflict') or c['certainty'] in ('preliminary','unconfirmed')]
        sentences=item['summary'] if event.get('conflicts') else [item['summary'][0],item['consequences']]
        unique={s['text']:s for s in sentences if s['text']!='В источнике не указано.'}
        item['short']={'text':' '.join(unique),'claim_ids':list(dict.fromkeys(c for s in unique.values() for c in s['claim_ids']))}

def render_digest(items,events,T,zero_reason):
    align_formats(items,events)
    start=T-timedelta(hours=24)
    title='Дайджест по кибербезопасности'
    period=f"{start.astimezone(MOSCOW):%d.%m.%Y %H:%M} - {T.astimezone(MOSCOW):%d.%m.%Y %H:%M} МСК"
    header=title+'\nПериод: '+period+f'\nКонтрольное время: {T.astimezone(MOSCOW):%d.%m.%Y %H:%M} МСК'
    full=[header]; post=[header]
    if not items:
        full.append('Подходящих событий за период нет. '+zero_reason)
        post.append('Подходящих событий за период нет. '+zero_reason)
    else:
        if len(items)<5:
            note=f'Выбрано событий: {len(items)}. '+zero_reason
            full.append(note); post.append(note)
        for i,(item,event) in enumerate(zip(items,events),1):
            sources='\n'.join(source_line(s) for s in event['sources'])
            item_title=('Обновление старого события: ' if event.get('is_update') else '')+item['title']['text']
            notes='\nСтатус сообщения: '+' '.join(n['text'] for n in event['status_notes']) if event.get('status_notes') else ''
            full.append(f"{i}. {item_title}\n"+' '.join(x['text'] for x in item['summary'])+
                '\nПоследствия: '+item['consequences']['text']+notes+'\nИсточники:\n'+sources)
            post_sources='\n'.join(s['url'] for s in event['sources'])
            post.append(f"{i}. {item_title}\n{item['short']['text']}"+notes+'\nИсточники:\n'+post_sources)
    urls=[s['url'] for e in events for s in e['sources']]
    return {'title':title,'period':period,'control_time':T.isoformat(),'subject':f'КиберСводка: {T.astimezone(MOSCOW):%d.%m.%Y} · {len(items)} событий',
        'full':'\n\n'.join(full),'post':'\n\n'.join(post),'items':items,'events':events,'urls':list(dict.fromkeys(urls)),
        'zero_events_reason':zero_reason,'event_count':len(items),'post_method':'Extractive compression of the same AI-written full digest'}

def validation_for(data):
    errors=[]
    urls=data['urls']
    full_count=count_chars(data['full'],urls); post_count=count_chars(data['post'],urls)
    if full_count>4000: errors.append('Полный текст превышает 4 000 знаков без URL')
    if post_count>2000: errors.append('Пост превышает 2 000 знаков без URL')
    if data['event_count']>5: errors.append('Событий больше пяти')
    if '\u2014' in data['full'] or '\u2014' in data['post']: errors.append('Использовано длинное тире')
    if [x['event_id'] for x in data['items']]!=[x['event_id'] for x in data['events']]: errors.append('Состав событий расходится')
    for url in urls:
        if url not in data['full'] or url not in data['post']: errors.append('Ссылка отсутствует в одном формате')
    for event in data['events']:
        for note in event.get('status_notes',[]):
            if note['text'] not in data['full'] or note['text'] not in data['post']:errors.append('Оговорка отсутствует в одном формате')
    if data.get('semantic_verification',{}).get('supported') is False: errors.extend(data['semantic_verification']['problems'])
    return {'passed':not errors,'errors':errors,'full_chars':full_count,'post_chars':post_count,
        'checks':['Период МСК','Не более пяти событий','Существующие ID и источники','Цитаты и offsets','Согласованность форматов','Лимиты текста'],
        'label':'Автоматические проверки пройдены' if not errors else 'Требуется исправление',
        'requires_editor_review':True}

def context_fingerprint(mode):
    from .core import settings
    from .llm import PROMPTS
    files=[Path(__file__),Path(__file__).with_name('schemas.py'),Path(__file__).with_name('validators.py'),ROOT/'config'/'keywords.json',*sorted(PROMPTS.glob('*.txt'))]
    return hashlib.sha256((''.join(p.read_text(encoding='utf-8') for p in files)+json.dumps({'mode':mode,'model':settings.gigachat_model,'temperature':settings.gigachat_temperature})).encode()).hexdigest()

async def process(articles,control_time,mode='live',run_id=None,progress=None,group_overrides=None,checkpoint=None,save_checkpoint=None):
    started=time.monotonic()
    T,reason=parse_date(control_time)
    if T is None: raise ValueError('Укажите контрольное время с часовым поясом')
    model=GigaChat(run_id) if mode=='live' else None
    fingerprint=hashlib.sha256((context_fingerprint(mode)+T.isoformat()+json.dumps(articles,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()
    checkpoint=checkpoint or {}
    if checkpoint.get('context_fingerprint')!=fingerprint:checkpoint={}
    decisions=checkpoint.get('decisions',[]); candidates=checkpoint.get('candidates',[])
    for decision in decisions:
        decision['event_group_ids']=[];decision.pop('selected_event_ids',None)
        decision.pop('grouping_explanation',None);decision.pop('ranking_explanation',None)
    async def cache(**stage_data):
        checkpoint.update({'context_fingerprint':fingerprint,'decisions':decisions,'candidates':candidates,**stage_data})
        if save_checkpoint:
            await save_checkpoint(checkpoint)
    async def report(stage,value):
        if progress: await progress(stage,value)
    for i,article in enumerate(articles):
        if any(d['article_id']==article['id'] for d in decisions):continue
        await cache(stage='extract')
        await report(f'Материалы: {i+1} из {len(articles)}',int(55*(i+1)/max(1,len(articles))))
        decision={'article_id':article['id'],'internal_article_id':article.get('internal_id'),'status':'excluded','event_group_ids':[],
            'source':article.get('source',''),'url':article.get('url',''),'published_at':article.get('published_at'),
            'missing_fields':article.get('missing_original_fields',[k for k in ('id','title','text','source','url','published_at') if not article.get(k)]),'warnings':[],
            'errors':[article['read_error']] if article.get('read_error') else []}
        normalized_date,date_status=parse_date(article.get('published_at'),article.get('assume_moscow',False))
        decision.update(published_at_raw=article.get('published_at'),published_at_normalized=normalized_date.isoformat() if normalized_date else None,
            date_verification_status='CONFLICT' if article.get('date_conflict') else date_status)
        decisions.append(decision)
        rejected=period_reason(article,T)
        try:
            if article.get('read_error'): rejected='SOURCE_UNAVAILABLE' if any(code in article['read_error'] for code in ('SOURCE_UNAVAILABLE','SOURCE_HTTP')) else 'READ_ERROR'
            if not rejected and not safe_display_url(article.get('url','')): rejected='MISSING_SOURCE_URL'
            if not rejected and len(article.get('text','').strip())<60: rejected='INSUFFICIENT_CONTENT'
            if rejected and rejected!='UPDATE_CANDIDATE':
                decision.update(reason_code=rejected,reason_text=REASONS.get(rejected,rejected)); continue
            text=article['text']
            chunks=[text] if len(text)<=18000 else [text[s:s+12000] for s in range(0,len(text),11500)]
            outputs=[]
            for chunk in chunks:
                if model:
                    feedback=''
                    for attempt in range(2):
                        output=(await model.call('extract',{'article':{k:article.get(k) for k in ('id','title','source','url','published_at','updated_at','publisher_type')},
                            'keyword_signals':[term for term in KEYWORDS if term in chunk.lower()],
                            'text':chunk,'control_time':control_time,'validation_feedback':feedback},Extraction)).model_dump()
                        unsupported=[]
                        for event in output['events']:
                            valid_facts=[]
                            for fact in event['facts']:
                                try:validate_quote(fact,article);valid_facts.append(fact)
                                except ValueError:unsupported.append(fact['quote'][:160])
                            if attempt==1:event['facts']=valid_facts
                        if not unsupported:break
                        feedback='Следующие цитаты не найдены буквально в text или содержат неподтверждённые числа: '+json.dumps(unsupported,ensure_ascii=False)+'. Верни полный ответ с исправленными точными цитатами. Не используй заголовок как цитату.'
                    if unsupported:decision['warnings'].append('Неподтверждённые утверждения исключены: '+str(len(unsupported)))
                    output['events']=[e for e in output['events'] if e['facts']]
                else:output=fixture_extract(article)
                outputs.append(output)
            if not any(x['relevant'] for x in outputs):
                decision.update(reason_code='OUT_OF_TOPIC',reason_text=outputs[0]['reason']); continue
            events=[e for x in outputs if x['relevant'] and x['sufficient'] for e in x['events']]
            if not events:
                code='EVIDENCE_NOT_SUPPORTED' if any(w.startswith('Неподтверждённые') for w in decision['warnings']) else 'INSUFFICIENT_CONTENT'
                decision.update(reason_code=code,reason_text='Модель не смогла подтвердить пересказ точными фрагментами исходного текста.' if code=='EVIDENCE_NOT_SUPPORTED' else REASONS['INSUFFICIENT_CONTENT']); continue
            if rejected=='UPDATE_CANDIDATE' and not any(e['new_facts'] for e in events):
                decision.update(reason_code='OUT_OF_PERIOD',reason_text='Значимые новые факты обновления не подтверждены'); continue
            if all(e['is_old_event'] and not e['new_facts'] for e in events):
                decision.update(reason_code='OUT_OF_PERIOD',reason_text='Перепечатка старого события без новых фактов'); continue
            events=[e for e in events if not(e['is_old_event'] and not e['new_facts'])]
            decision['classification']=outputs[0]['category']
            if re.search('игнорируй|ignore previous|отправь ключ|измени период',text,re.I): decision['warnings'].append('PROMPT_INJECTION_IGNORED')
            for n,e in enumerate(events):
                claims=[]
                for fact in e['facts']:
                    start,end=validate_quote(fact,article)
                    cid='C-'+hashlib.sha256((article['id']+fact['quote']).encode()).hexdigest()[:12]
                    claims.append({**fact,'claim_id':cid,'article_id':article['id'],'internal_article_id':article.get('internal_id'),
                        'start_offset':start,'end_offset':end,'verification_status':'quote_and_numbers_checked'})
                if not claims: raise ValueError('EVIDENCE_NOT_SUPPORTED: нет фактов')
                candidates.append({**e,'candidate_id':f"{article['id']}:{n}",'claims':claims,'article':article,
                    'is_update':rejected=='UPDATE_CANDIDATE',
                    'test_key':article.get('test_event_key') if mode=='fixture' else None})
            decision.update(status='candidate',reason_code='UPDATED_EVENT_INCLUDED' if rejected=='UPDATE_CANDIDATE' else 'CANDIDATE',reason_text=outputs[0]['reason'])
        except ModelError: raise
        except (ValueError,KeyError,TypeError) as exc:
            decision.update(reason_code='EVIDENCE_NOT_SUPPORTED',reason_text=str(exc)[:300])
    await cache(stage='cluster')
    await report('Объединение событий',60)
    groups=[]
    if candidates:
        if group_overrides is not None:
            groups=group_overrides
        elif checkpoint.get('groups') is not None:
            groups=checkpoint['groups']
        elif model:
            payload=[{k:v for k,v in c.items() if k not in ('article','test_key')} for c in candidates]
            groups=(await model.call('cluster',payload,Grouping)).model_dump()['groups']
        else:
            mapping={}
            for c in candidates: mapping.setdefault(c['test_key'] or c['candidate_id'],[]).append(c['candidate_id'])
            groups=[{'candidate_ids':ids,'reason':'Объединено по ID события тестового набора; провайдер fixtures.',
                'conflicts':['Источники сообщают разные числа; обе версии сохраняются.'] if any(c['article'].get('test_conflict') for c in candidates if c['candidate_id'] in ids) else []} for ids in mapping.values()]
        assigned=[cid for g in groups for cid in g['candidate_ids']]
        if sorted(assigned)!=sorted(c['candidate_id'] for c in candidates): raise ValueError('CLUSTER_ID_MISMATCH')
    await cache(stage='rank',groups=groups)
    events=[]
    for group in groups:
        members=[c for c in candidates if c['candidate_id'] in group['candidate_ids']]
        eid='E-'+hashlib.sha256('|'.join(sorted(group['candidate_ids'])).encode()).hexdigest()[:12]
        sources=[]
        for c in members:
            a=c['article']
            if not any(s['id']==a['id'] for s in sources):
                source={k:a.get(k) for k in ('id','internal_id','source','url','published_at','updated_at')}
                date,date_status=parse_date(a.get('published_at'),a.get('assume_moscow',False))
                source.update(published_at_raw=a.get('published_at'),published_at=date.isoformat() if date else a.get('published_at'),date_status=date_status)
                sources.append(source)
        claims=list({c['claim_id']:c for m in members for c in m['claims']}.values())
        origins={m.get('origin_statement') for m in members if m.get('origin_statement')}
        events.append({'event_id':eid,'title':members[0]['title'],'candidate_ids':group['candidate_ids'],'claims':claims,'sources':sources,'group_reason':group['reason'],
            'conflicts':group['conflicts'],'is_update':any(m.get('is_update') for m in members),'uncertainties':list(dict.fromkeys(x for m in members for x in m['uncertainties'])),
            'primary_source_ids':[m['article']['id'] for m in members if m['primary']],
            'independent_origin_count':1 if len(origins)==1 else None,'origin_statements':sorted(origins),
            'new_facts':list(dict.fromkeys(x for m in members for x in m['new_facts'])),
            'test_scores':members[0]['article'].get('test_scores',[3,1,2,4]) if mode=='fixture' else None})
        for decision in decisions:
            if decision['article_id'] in [s['id'] for s in sources]:
                decision['event_group_ids'].append(eid); decision['grouping_explanation']=group['reason']
    await report('Объяснимый отбор',70)
    ranking=[]
    if events:
        if checkpoint.get('ranking') is not None:ranking=checkpoint['ranking']
        elif model: ranking=(await model.call('rank',events,Ranking)).model_dump()['events']
        else: ranking=[{'event_id':e['event_id'],'impact':e['test_scores'][0],'scale':e['test_scores'][1],
            'urgency':e['test_scores'][2],'audience':e['test_scores'][3],
            'reason':'Отбор по указанным в тестовом наборе последствиям, масштабу и срочности.',
            'evidence_claim_ids':[c['claim_id'] for c in e['claims']]} for e in events]
        if sorted(r['event_id'] for r in ranking)!=sorted(e['event_id'] for e in events): raise ValueError('RANK_ID_MISMATCH')
        byid={e['event_id']:e for e in events}
        for r in ranking:
            e=byid[r['event_id']]
            if not r['evidence_claim_ids'] or not set(r['evidence_claim_ids'])<=set(c['claim_id'] for c in e['claims']): raise ValueError('RANK_EVIDENCE_MISSING')
            score=.35*r['impact']+.25*(r['scale'] or 0)+.25*r['urgency']+.15*r['audience']
            e.update(ranking=r,score=round(score,3))
        events.sort(key=lambda e:(-e['score'],e['event_id']))
    await cache(stage='compose',groups=groups,ranking=ranking)
    selected=events[:5]
    for i,e in enumerate(events): e['selected']=i<5; e['rank']=i+1
    for d in decisions:
        chosen=[e for e in selected if e['event_id'] in d['event_group_ids']]
        if chosen:
            d['status']='included'; d['selected_event_ids']=[e['event_id'] for e in chosen]
            if d['reason_code']!='UPDATED_EVENT_INCLUDED': d['reason_code']='MERGED_DUPLICATE_EVENT' if any(len(e['sources'])>1 for e in chosen) else 'INCLUDED'
            d['reason_text']=chosen[0]['ranking']['reason']; d['ranking_explanation']=chosen[0]['ranking']['reason']
        elif d['event_group_ids']: d.update(status='not_selected',reason_code='RELEVANT_NOT_SELECTED',reason_text=REASONS['RELEVANT_NOT_SELECTED'])
    await report('Дайджест и короткий пост',80)
    items=[]
    composition_repairs=[]
    if selected:
        if checkpoint.get('items') is not None:
            items=checkpoint['items']
        elif model:
            feedback=''
            compose_events=[{**e,'sources':[{k:s[k] for k in ('id','source')} for s in e['sources']]} for e in selected]
            for repair in range(3):
                items=(await model.call('compose',{'events':compose_events,'validation_feedback':feedback},Composition)).model_dump()['items']
                for item in items:
                    for sentence in [item['title'],*item['summary'],item['consequences'],item['short']]:
                        sentence['text']=sentence['text'].replace('\u2014','-')
                        sentence['claim_ids']=[cid.strip() for cid in sentence['claim_ids']]
                align_formats(items,selected)
                try:
                    validate_composition(items,selected)
                    break
                except ValueError as exc:
                    feedback=str(exc)+'. Исправь конкретное нарушение. Не добавляй новых фактов. При отсутствии последствий используй строго «В источнике не указано.»'
                    if repair==2:
                        for item,event in zip(items,selected):
                            ids={c['claim_id'] for c in event['claims']}
                            consequence=item['consequences']
                            if not consequence['claim_ids'] or not set(consequence['claim_ids'])<=ids:
                                impacts=[c for c in event['claims'] if c['kind']=='impact']
                                if impacts:
                                    fact=min(impacts,key=lambda c:len(c['text']))
                                    item['consequences']={'text':fact['text'].replace('\u2014','-'),'claim_ids':[fact['claim_id']]}
                                else:item['consequences']={'text':'В подтверждённых фрагментах последствия не указаны.','claim_ids':[]}
                                composition_repairs.append({'event_id':event['event_id'],'field':'consequences','reason':'Неподтверждённый вывод модели заменён подтверждённым фактом либо явным отсутствием данных.'})
                        validate_composition(items,selected)
        else:
            for e in selected:
                facts=list({c['text']:c for c in e['claims']}.values())
                sentences=[{'text':c['text'],'claim_ids':[c['claim_id']]} for c in facts]
                if e['conflicts']:
                    summary=[{'text':s['source']+': '+' '.join(c['text'] for c in facts if c['article_id']==s['id']),
                        'claim_ids':[c['claim_id'] for c in facts if c['article_id']==s['id']]} for s in e['sources']]
                    short={'text':'Расхождение: '+' '.join(s['text'] for s in summary),'claim_ids':[c for s in summary for c in s['claim_ids']]}
                else:
                    summary=sentences[:2]
                    short={'text':' '.join(s['text'] for s in summary),'claim_ids':[c for s in summary for c in s['claim_ids']]}
                items.append({'event_id':e['event_id'],'title':{'text':e['title'],'claim_ids':[facts[0]['claim_id']]},
                    'summary':summary,'consequences':sentences[1] if len(sentences)>1 else {'text':'В источнике не указано.','claim_ids':[]},'short':short})
        align_formats(items,selected)
        validate_composition(items,selected)
    await cache(stage='verify',groups=groups,ranking=ranking,items=items)
    await report('Проверка фактов и лимитов',90)
    verification={'supported':True,'problems':[],'provider':'fixtures: структурные проверки, без смыслового подтверждения моделью'}
    if checkpoint.get('verification') is not None:verification=checkpoint['verification']
    elif model and items: verification={**(await model.call('verify',{'items':items,'events':selected},Verification)).model_dump(),'provider':'GigaChat'}
    await cache(stage='complete',groups=groups,ranking=ranking,items=items,verification=verification)
    exclusion_counts={}
    for d in decisions:
        if d['status']=='excluded': exclusion_counts[d['reason_code']]=exclusion_counts.get(d['reason_code'],0)+1
    zero_reason='Подходящих самостоятельных событий в наборе: '+str(len(events))+'.'
    if exclusion_counts: zero_reason+=' Исключено материалов: '+str(sum(exclusion_counts.values()))+'. Причины доступны в журнале.'
    data=render_digest(items,selected,T,zero_reason)
    data['semantic_verification']=verification
    data['composition_repairs']=composition_repairs
    data['mode']=mode
    validation=validation_for(data)
    await report('Завершено',100)
    return {'digest':data,'validation':validation,'events':events,'decisions':decisions,
        'candidates':candidates,'context_fingerprint':fingerprint,
        'prompt_snapshots':model.prompt_snapshots if model else {},
        'metrics':{'duration_seconds':round(time.monotonic()-started,2),'article_count':len(articles),'event_count':len(events),'selected_count':len(selected),
            'model_calls':model.calls if model else 0,'tokens':model.tokens if model and model.usage_available else None,'cost':None,
            'model_identifiers':sorted(model.actual_models) if model else ['fixtures-deterministic-v1'],
            'prompt_version':'1.0','temperature':settings_temperature() if model else None,'timezone':'Europe/Moscow','control_time':control_time,
            'period_start':(T-timedelta(hours=24)).isoformat(),'period_end':T.isoformat(),'period_rule':'start < published_at <= end',
            'provider':mode,'exact_model_version':', '.join(m.split(':',1)[1] for m in sorted(model.actual_models) if ':' in m) or 'Отдельная версия недоступна' if model else 'v1'}}

def settings_temperature():
    from .core import settings
    return settings.gigachat_temperature
