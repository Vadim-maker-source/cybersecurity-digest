import asyncio, hashlib, json, ssl, time, uuid
from pathlib import Path
import httpx
from pydantic import BaseModel
from .core import settings
from .models import Session, ModelCall, Audit, engine
from sqlalchemy import text as sqltext

PROMPTS = Path(__file__).parent / 'prompts'
TOKEN_CACHE={}
TOKEN_LOCK=asyncio.Lock()

class ModelError(Exception): pass

class GigaChat:
    def __init__(self, run_id=None):
        self.run_id = run_id
        self.token = None
        self.expires = 0
        self.lock = asyncio.Lock()
        self.actual_models = set()
        self.calls = 0
        self.tokens = 0
        self.usage_available = True
        self.context = ssl.create_default_context()
        self.prompt_snapshots={p.name:p.read_text(encoding='utf-8') for p in PROMPTS.glob('*.txt')}
        if settings.gigachat_ca_bundle:
            self.context.load_verify_locations(settings.gigachat_ca_bundle)

    async def log(self, stage, model, digest, usage, started, status):
        async with Session() as db:
            db.add(ModelCall(run_id=self.run_id, stage=stage, model=model, prompt_hash=digest,
                usage=usage, duration_ms=int((time.monotonic()-started)*1000), status=status))
            await db.commit()

    async def access_token(self, refresh=False):
        async with TOKEN_LOCK:
            key=hashlib.sha256((settings.gigachat_auth_key+settings.gigachat_scope).encode()).hexdigest()
            cached=TOKEN_CACHE.get(key)
            if cached and cached['expires']>time.time()+60 and not refresh:
                self.token=cached['token'];self.expires=cached['expires'];return self.token
            if self.token and self.expires > time.time()+60 and not refresh: return self.token
            if not settings.gigachat_auth_key: raise ModelError('GIGACHAT_NOT_CONFIGURED: ключ не настроен')
            async with httpx.AsyncClient(verify=self.context, timeout=20) as client:
                response = await client.post(settings.gigachat_auth_url,
                    headers={'Authorization':'Basic '+settings.gigachat_auth_key,'RqUID':str(uuid.uuid4()),'Accept':'application/json'},
                    data={'scope':settings.gigachat_scope})
                if response.status_code != 200: raise ModelError(f'OAUTH_{response.status_code}: проверьте ключ и scope')
                data = response.json()
                self.token = data['access_token']
                expires = float(data['expires_at'])
                self.expires = expires / 1000 if expires > 10**11 else expires
                TOKEN_CACHE[key]={'token':self.token,'expires':self.expires}
                return self.token

    async def models(self):
        token = await self.access_token()
        async with httpx.AsyncClient(verify=self.context, timeout=20) as client:
            response = await client.get(settings.gigachat_base_url.rstrip('/')+'/models',headers={'Authorization':'Bearer '+token})
            if response.status_code != 200: raise ModelError(f'MODELS_{response.status_code}')
            return response.json()

    async def call(self, stage, data, schema: type[BaseModel]):
        async with engine.connect() as connection:
            await connection.execute(sqltext('SELECT pg_advisory_lock(673253)'))
            try:return await self._call(stage,data,schema)
            finally:await connection.execute(sqltext('SELECT pg_advisory_unlock(673253)'))

    async def _call(self, stage, data, schema: type[BaseModel]):
        if not settings.gigachat_model: raise ModelError('MODEL_NOT_CONFIGURED: выберите доступную модель')
        system = self.prompt_snapshots['system.txt']
        instruction = self.prompt_snapshots[f'{stage}.txt']
        digest = hashlib.sha256((system+instruction+json.dumps(schema.model_json_schema(),ensure_ascii=False)).encode()).hexdigest()
        messages = [{'role':'system','content':system+'\n'+instruction},
            {'role':'user','content':json.dumps({'task_data':data,'response_schema':schema.model_json_schema()},ensure_ascii=False)}]
        refreshed = False
        schema_mode = True
        last_error = 'MODEL_UNAVAILABLE'
        for attempt in range(settings.gigachat_max_retries+1):
            started = time.monotonic()
            token = await self.access_token()
            body = {'model':settings.gigachat_model,'messages':messages,'temperature':settings.gigachat_temperature,'stream':False,'max_tokens':8000}
            if schema_mode: body['response_format'] = {'type':'json_schema','schema':schema.model_json_schema(),'strict':True}
            try:
                async with httpx.AsyncClient(verify=self.context, timeout=settings.gigachat_timeout_seconds) as client:
                    response = await client.post(settings.gigachat_base_url.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+token},json=body)
                self.calls += 1
                if response.status_code == 401 and not refreshed:
                    await self.log(stage,settings.gigachat_model,digest,None,started,'401')
                    await self.access_token(refresh=True); refreshed=True; continue
                if response.status_code == 400 and schema_mode:
                    await self.log(stage,settings.gigachat_model,digest,None,started,'schema_fallback')
                    schema_mode=False; continue
                if response.status_code in (429,500,502,503,504):
                    await self.log(stage,settings.gigachat_model,digest,None,started,str(response.status_code))
                    last_error=f'MODEL_HTTP_{response.status_code}'
                    delay = min(20,float(response.headers.get('Retry-After',2**attempt)))
                    await asyncio.sleep(delay); continue
                if response.status_code != 200:
                    await self.log(stage,settings.gigachat_model,digest,None,started,str(response.status_code))
                    raise ModelError(f'MODEL_HTTP_{response.status_code}: ошибка API')
                result=response.json()
                actual=result.get('model',settings.gigachat_model)
                usage=result.get('usage')
                self.actual_models.add(actual)
                self.usage_available &= usage is not None
                self.tokens += (usage or {}).get('total_tokens',0)
                await self.log(stage,actual,digest,usage,started,'received')
                choice=result['choices'][0]
                if choice.get('finish_reason') in ('length','blacklist'): raise ValueError('неполный ответ или отказ провайдера')
                content=choice['message']['content'].strip()
                safe_content=content
                for secret in [settings.gigachat_auth_key,settings.session_secret,settings.bootstrap_admin_password,settings.smtp_password]:
                    if secret:safe_content=safe_content.replace(secret,'[скрыто]')
                async with Session() as db:
                    db.add(Audit(kind='model_output',entity_id=self.run_id,data={'stage':stage,'model':actual,'prompt_hash':digest,'response':safe_content,'usage':usage}))
                    await db.commit()
                if content.startswith('```'): content=content.split('\n',1)[1].rsplit('```',1)[0]
                return schema.model_validate_json(content)
            except (httpx.HTTPError,ValueError,KeyError,IndexError) as exc:
                last_error='MODEL_RESPONSE_INVALID' if isinstance(exc,(ValueError,KeyError,IndexError)) else 'MODEL_NETWORK_ERROR'
                if isinstance(exc,httpx.HTTPError):
                    self.calls += 1
                    await self.log(stage,settings.gigachat_model,digest,None,started,last_error)
                messages.append({'role':'user','content':'Предыдущий ответ не принят: '+last_error+'. Верни полный корректный JSON по исходной схеме. Не добавляй факты.'})
                await asyncio.sleep(min(2**attempt,8))
        raise ModelError(last_error+': исчерпан лимит повторов')
