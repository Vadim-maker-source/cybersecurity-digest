from pathlib import Path
from datetime import datetime, timezone
from pydantic_settings import BaseSettings, SettingsConfigDict
import uuid

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore',hide_input_in_errors=True)
    app_env: str = 'local'
    enable_demo: bool = False
    initial_source_names: str = 'SecurityLab,CNews,Хабр'
    daily_schedule_enabled: bool = True
    database_url: str
    session_secret: str
    bootstrap_admin_password: str = ''
    cookie_secure: bool = False
    public_base_url: str = 'http://localhost:6752'
    gigachat_auth_key: str = ''
    gigachat_scope: str = 'GIGACHAT_API_PERS'
    gigachat_auth_url: str = 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth'
    gigachat_base_url: str = 'https://api.giga.chat/v1'
    gigachat_model: str = ''
    gigachat_ca_bundle: str = ''
    gigachat_timeout_seconds: int = 60
    gigachat_max_retries: int = 3
    gigachat_temperature: float = 0.1
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_security: str = 'starttls'
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_from: str = ''
    recipient_allowlist: str = ''
    auto_send_enabled: bool = False
    public_model_call_limit: int = 200
    max_upload_mb: int = 20
    max_fetch_response_mb: int = 5
    fetch_timeout_seconds: int = 20

settings = Settings()

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)
def iso(value): return value.isoformat() if value else None
