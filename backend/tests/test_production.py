import ssl
import pytest
from fastapi.testclient import TestClient
from app.core import settings
from app.main import app
from app import mail

def test_demo_login_disabled_without_session(monkeypatch):
    monkeypatch.setattr(settings,'enable_demo',False)
    client=TestClient(app)
    response=client.post('/api/v1/auth/demo')
    assert response.status_code==404
    assert 'cyber_session' not in response.cookies

def test_smtp_check_authenticates_without_sending(monkeypatch):
    seen={}
    class FakeSMTP:
        def __init__(self,host,port,**kwargs):
            context=kwargs['context']
            assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def login(self,*args):seen['authenticated']=True
        def noop(self):return 250,b'OK'
        def send_message(self,*args):raise AssertionError('Connection test must never send mail')
    for key,value in {'smtp_host':'smtp.example.org','smtp_from':'unit@example.org','smtp_username':'unit@example.org','smtp_password':'unit-test','smtp_security':'ssl'}.items():
        monkeypatch.setattr(settings,key,value)
    monkeypatch.setattr(mail.smtplib,'SMTP_SSL',FakeSMTP)
    assert mail.check_connection()=={'status':'connected','authenticated':True,'message_sent':False}
    assert seen['authenticated']

def test_plaintext_smtp_rejected(monkeypatch):
    monkeypatch.setattr(settings,'smtp_host','smtp.example.org')
    monkeypatch.setattr(settings,'smtp_from','unit@example.org')
    monkeypatch.setattr(settings,'smtp_security','none')
    with pytest.raises(ValueError,match='SMTP_SECURITY'):mail.check_connection()
