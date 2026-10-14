from pathlib import Path
import asyncio,sys
from dotenv import dotenv_values
import asyncpg
root=Path(__file__).resolve().parents[2]
env=dotenv_values(root/'.env')
async def main():
    connection=await asyncpg.connect(user=env['POSTGRES_USER'],password=env['POSTGRES_PASSWORD'],database='postgres',host='127.0.0.1',port=55432)
    name=env['POSTGRES_DB']
    if name!='cyber_digest':raise ValueError('Native bootstrap uses cyber_digest; configure custom databases manually')
    if not await connection.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',name):await connection.execute('CREATE DATABASE cyber_digest')
    await connection.close()
    path=root/'.env';text=path.read_text(encoding='utf-8')
    from urllib.parse import quote
    url='postgresql+asyncpg://'+quote(env['POSTGRES_USER'],safe='')+':'+quote(env['POSTGRES_PASSWORD'],safe='')+'@127.0.0.1:55432/'+name
    text='\n'.join('DATABASE_URL='+url if line.startswith('DATABASE_URL=') else line for line in text.splitlines())+'\n'
    cert=root/'config/certs/russian-root.crt'
    if cert.is_file():text='\n'.join('GIGACHAT_CA_BUNDLE='+cert.as_posix() if line.startswith('GIGACHAT_CA_BUNDLE=') else line for line in text.splitlines())+'\n'
    path.write_text(text,encoding='utf-8')
    print('Project database ready; credentials not displayed')
asyncio.run(main())
