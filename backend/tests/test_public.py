from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from app.main import app, db_session
from app.public import public_digest


def sample():
    return SimpleNamespace(id='digest-id', revision=2, status='needs_review',
        created_at=datetime(2026, 10, 14, tzinfo=timezone.utc), data={
            'title':'Выпуск', 'subject':'Тема', 'period':'24 часа', 'full':'Полный текст', 'post':'Пост',
            'internal_prompt':'PRIVATE', 'items':[{'event_id':'e', 'title':{'text':'Событие','claim_ids':['secret-id']},
                'summary':[{'text':'Что произошло'}], 'consequences':{'text':'Сервис недоступен'}}],
            'events':[{'event_id':'e','ranking':{'reason':'Подтверждённый простой'},
                'claims':[{'text':'PRIVATE RAW SOURCE'}], 'sources':[
                    {'source':'СМИ','url':'https://example.org/news','published_at':'2026-10-14T12:00:00Z','text':'PRIVATE DOCUMENT'},
                    {'url':'javascript:alert(1)'}]}]})


def test_public_dto_exposes_only_reader_fields():
    result=public_digest(sample())
    assert result['items'][0]['selection_reason']=='Подтверждённый простой'
    assert result['items'][0]['consequences']=='Сервис недоступен'
    assert len(result['items'][0]['sources'])==1
    assert result['status']=='needs_review'
    assert 'PRIVATE' not in str(result)
    assert 'claim_ids' not in str(result)


def test_anonymous_reader_gets_only_validated_real_digests():
    class DB:
        async def scalars(self, statement):
            sql=str(statement.compile(dialect=postgresql.dialect(),compile_kwargs={'literal_binds':True}))
            assert 'processing_runs.mode = \'live\'' in sql
            assert "'needs_review', 'approved'" in sql
            assert "'passed'" in sql and '= true' in sql
            assert 'LIMIT 20' in sql
            return SimpleNamespace(all=lambda:[sample()])
    async def database():yield DB()
    app.dependency_overrides[db_session]=database
    try:
        response=TestClient(app).get('/api/v1/public/digests')
        assert response.status_code==200
        assert response.headers['cache-control']=='no-store'
        assert response.json()['items'][0]['id']=='digest-id'
        assert 'cyber_session' not in response.cookies
    finally:app.dependency_overrides.clear()


def test_open_workspace_does_not_expose_owner_settings_or_mail():
    client=TestClient(app)
    for path in ['/settings','/subscribers','/schedules','/audit']:
        assert client.get('/api/v1'+path).status_code==403, path
    for path in ['/digests/private/send','/settings/smtp/test']:
        assert client.post('/api/v1'+path,json={}).status_code==403, path
    for path in ['/auth/login','/auth/logout','/auth/demo']:
        assert client.post('/api/v1'+path,json={}).status_code==404, path
