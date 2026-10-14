import hashlib,json
from datetime import timedelta
from sqlalchemy import select
from argon2 import PasswordHasher
from .models import Session,User,Dataset,Article,Source,Job,Audit,Schedule
from .core import ROOT,settings,uid,now
from .validators import parse_date,MOSCOW

hasher=PasswordHasher()

def article_data(a):
    return {**a.original,'id':a.original_id,'title':a.title,'text':a.text,'source':a.source,'url':a.url,
        'published_at':a.original.get('published_at'),'internal_id':a.id,'dataset_id':a.dataset_id,
        'date_status':a.meta.get('date_status'),'content_hash':a.content_hash,
        'missing_original_fields':[k for k in ('id','title','text','source','url','published_at') if not a.original.get(k)]}

async def import_records(db,records,name,kind='organizer',metadata=None):
    if not isinstance(records,list) or len(records)>500: raise ValueError('Ожидается массив не более 500 записей')
    checksum=hashlib.sha256(json.dumps(records,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    existing=await db.scalar(select(Dataset).where(Dataset.checksum==checksum,Dataset.kind==kind))
    if existing: return existing,{'duplicate_dataset':True,'accepted':0,'warnings':[]}
    dataset=Dataset(id=uid(),name=name,kind=kind,checksum=checksum,meta=metadata or {})
    db.add(dataset); await db.flush()
    seen={}; warnings=[]; accepted=0
    for i,record in enumerate(records):
        if not isinstance(record,dict): record={'read_error':'READ_ERROR: запись не является объектом'}
        normalized=dict(record)
        original_id=str(record.get('id') or f'ROW-{i+1}')
        content_hash=hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if (original_id,content_hash) in seen: warnings.append(f'{original_id}: повтор идентичной записи'); continue
        if any(k[0]==original_id for k in seen):
            normalized['read_error']='READ_ERROR: конфликт исходного ID с другим содержимым'
            warnings.append(f'{original_id}: конфликт ID')
            original_id+=f'~version-{i+1}'
        seen[original_id,content_hash]=True
        published,status=parse_date(record.get('published_at'),record.get('assume_moscow',False))
        if record.get('date_conflict'):status='CONFLICT'
        db.add(Article(id=uid(),dataset_id=dataset.id,original_id=original_id,title=str(record.get('title') or ''),
            text=str(record.get('text') or ''),source=str(record.get('source') or ''),url=str(record.get('url') or ''),
            published_at=published,content_hash=content_hash,original=normalized,meta={'date_status':status}))
        accepted+=1
    db.add(Audit(kind='import',entity_id=dataset.id,data={'accepted':accepted,'warnings':warnings,'checksum':checksum}))
    return dataset,{'accepted':accepted,'warnings':warnings,'duplicate_dataset':False}

async def enqueue(db,kind,payload,key=None):
    if key:
        existing=await db.scalar(select(Job).where(Job.idempotency_key==key))
        if existing: return existing
    job=Job(id=uid(),kind=kind,payload=payload,idempotency_key=key)
    db.add(job); await db.flush(); return job

async def load_runtime_settings():
    async with Session() as db:
        records=(await db.scalars(select(Audit).where(Audit.kind=='settings').order_by(Audit.created_at))).all()
        for record in records:
            for k,v in record.data.items():
                if k in ('gigachat_model','recipient_allowlist'):setattr(settings,k,v)

async def seed():
    async with Session() as db:
        if not await db.scalar(select(User.id).limit(1)):
            db.add(User(email=settings.bootstrap_admin_email,password_hash=hasher.hash(settings.bootstrap_admin_password),role='admin'))
        path=ROOT/'config'/'sources.json'
        initial={name.strip() for name in settings.initial_source_names.split(',') if name.strip()}
        for source in json.loads(path.read_text(encoding='utf-8')):
            if not await db.scalar(select(Source.id).where(Source.name==source['name'])):
                source['feed_url']=source.get('feed_url') or ''
                if source['name'] in initial and source['meta'].get('verification_status')=='verified':
                    source['agreed']=True;source['enabled']=True
                    source['meta']={**source['meta'],'auto_collect':True,'collect_interval_minutes':60,
                        'next_collect_at':(now()+timedelta(hours=1)).isoformat()}
                db.add(Source(**source))
        if settings.daily_schedule_enabled and not await db.scalar(select(Schedule.id).limit(1)):
            next_run=now().astimezone(MOSCOW).replace(hour=9,minute=0,second=0,microsecond=0)
            if next_run<=now():next_run+=timedelta(days=1)
            db.add(Schedule(name='Ежедневный дайджест',enabled=True,hour=9,minute=0,mode='live',next_run=next_run))
        await db.commit()

if __name__=='__main__':
    import asyncio
    asyncio.run(seed())
