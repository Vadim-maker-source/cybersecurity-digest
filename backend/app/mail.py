"""Authenticated SMTP with TLS; connection checks never send messages."""
from contextlib import contextmanager
import smtplib,ssl
from .core import settings

@contextmanager
def connection():
    if not settings.smtp_host or not settings.smtp_from:raise ValueError('SMTP_NOT_CONFIGURED')
    if settings.smtp_security not in ('ssl','starttls'):raise ValueError('SMTP_SECURITY must be ssl or starttls')
    factory=smtplib.SMTP_SSL if settings.smtp_security=='ssl' else smtplib.SMTP
    options={'context':ssl.create_default_context()} if settings.smtp_security=='ssl' else {}
    with factory(settings.smtp_host,settings.smtp_port,timeout=20,**options) as smtp:
        if settings.smtp_security=='starttls':smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:smtp.login(settings.smtp_username,settings.smtp_password)
        yield smtp

def check_connection():
    with connection() as smtp:
        code,_=smtp.noop()
        if code!=250:raise ValueError('SMTP_NOT_READY')
    return {'status':'connected','authenticated':bool(settings.smtp_username),'message_sent':False}
