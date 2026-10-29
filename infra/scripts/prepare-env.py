"""Create local secrets without printing or hard-coding them."""
from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[2]
target=root/'.env'
if target.exists():raise SystemExit('.env already exists; not overwritten')
text=(root/'.env.example').read_text(encoding='utf-8')
for key,size in [('POSTGRES_PASSWORD',24),('SESSION_SECRET',48)]:
    text=text.replace(key+'=\n',key+'='+secrets.token_urlsafe(size)+'\n')
target.write_text(text,encoding='utf-8')
print('.env created; secrets not displayed')
