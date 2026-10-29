import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import main
from app.core import settings


def test_workspace_opens_without_identity_and_provides_csrf():
    response=TestClient(main.app).get('/api/v1/workspace')
    assert response.status_code==200
    assert response.json()['user']['role']=='editor'
    assert response.json()['csrf']
    assert response.cookies.get('cyber_session')


def test_import_works_without_login_and_rejects_cross_site_writes(monkeypatch):
    called=[]
    async def import_records(db,records,*args):
        called.append(records)
        return SimpleNamespace(id='new-dataset'),{'accepted':len(records)}
    class DB:
        async def commit(self):pass
    async def database():yield DB()
    monkeypatch.setattr(main,'import_records',import_records)
    main.app.dependency_overrides[main.db_session]=database
    try:
        client=TestClient(main.app,base_url='https://testserver')
        token=client.get('/api/v1/workspace').json()['csrf']
        files={'file':('news.json',json.dumps([{'title':'Новость','text':'Исходная публикация'}]).encode(),'application/json')}
        assert client.post('/api/v1/datasets/import',files=files).status_code==403
        headers={'X-CSRF-Token':token,'Origin':'https://unrelated.example'}
        assert client.post('/api/v1/datasets/import',files=files,headers=headers).status_code==403
        headers['Origin']='https://testserver'
        response=client.post('/api/v1/datasets/import',files=files,headers=headers)
        assert response.status_code==200
        assert response.json()['accepted']==1 and len(called)==1
    finally:main.app.dependency_overrides.clear()


def test_workspace_cookie_does_not_enable_server_operations():
    client=TestClient(main.app)
    assert client.get('/api/v1/workspace').status_code==200
    assert client.patch('/api/v1/settings',json={'recipient_allowlist':'intruder@example.org'}).status_code==403
    assert client.post('/api/v1/subscribers',json={'email':'intruder@example.org'}).status_code==403


@pytest.mark.asyncio
async def test_public_model_budget_stops_additional_processing():
    class DB:
        async def scalar(self,*args):return settings.public_model_call_limit
    with pytest.raises(HTTPException) as error:
        await main.check_processing_budget(DB())
    assert error.value.status_code==429


def test_shared_job_history_hides_mail_recipient():
    job=SimpleNamespace(id='mail',kind='email',status='failed',stage='Отправка',progress=0,
        payload={'recipient':'private@example.org','digest_id':'digest'},
        result={'recipient':'private@example.org'},error='Failed for private@example.org',
        created_at=None,finished_at=None)
    public=main.out_job(job)
    assert 'private@example.org' not in json.dumps(public)
    assert public['payload']['digest_id']=='digest'
    assert job.payload['recipient']=='private@example.org'
