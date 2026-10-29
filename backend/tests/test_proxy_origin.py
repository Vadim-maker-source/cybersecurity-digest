import pytest
from types import SimpleNamespace
from fastapi import HTTPException
from starlette.requests import Request
from app.main import user


@pytest.mark.asyncio
@pytest.mark.parametrize('origin,allowed',[
    ('https://temporary-link.lhr.life',True),
    ('https://unrelated.example',False),
])
async def test_editor_csrf_accepts_only_same_proxy_origin(origin,allowed):
    request=Request({'type':'http','method':'POST','scheme':'https','path':'/api/v1/collection-runs',
        'headers':[(b'host',b'temporary-link.lhr.life'),(b'origin',origin.encode()),
            (b'x-csrf-token',b'valid-token')],
        'session':{'user_id':'editor','csrf':'valid-token'},'query_string':b''})
    class DB:
        async def get(self,*args):return SimpleNamespace(id='editor',email='unit@example.org',role='admin')
    if allowed:assert (await user(request))['role']=='editor'
    else:
        with pytest.raises(HTTPException) as error:await user(request)
        assert error.value.status_code==403
