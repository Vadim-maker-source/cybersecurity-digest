import csv, hashlib, html, io, json, zipfile
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from .core import settings

def email_html(data):
    title=html.escape(data['subject'])
    content=html.escape(data['full'])
    for url in sorted(set(data.get('urls',[])),key=len,reverse=True):
        escaped=html.escape(url,quote=True)
        content=content.replace(escaped,f'<a href="{escaped}" rel="noreferrer">{escaped}</a>')
    return f'<!doctype html><html lang="ru"><meta charset="utf-8"><body style="font-family:Arial,sans-serif;color:#202b41;max-width:700px;margin:32px auto"><h1 style="font-size:24px">{title}</h1><pre style="font:15px/1.65 Arial,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere">{content}</pre></body></html>'

def email_message(data,recipient=None):
    message=EmailMessage(policy=SMTP)
    message['Subject']=data['subject']; message['From']=(settings.smtp_from or 'preview@localhost') if recipient else 'preview@localhost'
    if recipient: message['To']=recipient
    message.set_content(data['full']); message.add_alternative(email_html(data),subtype='html')
    return message

def log_csv(decisions):
    stream=io.StringIO(); fields=['article_id','status','reason_code','reason_text','source','url','published_at','event_group_ids','missing_fields','warnings','errors']
    writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader()
    for d in decisions:
        row={k:json.dumps(d.get(k),ensure_ascii=False) if isinstance(d.get(k),(list,dict)) else str(d.get(k) or '') for k in fields}
        for k,v in row.items():
            if v.lstrip().startswith(('=','+','-','@','\t','\r')): row[k]="'"+v
        writer.writerow(row)
    return '\ufeff'+stream.getvalue()

def safe_package(run,digest,test_outputs=None,test_runs=None,model_calls=None):
    data=digest.data
    files={'digest.txt':data['full'],'digest.md':data['full'],'post.txt':data['post'],'email.html':email_html(data),
        'email.txt':data['full'],'email.eml':email_message(data).as_bytes(),'processing_log.csv':log_csv(run.decisions),
        'processing_log.json':run.decisions,'events.json':run.result.get('events',[]),'claims_and_evidence.json':[c for e in run.result.get('events',[]) for c in e['claims']],
        'run_metadata.json':{**run.metrics,'dataset_id':run.dataset_id,'run_id':run.id,'validation':digest.validation,'dataset_snapshot_hash':hashlib.sha256(json.dumps(run.snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()},
        'ai_description.md':'# Работа ИИ\nКлассификация и извлечение, объединение, ранжирование, написание и смысловая проверка выполняются GigaChat в live-режиме. Режим fixtures использует детерминированный провайдер и не подтверждает качество модели.\nПроверки: точные цитаты и offsets, числа, ID, период МСК, лимиты и состав событий/ссылок. Автоматическая смысловая проверка не гарантирует истинность новости. Требуется редактор.\nСтоимость недоступна без достоверного тарифа. Точная версия модели может не раскрываться API.',
        'README.md':'# Результаты КиберСводки\nЗапуск: см. README репозитория.\nПериод: start < published_at <= end, Europe/Moscow.\nНабор: '+data.get('mode','live')+'\nСтатус выпуска: '+digest.status+'\nНе считается оценкой жюри.',
        'tests/results.json':test_outputs or {'status':'not_run','warning':'Обязательные проверки ещё не запускались'},
        'manifest.json':{'run_id':run.id,'provider':run.mode,'dataset_kind':run.result.get('dataset_kind','not_recorded'),
            'organizer_dataset_processed':run.result.get('dataset_kind')=='organizer','test_status':'available' if test_outputs else 'not_run','format_version':'1.0'}}
    for name,content in run.result.get('prompt_snapshots',{}).items():files['prompts/'+name]=content
    if not run.result.get('prompt_snapshots'):files['prompts/README.txt']='Этот выпуск создан fixtures-провайдером или до сохранения snapshots; точный текст использованных промптов отсутствует. Не подменён текущими шаблонами.'
    for result in (test_outputs or {}).get('results',[]):
        name=result['case_id']
        files['tests/input/'+name+'.json']=result['input']
        files['tests/output/'+name+'.json']=result.get('output') or {'status':result['status'],'errors':result['failures']}
    files['tests/report.md']='# Обязательные проверки\n'+('\n'.join(f"- {r['name']}: {r['status']}" for r in test_outputs['results']) if test_outputs else 'Не запускались')
    files['model_calls.json']=model_calls or []
    for mode,result in (test_runs or {}).items():files['tests/'+mode+'/results.json']=result
    if not settings.enable_demo:
        files={name:content for name,content in files.items() if not name.startswith('tests/')}
        files['ai_description.md']='# Работа ИИ\nGigaChat выполняет классификацию, извлечение фактов, объединение, отбор, написание и смысловую проверку. Факты связаны с цитатами из публикаций. Проверяются даты, числа, ID, источники, период и лимиты. Итог утверждает редактор.\n'
        files['README.md']='# Результаты КиберСводки\nПериод: start < published_at <= end, Europe/Moscow.\nСтатус: '+digest.status+'\nМатериалы, ссылки и цитаты сохранены в соседних файлах.\n'
        files['manifest.json'].pop('test_status',None)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for filename,content in files.items():
            if not isinstance(content,(str,bytes)): content=json.dumps(content,ensure_ascii=False,indent=2)
            payload=content.encode('utf-8') if isinstance(content,str) else content
            for secret in [settings.gigachat_auth_key,settings.session_secret,settings.bootstrap_admin_password,settings.smtp_password]:
                if secret and secret.encode() in payload: raise ValueError('SECRET_SCAN_FAILED')
            archive.writestr(filename,payload)
    return buffer.getvalue()
