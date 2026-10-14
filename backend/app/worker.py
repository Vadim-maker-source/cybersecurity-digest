import asyncio, json, smtplib, ssl, time
from datetime import timedelta,datetime,timezone
from sqlalchemy import select,update,text as sqltext
from .models import Session,Job,Run,Digest,Event,Claim,ArticleEvent,Source,Audit,Schedule,Article,Dataset,ModelCall,Subscriber,engine
from .core import now,uid,settings
from .service import import_records,enqueue,article_data,load_runtime_settings
from .pipeline import process
from .parsers import collect_source,fetch,robots_allowed,article_html
from .fixtures import CASES,CONTROL
from .exports import email_message
from .mail import connection as smtp_connection
from .validators import MOSCOW,parse_date

class Cancelled(Exception): pass

async def progress(job_id,stage,value):
    async with Session() as db:
        job=await db.get(Job,job_id)
        if job.status=='cancelled': raise Cancelled()
        job.stage=stage; job.progress=value; job.heartbeat=now(); await db.commit()

async def heartbeat(job_id):
    while True:
        await asyncio.sleep(15)
        async with Session() as db:
            await db.execute(update(Job).where(Job.id==job_id,Job.status=='running').values(heartbeat=now())); await db.commit()

async def run_processing(job):
    async with Session() as db:
        run=await db.get(Run,job.payload['run_id'])
        if run.status=='succeeded':
            digest=await db.scalar(select(Digest).where(Digest.run_id==run.id).order_by(Digest.created_at.desc()).limit(1))
            return {'run_id':run.id,'digest_id':digest.id,'validation':digest.validation}
        run.status='running'; await db.commit()
        articles=run.snapshot; control=run.control_time.isoformat(); mode=run.mode
        dataset_kind=(await db.get(Dataset,run.dataset_id)).kind
        checkpoint=run.result.get('_checkpoint')
    async def save_checkpoint(data):
        async with Session() as db:
            current=await db.get(Run,run.id)
            current.result={'_checkpoint':data};current.decisions=data['decisions']
            await db.commit()
    result=await process(articles,control,mode,run.id,lambda s,p:progress(job.id,s,p),job.payload.get('group_overrides'),checkpoint,save_checkpoint)
    result['dataset_kind']=dataset_kind
    await progress(job.id,'Сохранение результата',98)
    async with Session() as db:
        run=await db.get(Run,run.id)
        calls=(await db.scalars(select(ModelCall).where(ModelCall.run_id==run.id))).all()
        if calls:
            result['metrics']['model_calls']=len(calls)
            result['metrics']['model_identifiers']=sorted(set(c.model for c in calls))
            result['metrics']['exact_model_version']=', '.join(sorted(set(c.model.split(':',1)[1] for c in calls if ':' in c.model))) or 'Отдельная версия недоступна'
            result['metrics']['tokens']=sum((c.usage or {}).get('total_tokens',0) for c in calls) if all(c.usage is not None for c in calls if c.status=='received') else None
        run.status='succeeded'; run.result=result; run.decisions=result['decisions']; run.metrics=result['metrics']
        for event in result['events']:
            record=Event(id=uid(),run_id=run.id,rank=event['rank'],selected=event['selected'],data=event)
            db.add(record); await db.flush()
            for source in event['sources']:
                if source.get('internal_id'): db.add(ArticleEvent(event_id=record.id,article_id=source['internal_id']))
            for claim in event['claims']:
                if claim.get('internal_article_id'):
                    db.add(Claim(event_id=record.id,article_id=claim['internal_article_id'],text=claim['text'],quote=claim['quote'],
                        start_offset=claim['start_offset'],end_offset=claim['end_offset'],status=claim['verification_status'],data=claim))
        digest=Digest(id=uid(),run_id=run.id,data=result['digest'],validation=result['validation'],
            status='needs_review' if result['validation']['passed'] else 'validation_failed')
        db.add(digest); await db.commit()
        return {'run_id':run.id,'digest_id':digest.id,'validation':result['validation']}

async def run_tests(job):
    results=[]
    mode=job.payload.get('mode','fixture')
    if not settings.enable_demo:raise ValueError('DEMO_DISABLED')
    config_before=(settings.recipient_allowlist,settings.gigachat_scope,settings.public_base_url)
    for i,case in enumerate(CASES):
        await progress(job.id,case['name'],int(100*i/len(CASES)))
        started=now().isoformat()
        try:
            output=await process(case['articles'],CONTROL,mode,run_id=job.id)
            expected=case['expected']; failures=[]
            if output['digest']['event_count']!=expected['count']: failures.append('Число событий')
            if not output['validation']['passed']: failures.extend(output['validation']['errors'])
            if expected.get('sources') and len(output['digest']['events'][0]['sources'])!=expected['sources']: failures.append('Ссылки дубликатов')
            if expected.get('reason') and not any(d['reason_code']==expected['reason'] for d in output['decisions']): failures.append('Причина исключения')
            if expected.get('updated') and not any(d['reason_code']=='UPDATED_EVENT_INCLUDED' for d in output['decisions']): failures.append('Обновление старого события')
            if expected.get('conflict') and not ('100' in output['digest']['post'] and '300' in output['digest']['post']): failures.append('Потеряна альтернативная версия')
            if expected.get('injection'):
                if config_before!=(settings.recipient_allowlist,settings.gigachat_scope,settings.public_base_url): failures.append('Изменилась конфигурация')
                if 'hacker@fixture.invalid' in output['digest']['full']: failures.append('Инструкция попала в дайджест')
                if not any('PROMPT_INJECTION_IGNORED' in d['warnings'] for d in output['decisions']): failures.append('Инструкция не отмечена')
            results.append({'case_id':case['id'],'name':case['name'],'status':'failed' if failures else 'passed','failures':failures,
                'input':case['articles'],'expected':expected,'output':output,'started_at':started})
        except Exception as exc:
            results.append({'case_id':case['id'],'name':case['name'],'status':'failed','failures':[safe_error(exc)],'input':case['articles'],'expected':case['expected'],'output':None,'started_at':started})
    result={'mode':mode,'results':results,'passed':sum(x['status']=='passed' for x in results),'total':len(results),'finished_at':now().isoformat(),
        'prompts_version':'1.0','control_time':CONTROL,'config_invariant':config_before==(settings.recipient_allowlist,settings.gigachat_scope,settings.public_base_url)}
    async with Session() as db:
        db.add(Audit(kind='test_results',entity_id=job.id,data=result)); await db.commit()
    return result

async def run_collect(job):
    async with Session() as db:
        source=await db.get(Source,job.payload['source_id'])
        if not source.agreed or not source.enabled: raise ValueError('Источник должен быть согласован и включён редактором')
        data={'name':source.name,'url':source.url,'feed_url':source.feed_url,'meta':source.meta,'publisher_type':source.publisher_type}
    articles,errors=await collect_source(data,job.payload.get('limit',3))
    async with Session() as db:
        source=await db.get(Source,source.id); source.last_checked=now()
        source.meta={**source.meta,'last_collection':{'count':len(articles),'errors':errors,'checked_at':now().isoformat()}}
        dataset,result=await import_records(db,articles,source.name+' · '+now().strftime('%d.%m %H:%M'),'live',{'source_id':source.id,'errors':errors})
        await db.commit()
    return {'dataset_id':dataset.id,'count':len(articles),'errors':errors}

async def run_url(job):
    url=job.payload['url']
    await asyncio.to_thread(robots_allowed,url)
    raw,final,_=await asyncio.to_thread(fetch,url)
    article=await asyncio.to_thread(article_html,raw,final)
    article['source']=job.payload.get('source') or final.split('/')[2]
    async with Session() as db:
        dataset,result=await import_records(db,[article],article['title'] or 'URL-импорт','live'); await db.commit()
    return {'dataset_id':dataset.id,**result}

async def run_daily(job):
    if job.payload.get('run_id'):return await run_processing(job)
    async with Session() as db:
        sources=(await db.scalars(select(Source).where(Source.agreed==True,Source.enabled==True))).all()
        configs=[{'id':s.id,'name':s.name,'url':s.url,'feed_url':s.feed_url,'meta':s.meta} for s in sources]
    articles=[];errors=[]
    for i,s in enumerate(configs):
        await progress(job.id,'Сбор: '+s['name'],int(20*i/max(1,len(configs))))
        try:
            found,issues=await collect_source(s,3)
            articles.extend(found);errors.extend(issues)
        except Exception as exc:errors.append({'source':s['name'],'reason':safe_error(exc)})
    T,_=parse_date(job.payload['control_time'])
    async with Session() as db:
        dataset,_=await import_records(db,articles,'Ежедневный сбор · '+T.astimezone(MOSCOW).strftime('%d.%m.%Y'),'live',{'errors':errors,'source_ids':[s['id'] for s in configs]})
        records=(await db.scalars(select(Article).where(Article.dataset_id==dataset.id))).all()
        run=Run(id=uid(),dataset_id=dataset.id,mode='live',control_time=T,snapshot=[article_data(a) for a in records])
        db.add(run);await db.flush()
        current=await db.get(Job,job.id);current.payload={**current.payload,'run_id':run.id};job.payload=current.payload
        await db.commit()
    result=await run_processing(job);result['errors']=errors
    return result

def send_mail(data,recipient):
    with smtp_connection() as smtp:
        smtp.send_message(email_message(data,recipient))
    return {'status':'accepted_by_smtp','recipient':recipient,'message':'SMTP принял письмо; доставка в папку входящих не подтверждена'}

async def run_email(job):
    async with Session() as db:
        digest=await db.get(Digest,job.payload['digest_id'])
        if digest.status!='approved' or digest.revision!=job.payload['revision']: raise ValueError('Выпуск изменился или не утверждён')
        recipient=job.payload['recipient'].lower()
        registered=await db.scalar(select(Subscriber.id).where(Subscriber.email==recipient,Subscriber.active==True))
        allowed={x.strip().lower() for x in settings.recipient_allowlist.split(',') if x.strip()}
        if not registered and recipient not in allowed:raise ValueError('RECIPIENT_NOT_REGISTERED')
        data=digest.data
    await progress(job.id,'Отправка письма',50)
    result=await asyncio.to_thread(send_mail,data,job.payload['recipient'])
    async with Session() as db:
        db.add(Audit(kind='email_delivery',entity_id=digest.id,data=result)); await db.commit()
    return result

def safe_error(exc):
    value=str(exc)[:400]
    for secret in [settings.gigachat_auth_key,settings.smtp_password,settings.session_secret,settings.bootstrap_admin_password]:
        if secret: value=value.replace(secret,'[скрыто]')
    return value or type(exc).__name__

async def scheduler_tick():
    async with Session() as db:
        schedules=(await db.scalars(select(Schedule).where(Schedule.enabled==True,Schedule.next_run<=now()).with_for_update(skip_locked=True))).all()
        for schedule in schedules:
            T=schedule.next_run
            if schedule.dataset_id:
                dataset=await db.get(Dataset,schedule.dataset_id)
                articles=(await db.scalars(select(Article).where(Article.dataset_id==schedule.dataset_id))).all()
                run=Run(id=uid(),dataset_id=schedule.dataset_id,mode=schedule.mode,control_time=T,snapshot=[article_data(a) for a in articles])
                db.add(run); await db.flush()
                await enqueue(db,'process',{'run_id':run.id},f'schedule:{schedule.id}:{T.isoformat()}')
            else:
                await enqueue(db,'daily',{'schedule_id':schedule.id,'control_time':T.isoformat()},f'schedule:{schedule.id}:{T.isoformat()}')
            schedule.last_run=T; schedule.next_run=T+timedelta(days=1)
        sources=(await db.scalars(select(Source).where(Source.enabled==True,Source.agreed==True).with_for_update(skip_locked=True))).all()
        for source in sources:
            if not source.meta.get('auto_collect'):continue
            T,_=parse_date(source.meta.get('next_collect_at'))
            if T and T<=now():
                await enqueue(db,'collect',{'source_id':source.id,'limit':3},f'auto-collect:{source.id}:{T.isoformat()}')
                source.meta={**source.meta,'next_collect_at':(now()+timedelta(minutes=source.meta.get('collect_interval_minutes',60))).isoformat()}
        if settings.auto_send_enabled and settings.smtp_host:
            allowed={x.strip().lower() for x in settings.recipient_allowlist.split(',') if x.strip()}
            subscribers=(await db.scalars(select(Subscriber).where(Subscriber.active==True))).all()
            digests=(await db.scalars(select(Digest).where(Digest.status=='approved',Digest.created_at>now()-timedelta(days=1)))).all()
            for digest in digests:
                for subscriber in subscribers:
                    await enqueue(db,'email',{'digest_id':digest.id,'recipient':subscriber.email,'revision':digest.revision},f'email:{digest.id}:{digest.revision}:{subscriber.email}')
        await db.commit()

async def main():
    print('CyberSvodka worker ready',flush=True)
    async with engine.connect() as lock_connection:
        # A global advisory lock limits prototype to one active worker and one live model call at a time.
        locked=await lock_connection.scalar(sqltext('SELECT pg_try_advisory_lock(673252)'))
        if not locked: raise RuntimeError('Другой worker уже работает')
        while True:
            await scheduler_tick()
            async with Session() as db:
                await db.execute(update(Job).where(Job.status=='running',Job.heartbeat<now()-timedelta(minutes=3)).values(status='queued',stage='Восстановление после остановки'))
                job=await db.scalar(select(Job).where(Job.status=='queued').order_by(Job.created_at).limit(1).with_for_update(skip_locked=True))
                if job:
                    job.status='running'; job.heartbeat=now(); job.attempts+=1; await db.commit()
            if not job: await asyncio.sleep(1); continue
            heart=asyncio.create_task(heartbeat(job.id))
            try:
                await load_runtime_settings()
                handlers={'process':run_processing,'daily':run_daily,'tests':run_tests,'collect':run_collect,'url':run_url,'email':run_email}
                result=await handlers[job.kind](job)
                async with Session() as db:
                    current=await db.get(Job,job.id)
                    if current.status!='cancelled':
                        current.status='partially_succeeded' if result.get('errors') else 'succeeded'
                        current.result=result; current.progress=100; current.stage='Завершено'; current.finished_at=now()
                    await db.commit()
            except Exception as exc:
                async with Session() as db:
                    current=await db.get(Job,job.id)
                    current.status='cancelled' if isinstance(exc,Cancelled) else 'failed'
                    current.error=safe_error(exc); current.finished_at=now()
                    if job.kind=='process':
                        run=await db.get(Run,job.payload['run_id']); run.status=current.status
                        run.metrics={**run.metrics,'error':current.error}
                    await db.commit()
                print('Job failed:',job.kind,safe_error(exc),flush=True)
            finally: heart.cancel()

if __name__=='__main__': asyncio.run(main())
