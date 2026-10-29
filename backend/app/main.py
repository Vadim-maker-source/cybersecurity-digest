import asyncio, hashlib, io, json, re, secrets, time
from contextlib import asynccontextmanager
from datetime import datetime,timedelta
from urllib.parse import urlsplit
from fastapi import FastAPI,Depends,HTTPException,Request,UploadFile,File,Form
from fastapi.responses import Response,HTMLResponse,JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select,func,text as sqltext
from argon2.exceptions import VerificationError
from .models import Session,User,Dataset,Article,Source,Run,Digest,Job,Schedule,Subscriber,Audit,Event,ModelCall
from .core import settings,uid,now,iso
from .service import hasher,seed,import_records,enqueue,article_data,load_runtime_settings
from .validators import parse_date,MOSCOW
from .fixtures import DEMO,CONTROL,CASES
from .pipeline import validation_for,render_digest
from .llm import GigaChat,ModelError
from .schemas import Verification
from .parsers import parse_import
from .exports import safe_package,email_html,email_message,log_csv
from .mail import check_connection
from .verification import verify_sources
from .public import public_digest

@asynccontextmanager
async def lifespan(app):
    await seed()
    await load_runtime_settings()
    yield

app=FastAPI(title='КиберСводка API',version='1.0.0',lifespan=lifespan,docs_url='/api/docs',openapi_url='/api/openapi.json')
app.add_middleware(SessionMiddleware,secret_key=settings.session_secret,session_cookie='cyber_session',same_site='lax',https_only=settings.cookie_secure,max_age=8*3600)

@app.exception_handler(ValueError)
async def bad_value(request,exc): return JSONResponse({'detail':str(exc)[:400]},status_code=422)

@app.exception_handler(ModelError)
async def model_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=503)

async def db_session():
    async with Session() as db: yield db

async def user(request:Request,db=Depends(db_session)):
    id=request.session.get('user_id')
    if id=='demo-viewer' and settings.enable_demo and settings.app_env=='local': return {'id':id,'email':'Демонстрационный просмотр','role':'viewer'}
    record=await db.get(User,id) if id else None
    if not record: raise HTTPException(401,'Войдите в рабочий кабинет')
    if request.method not in ('GET','HEAD','OPTIONS'):
        if request.headers.get('X-CSRF-Token')!=request.session.get('csrf'): raise HTTPException(403,'CSRF token отсутствует или неверен')
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc not in {request.url.netloc,urlsplit(settings.public_base_url).netloc,'localhost:6752','127.0.0.1:6752'}:
            raise HTTPException(403,'Недопустимый Origin')
    return {'id':record.id,'email':record.email,'role':record.role}

async def editor(u=Depends(user)):
    if u['role'] not in ('admin','editor'): raise HTTPException(403,'Требуется роль редактора')
    return u

async def admin(u=Depends(editor)):
    if u['role']!='admin': raise HTTPException(403,'Требуется роль администратора')
    return u

def out_job(job):
    return {'id':job.id,'kind':job.kind,'status':job.status,'stage':job.stage,'progress':job.progress,'payload':job.payload,
        'result':job.result,'error':job.error,'created_at':iso(job.created_at),'finished_at':iso(job.finished_at)}

def out_digest(d):
    return {'id':d.id,'run_id':d.run_id,'revision':d.revision,'status':d.status,'created_at':iso(d.created_at),'data':d.data,'validation':d.validation}

login_attempts={}
@app.post('/api/v1/auth/login')
async def login(body:dict,request:Request,db=Depends(db_session)):
    key=request.client.host+':'+str(body.get('email','')).lower()
    hits=[x for x in login_attempts.get(key,[]) if x>time.time()-60]
    if len(hits)>=8: raise HTTPException(429,'Слишком много попыток. Повторите через минуту.')
    login_attempts[key]=hits+[time.time()]
    u=await db.scalar(select(User).where(User.email==body.get('email','').lower()))
    valid=False
    if u:
        try: valid=await asyncio.to_thread(hasher.verify,u.password_hash,str(body.get('password','')))
        except VerificationError: pass
    if not valid: raise HTTPException(401,'Неверный адрес или пароль')
    request.session.clear(); request.session['user_id']=u.id; request.session['csrf']=secrets.token_urlsafe(32)
    return {'user':{'email':u.email,'role':u.role},'csrf':request.session['csrf']}

@app.post('/api/v1/auth/demo')
async def demo_login(request:Request):
    if not settings.enable_demo or settings.app_env!='local': raise HTTPException(404)
    request.session.clear();request.session['user_id']='demo-viewer';request.session['csrf']=secrets.token_urlsafe(32)
    return {'role':'viewer','csrf':request.session['csrf']}

@app.get('/api/v1/auth/me')
async def me(request:Request,u=Depends(user)): return {'user':u,'csrf':request.session.get('csrf')}

@app.post('/api/v1/auth/logout')
async def logout(request:Request,u=Depends(user)):
    request.session.clear(); return {'ok':True}

@app.get('/api/v1/health/live')
async def live(): return {'status':'ok'}

@app.get('/api/v1/health/ready')
async def ready(db=Depends(db_session)):
    await db.execute(sqltext('SELECT 1')); return {'status':'ok','database':'postgresql'}

@app.get('/api/v1/overview')
async def overview(u=Depends(user),db=Depends(db_session)):
    datasets=(await db.scalars(select(Dataset).order_by(Dataset.created_at.desc()))).all()
    digests=(await db.scalars(select(Digest).order_by(Digest.created_at.desc()).limit(20))).all()
    jobs=(await db.scalars(select(Job).order_by(Job.created_at.desc()).limit(10))).all()
    counts={'articles':await db.scalar(select(func.count()).select_from(Article)),
        'datasets':len(datasets),'events':await db.scalar(select(func.count()).select_from(Event)),
        'digests':await db.scalar(select(func.count()).select_from(Digest)),'sources':await db.scalar(select(func.count()).select_from(Source).where(Source.enabled==True))}
    return {'server_time':iso(now()),'counts':counts,'datasets':[{'id':d.id,'name':d.name,'kind':d.kind,'created_at':iso(d.created_at),'checksum':d.checksum,'meta':d.meta,
        'article_count':await db.scalar(select(func.count()).select_from(Article).where(Article.dataset_id==d.id))} for d in datasets],
        'digests':[out_digest(d) for d in digests],'jobs':[out_job(j) for j in jobs],
        'integrations':{'gigachat':bool(settings.gigachat_auth_key),'model':settings.gigachat_model,'smtp':bool(settings.smtp_host),'demo_enabled':settings.enable_demo,'app_env':settings.app_env,'public_base_url':settings.public_base_url}}

@app.get('/api/v1/public/digests')
async def public_digests(response:Response,db=Depends(db_session)):
    # Only real, successfully checked revisions; edits immediately remove a draft
    # from this view until it passes verification again.
    stmt=(select(Digest).join(Run,Digest.run_id==Run.id)
        .where(Run.mode=='live',Digest.status.in_(['needs_review','approved']),
            Digest.validation['passed'].as_boolean()==True)
        .order_by(Digest.created_at.desc()).limit(20))
    records=(await db.scalars(stmt)).all()
    response.headers['Cache-Control']='no-store'
    return {'server_time':iso(now()),'items':[public_digest(d) for d in records]}

@app.get('/api/v1/articles')
async def articles(dataset_id:str|None=None,query:str='',offset:int=0,limit:int=50,u=Depends(user),db=Depends(db_session)):
    stmt=select(Article)
    if dataset_id: stmt=stmt.where(Article.dataset_id==dataset_id)
    if query: stmt=stmt.where(Article.title.ilike('%'+query+'%'))
    total=await db.scalar(select(func.count()).select_from(stmt.subquery()))
    records=(await db.scalars(stmt.order_by(Article.published_at.desc().nullslast()).offset(max(0,offset)).limit(max(1,min(limit,100))))).all()
    return {'total':total,'items':[article_data(a) for a in records]}

@app.post('/api/v1/datasets/demo')
async def demo_dataset(u=Depends(editor),db=Depends(db_session)):
    if not settings.enable_demo or settings.app_env!='local':raise HTTPException(404)
    dataset,result=await import_records(db,DEMO,'Демонстрация · 8 тестовых материалов','test',{'control_time':CONTROL,'fictional':True})
    await db.commit();return {'dataset_id':dataset.id,**result,'control_time':CONTROL}

@app.post('/api/v1/datasets/import')
async def upload(file:UploadFile=File(...),metadata:str=Form('{}'),u=Depends(editor),db=Depends(db_session)):
    raw=await file.read(settings.max_upload_mb*1024*1024+1)
    meta=json.loads(metadata)
    records=await asyncio.to_thread(parse_import,raw,file.filename or 'file.json',meta)
    if meta.get('assume_moscow'):
        records=[{**r,'assume_moscow':True} if isinstance(r,dict) else r for r in records]
    kind=meta.get('kind','organizer')
    if kind not in ('organizer','live'): raise ValueError('Тестовый режим доступен только для встроенных fixtures')
    dataset,result=await import_records(db,records,meta.get('name',file.filename or 'Набор'),kind,{'mapping':meta.get('mapping',{}),'file_name':file.filename})
    await db.commit(); return {'dataset_id':dataset.id,**result}

@app.post('/api/v1/articles/manual')
async def manual(body:dict,u=Depends(editor),db=Depends(db_session)):
    if 'test_event_key' in body: raise ValueError('Поле тестового провайдера недопустимо')
    dataset,result=await import_records(db,[body],body.get('title','Ручной материал'),'organizer')
    await db.commit(); return {'dataset_id':dataset.id,**result}

@app.post('/api/v1/articles/url')
async def from_url(body:dict,u=Depends(editor),db=Depends(db_session)):
    job=await enqueue(db,'url',{'url':body.get('url',''),'source':body.get('source','')},body.get('idempotency_key'))
    await db.commit();return out_job(job)

@app.post('/api/v1/processing-runs',status_code=202)
async def create_run(body:dict,u=Depends(editor),db=Depends(db_session)):
    dataset=await db.get(Dataset,body.get('dataset_id'))
    if not dataset: raise HTTPException(404,'Набор не найден')
    T,reason=parse_date(body.get('control_time'))
    if not T: raise ValueError('Укажите контрольное время с часовым поясом')
    mode='fixture' if dataset.kind=='test' else 'live'
    if mode=='fixture' and not settings.enable_demo:raise HTTPException(409,'Демонстрационные данные отключены')
    if mode=='live' and (not settings.gigachat_auth_key or not settings.gigachat_model): raise HTTPException(409,'Настройте ключ и выберите модель GigaChat. Импортированные данные сохранены.')
    key=body.get('idempotency_key')
    if key:
        old=await db.scalar(select(Job).where(Job.idempotency_key==key))
        if old:return out_job(old)
    active=await db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(['queued','running']),Job.kind=='process'))
    if active>=3: raise HTTPException(429,'В очереди уже три выпуска. Дождитесь завершения.')
    records=(await db.scalars(select(Article).where(Article.dataset_id==dataset.id).order_by(Article.original_id))).all()
    if len(records)>100: raise HTTPException(422,'Один запуск ограничен 100 статьями; разделите набор')
    run=Run(id=uid(),dataset_id=dataset.id,mode=mode,control_time=T,snapshot=[article_data(a) for a in records])
    db.add(run);await db.flush()
    job=await enqueue(db,'process',{'run_id':run.id},key);await db.commit();return out_job(job)

@app.post('/api/v1/collection-runs',status_code=202)
async def collect_and_generate(body:dict,u=Depends(editor),db=Depends(db_session)):
    if not settings.gigachat_auth_key or not settings.gigachat_model:raise HTTPException(409,'Настройте GigaChat')
    count=await db.scalar(select(func.count()).select_from(Source).where(Source.enabled==True,Source.agreed==True))
    if not count:raise HTTPException(409,'Включите хотя бы один источник')
    active=await db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(['queued','running']),Job.kind.in_(['process','daily'])))
    if active>=3:raise HTTPException(429,'Дождитесь завершения текущих выпусков')
    job=await enqueue(db,'daily',{'control_time':now().isoformat()},body.get('idempotency_key'))
    await db.commit();return out_job(job)

@app.get('/api/v1/jobs/{id}')
async def get_job(id:str,u=Depends(user),db=Depends(db_session)):
    job=await db.get(Job,id)
    if not job: raise HTTPException(404,'Задача не найдена')
    return out_job(job)

@app.post('/api/v1/jobs/{id}/cancel')
async def cancel_job(id:str,u=Depends(editor),db=Depends(db_session)):
    job=await db.get(Job,id)
    if not job: raise HTTPException(404)
    if job.status in ('queued','running'): job.status='cancelled';job.finished_at=now();await db.commit()
    return out_job(job)

@app.post('/api/v1/jobs/{id}/retry')
async def retry_job(id:str,u=Depends(editor),db=Depends(db_session)):
    job=await db.get(Job,id)
    if not job or job.status not in ('failed','cancelled'): raise HTTPException(409,'Повтор допустим только после ошибки или отмены')
    if job.kind=='email': raise HTTPException(409,'Проверьте результат отправки, создайте новый тест вручную')
    job.status='queued';job.error=None;job.progress=0;job.stage='Повтор';await db.commit();return out_job(job)

@app.get('/api/v1/runs/{id}')
async def get_run(id:str,u=Depends(user),db=Depends(db_session)):
    run=await db.get(Run,id)
    if not run: raise HTTPException(404)
    return {'id':run.id,'dataset_id':run.dataset_id,'mode':run.mode,'status':run.status,'control_time':iso(run.control_time),
        'decisions':run.decisions,'events':run.result.get('events',[]),'metrics':run.metrics}

@app.post('/api/v1/runs/{id}/regroup',status_code=202)
async def regroup(id:str,body:dict,u=Depends(editor),db=Depends(db_session)):
    old=await db.get(Run,id)
    if not old or old.status!='succeeded':raise HTTPException(409,'Выберите завершённый запуск')
    events=old.result.get('events',[])
    chosen=body.get('event_ids',[])
    if not set(chosen)<=set(e['event_id'] for e in events):raise ValueError('Неизвестное событие')
    groups=[{'candidate_ids':e.get('candidate_ids',[]),'reason':e['group_reason'],'conflicts':e['conflicts']} for e in events if e['event_id'] not in chosen]
    selected=[e for e in events if e['event_id'] in chosen]
    if body.get('operation')=='merge':
        if len(selected)<2:raise ValueError('Выберите минимум два события')
        groups.append({'candidate_ids':[c for e in selected for c in e['candidate_ids']],
            'reason':'Ручное объединение редактором: '+str(body.get('reason') or 'Одно событие по исходным публикациям'),
            'conflicts':[c for e in selected for c in e['conflicts']]})
    elif body.get('operation')=='split':
        if len(selected)!=1:raise ValueError('Выберите одну группу')
        for cid in selected[0]['candidate_ids']:
            groups.append({'candidate_ids':[cid],'reason':'Ручное разделение редактором: '+str(body.get('reason') or 'Публикации описывают разные события'),'conflicts':[]})
    else:raise ValueError('Неизвестная операция')
    run=Run(id=uid(),dataset_id=old.dataset_id,mode=old.mode,control_time=old.control_time,snapshot=old.snapshot)
    if old.result.get('candidates'):
        import copy
        decisions=copy.deepcopy(old.decisions)
        for decision in decisions:
            decision['event_group_ids']=[];decision.pop('selected_event_ids',None)
        run.result={'_checkpoint':{'context_fingerprint':old.result.get('context_fingerprint'),
            'candidates':old.result['candidates'],'decisions':decisions}}
    db.add(run);await db.flush()
    job=await enqueue(db,'process',{'run_id':run.id,'group_overrides':groups},body.get('idempotency_key'))
    db.add(Audit(kind='regroup',entity_id=run.id,data={'parent_run':id,'editor':u['email'],'operation':body.get('operation'),'reason':body.get('reason'),'groups':groups}))
    await db.commit();return out_job(job)

@app.get('/api/v1/runs/{id}/log')
async def run_log(id:str,format:str='json',u=Depends(user),db=Depends(db_session)):
    run=await db.get(Run,id)
    if not run: raise HTTPException(404)
    content=log_csv(run.decisions) if format=='csv' else json.dumps(run.decisions,ensure_ascii=False,indent=2)
    return Response(content,media_type='text/csv' if format=='csv' else 'application/json',headers={'Content-Disposition':f'attachment; filename="processing_log.{format}"'})

@app.get('/api/v1/digests/{id}')
async def get_digest(id:str,u=Depends(user),db=Depends(db_session)):
    d=await db.get(Digest,id)
    if not d: raise HTTPException(404)
    return out_digest(d)

@app.patch('/api/v1/digests/{id}/draft')
async def edit_digest(id:str,body:dict,u=Depends(editor),db=Depends(db_session)):
    d=await db.get(Digest,id)
    if not d: raise HTTPException(404)
    run=await db.get(Run,d.run_id)
    data=json.loads(json.dumps(d.data))
    selected_ids=body.get('event_ids',[e['event_id'] for e in data['events']])
    if len(selected_ids)>5 or len(selected_ids)!=len(set(selected_ids)): raise ValueError('Выберите не больше пяти разных событий')
    available={e['event_id']:e for e in run.result['events']}
    if not set(selected_ids)<=set(available): raise ValueError('Неизвестное событие')
    items={i['event_id']:i for i in data['items']}
    if not set(selected_ids)<=set(items): raise ValueError('Для добавления нового события нужен повторный выпуск с новым отбором')
    edits=body.get('items',[])
    for item in edits:
        if item['event_id'] not in items: raise ValueError('Неизвестный пункт')
        items[item['event_id']]=item
    T,_=parse_date(data['control_time'])
    data=render_digest([items[x] for x in selected_ids],[available[x] for x in selected_ids],T,'Состав скорректирован редактором. Причины и история сохранены.')
    data['mode']=run.mode
    data['semantic_verification']={'supported':False,'problems':['После правки нужна повторная проверка']}
    db.add(Audit(kind='digest_revision',entity_id=d.id,data={'revision':d.revision,'data':d.data,'validation':d.validation,'editor':u['email']}))
    d.data=data;d.revision+=1;d.status='draft';d.validation=validation_for(data)
    await db.commit();return out_digest(d)

@app.post('/api/v1/digests/{id}/validate')
async def validate_digest(id:str,u=Depends(editor),db=Depends(db_session)):
    from .validators import validate_composition
    d=await db.get(Digest,id)
    if not d: raise HTTPException(404)
    data=json.loads(json.dumps(d.data))
    validate_composition(data['items'],data['events'])
    if data['mode']=='live':
        run=await db.get(Run,d.run_id)
        data['semantic_verification']=await verify_sources(GigaChat(d.run_id),data['items'],data['events'],run.snapshot,run.control_time.isoformat())
    else:
        # Fixture edits only pass if summary/short remain extractive and supported by quotes.
        errors=[]
        for item,event in zip(data['items'],data['events']):
            quote_text=' '.join(c['quote'] for c in event['claims'])
            for sentence in [*item['summary'],item['short'],item['consequences']]:
                if not all(part.strip() in quote_text for part in sentence['text'].split('\n') if part.strip()):
                    if not event['conflicts']: errors.append('Правка тестового текста требует подтверждающего исходного фрагмента')
        data['semantic_verification']={'supported':not errors,'problems':errors}
    d.data=data;d.validation=validation_for(data);d.status='needs_review' if d.validation['passed'] else 'validation_failed'
    await db.commit();return out_digest(d)

@app.post('/api/v1/digests/{id}/approve')
async def approve(id:str,u=Depends(editor),db=Depends(db_session)):
    d=await db.get(Digest,id)
    if not d: raise HTTPException(404)
    if not d.validation.get('passed') or d.status not in ('needs_review','ready'): raise HTTPException(409,'Сначала пройдите проверки')
    d.status='approved';db.add(Audit(kind='approval',entity_id=id,data={'revision':d.revision,'editor':u['email'],'at':now().isoformat()}))
    await db.commit();return out_digest(d)

@app.get('/api/v1/digests/{id}/export')
async def export(id:str,format:str='zip',u=Depends(user),db=Depends(db_session)):
    d=await db.get(Digest,id)
    if not d: raise HTTPException(404)
    if format=='zip':
        run=await db.get(Run,d.run_id)
        tests=await db.scalar(select(Audit).where(Audit.kind=='test_results').order_by(Audit.created_at.desc()).limit(1))
        test_runs={}
        for mode in ('live','fixture'):
            test_run=await db.scalar(select(Audit).where(Audit.kind=='test_results',Audit.data['mode'].astext==mode).order_by(Audit.created_at.desc()).limit(1))
            if test_run:test_runs[mode]=test_run.data
        primary=test_runs.get('live') or (tests.data if tests else None)
        calls=(await db.scalars(select(ModelCall).where(ModelCall.run_id==run.id).order_by(ModelCall.created_at))).all()
        model_calls=[{'stage':c.stage,'model':c.model,'prompt_hash':c.prompt_hash,'usage':c.usage,'duration_ms':c.duration_ms,'status':c.status,'created_at':iso(c.created_at)} for c in calls]
        content=safe_package(run,d,primary,test_runs,model_calls);mime='application/zip'
    elif format=='html': content=email_html(d.data);mime='text/html'
    elif format=='eml': content=email_message(d.data).as_bytes();mime='message/rfc822'
    else: content=d.data['post'] if format=='post' else d.data['full'];mime='text/plain'
    return Response(content,media_type=mime,headers={'Content-Disposition':f'attachment; filename="cyber-digest.{format if format not in ("post","txt") else "txt"}"'})

@app.get('/api/v1/digests/{id}/preview/email')
async def preview(id:str,u=Depends(user),db=Depends(db_session)):
    d=await db.get(Digest,id)
    if not d:raise HTTPException(404)
    return HTMLResponse(email_html(d.data),headers={'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'"})

@app.post('/api/v1/digests/{id}/send-test',status_code=202)
@app.post('/api/v1/digests/{id}/send',status_code=202)
async def send_test(id:str,body:dict,u=Depends(editor),db=Depends(db_session)):
    d=await db.get(Digest,id)
    if not d or d.status!='approved': raise HTTPException(409,'Утвердите выпуск')
    recipient=str(body.get('recipient','')).lower()
    registered=await db.scalar(select(Subscriber.id).where(Subscriber.email==recipient,Subscriber.active==True))
    if not registered and recipient not in {s.strip().lower() for s in settings.recipient_allowlist.split(',') if s.strip()}:raise HTTPException(403,'Добавьте активного подписчика или разрешите адрес в настройках')
    if not settings.smtp_host:raise HTTPException(409,'SMTP не настроен, используйте предпросмотр или экспорт')
    job=await enqueue(db,'email',{'digest_id':id,'recipient':recipient,'revision':d.revision},f'email:{id}:{d.revision}:{recipient}')
    await db.commit();return out_job(job)

@app.get('/api/v1/sources')
async def sources(u=Depends(user),db=Depends(db_session)):
    records=(await db.scalars(select(Source).order_by(Source.name))).all()
    return [{'id':s.id,'name':s.name,'url':s.url,'feed_url':s.feed_url,'publisher_type':s.publisher_type,'agreed':s.agreed,'enabled':s.enabled,'last_checked':iso(s.last_checked),'meta':s.meta} for s in records]

@app.patch('/api/v1/sources/{id}')
async def source_update(id:str,body:dict,u=Depends(admin),db=Depends(db_session)):
    s=await db.get(Source,id)
    if not s:raise HTTPException(404)
    for field in ('enabled','agreed','feed_url'):
        if field in body:setattr(s,field,body[field])
    if 'auto_collect' in body or 'collect_interval_minutes' in body:
        interval=int(body.get('collect_interval_minutes',s.meta.get('collect_interval_minutes',60)))
        if not 15<=interval<=1440:raise ValueError('Интервал сбора: от 15 до 1440 минут')
        s.meta={**s.meta,'auto_collect':bool(body.get('auto_collect',s.meta.get('auto_collect',False))),
            'collect_interval_minutes':interval,'next_collect_at':(now()+timedelta(minutes=interval)).isoformat()}
    if s.enabled and not s.agreed:raise ValueError('Сначала согласуйте источник')
    db.add(Audit(kind='source_settings',entity_id=id,data={'changes':body,'editor':u['email']}));await db.commit();return {'ok':True}

@app.post('/api/v1/sources/{id}/collect',status_code=202)
async def source_collect(id:str,body:dict,u=Depends(editor),db=Depends(db_session)):
    s=await db.get(Source,id)
    if not s or not s.enabled or not s.agreed:raise HTTPException(409,'Источник не согласован или отключён')
    job=await enqueue(db,'collect',{'source_id':id,'limit':min(10,int(body.get('limit',3)))},body.get('idempotency_key'))
    await db.commit();return out_job(job)

@app.post('/api/v1/test-runs',status_code=202)
async def test_runs(body:dict,u=Depends(editor),db=Depends(db_session)):
    if not settings.enable_demo:raise HTTPException(404)
    mode=body.get('mode','fixture')
    if mode not in ('fixture','live'):raise ValueError('Неизвестный режим')
    if mode=='live' and (not settings.gigachat_auth_key or not settings.gigachat_model):raise HTTPException(409,'GigaChat не настроен')
    job=await enqueue(db,'tests',{'mode':mode},body.get('idempotency_key'));await db.commit();return out_job(job)

@app.get('/api/v1/tests')
async def tests(u=Depends(user),db=Depends(db_session)):
    if not settings.enable_demo:return {'cases':[],'last':None,'history':[]}
    last=await db.scalar(select(Audit).where(Audit.kind=='test_results').order_by(Audit.created_at.desc()).limit(1))
    history=(await db.scalars(select(Audit).where(Audit.kind=='test_results').order_by(Audit.created_at.desc()).limit(10))).all()
    return {'cases':[{'id':c['id'],'name':c['name']} for c in CASES],'last':last.data if last else None,
        'history':[{'id':r.entity_id,'mode':r.data['mode'],'passed':r.data['passed'],'total':r.data['total'],'created_at':iso(r.created_at)} for r in history]}

@app.get('/api/v1/settings')
async def settings_info(u=Depends(user),db=Depends(db_session)):
    return {'gigachat_configured':bool(settings.gigachat_auth_key),'model':settings.gigachat_model,'scope':settings.gigachat_scope,
        'smtp_configured':bool(settings.smtp_host and settings.smtp_from),'smtp_host':settings.smtp_host,'recipient_allowlist':settings.recipient_allowlist,
        'mode':'production','timezone':'Europe/Moscow','app_env':settings.app_env,'public_base_url':settings.public_base_url,'auto_send':settings.auto_send_enabled}

@app.post('/api/v1/settings/gigachat/test')
async def test_gigachat(u=Depends(admin)):
    result=await GigaChat().models()
    return {'status':'connected','models':[m['id'] for m in result.get('data',[]) if m['id'].startswith('GigaChat')]}

@app.post('/api/v1/settings/smtp/test')
async def test_smtp(u=Depends(admin)):
    try:return await asyncio.to_thread(check_connection)
    except Exception:raise HTTPException(503,'Не удалось подключиться к почте. Проверьте SMTP и пароль приложения на сервере.')

@app.patch('/api/v1/settings')
async def save_settings(body:dict,u=Depends(admin),db=Depends(db_session)):
    allowed={'gigachat_model','recipient_allowlist'}
    if set(body)-allowed:raise ValueError('Секреты задаются только в .env, недопустимая настройка')
    if 'gigachat_model' in body:
        models=(await GigaChat().models()).get('data',[])
        if body['gigachat_model'] not in [m['id'] for m in models if m['id'].startswith('GigaChat')]:raise ValueError('Выберите доступную модель для генерации текста')
    if 'recipient_allowlist' in body:
        emails=[v.strip().lower() for v in str(body['recipient_allowlist']).split(',') if v.strip()]
        if any(not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v) for v in emails):raise ValueError('Недопустимый email')
        body['recipient_allowlist']=','.join(emails)
    for k,v in body.items():setattr(settings,k,v)
    db.add(Audit(kind='settings',data=body));await db.commit();return {'ok':True}

@app.get('/api/v1/subscribers')
async def subscribers(u=Depends(admin),db=Depends(db_session)):
    rows=(await db.scalars(select(Subscriber))).all()
    return [{'id':s.id,'email':s.email,'name':s.name,'active':s.active} for s in rows]

@app.post('/api/v1/subscribers')
async def add_subscriber(body:dict,u=Depends(admin),db=Depends(db_session)):
    email=str(body.get('email','')).lower().strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Укажите корректный email')
    if await db.scalar(select(Subscriber.id).where(Subscriber.email==email)):raise HTTPException(409,'Адрес уже добавлен')
    db.add(Subscriber(email=email,name=str(body.get('name',''))[:255]));await db.commit();return {'ok':True}

@app.patch('/api/v1/subscribers/{id}')
async def change_subscriber(id:str,body:dict,u=Depends(admin),db=Depends(db_session)):
    s=await db.get(Subscriber,id)
    if not s:raise HTTPException(404)
    s.active=bool(body.get('active',s.active));await db.commit();return {'ok':True}

@app.get('/api/v1/schedules')
async def schedules(u=Depends(admin),db=Depends(db_session)):
    rows=(await db.scalars(select(Schedule))).all()
    return [{'id':s.id,'name':s.name,'enabled':s.enabled,'hour':s.hour,'minute':s.minute,'dataset_id':s.dataset_id,'mode':s.mode,'next_run':iso(s.next_run),'last_run':iso(s.last_run)} for s in rows]

@app.post('/api/v1/schedules')
async def add_schedule(body:dict,u=Depends(admin),db=Depends(db_session)):
    hour=int(body.get('hour',9));minute=int(body.get('minute',0))
    if not 0<=hour<24 or not 0<=minute<60:raise ValueError('Недопустимое время')
    dataset=await db.get(Dataset,body.get('dataset_id')) if body.get('dataset_id')!='sources' else None
    if not dataset and body.get('dataset_id')!='sources':raise ValueError('Выберите набор или согласованные источники для расписания')
    next_run=now().astimezone(MOSCOW).replace(hour=hour,minute=minute,second=0,microsecond=0)
    if next_run<=now():next_run+=timedelta(days=1)
    db.add(Schedule(name=body.get('name','Ежедневный выпуск'),enabled=False,hour=hour,minute=minute,dataset_id=dataset.id if dataset else None,mode='fixture' if dataset and dataset.kind=='test' else 'live',next_run=next_run))
    await db.commit();return {'ok':True}

@app.patch('/api/v1/schedules/{id}')
async def toggle_schedule(id:str,body:dict,u=Depends(admin),db=Depends(db_session)):
    s=await db.get(Schedule,id)
    if not s:raise HTTPException(404)
    s.enabled=bool(body.get('enabled',s.enabled));await db.commit();return {'ok':True}

@app.get('/api/v1/audit')
async def audits(u=Depends(user),db=Depends(db_session)):
    rows=(await db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(100))).all()
    return [{'id':a.id,'kind':a.kind,'entity_id':a.entity_id,'created_at':iso(a.created_at),
        'data':{k:v for k,v in a.data.items() if k not in ('results','data')}} for a in rows]
