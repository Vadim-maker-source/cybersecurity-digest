"""Temporary, reconnecting HTTPS tunnel. No account or existing SSH key is used."""
import argparse,json,os,re,shutil,subprocess,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'work'
URL_PATTERN=re.compile(r'https://[a-z0-9]+\.lhr\.life')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=6752)
    parser.add_argument('--link-file',type=Path,default=WORK/'public-site-link.txt')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('Invalid local port')
    ssh=shutil.which('ssh')
    if not ssh:raise SystemExit('OpenSSH client is required')
    WORK.mkdir(exist_ok=True)
    lock=(WORK/'share.lock').open('a+b')
    lock.seek(0,os.SEEK_END)
    if not lock.tell():lock.write(b'0');lock.flush()
    lock.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        print('A sharing process is already running. Current URL:',flush=True)
        if (WORK/'public-url.txt').exists():print((WORK/'public-url.txt').read_text(),flush=True)
        return
    args.link_file.parent.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/v1/health/ready',timeout=10) as response:
        if response.status!=200:raise SystemExit('Start the local website first')
    (WORK/'share-process.json').write_text(json.dumps({'id':os.getpid(),
        'started':datetime.now(timezone.utc).isoformat(),'script':str(Path(__file__))}),encoding='utf-8')
    current=None
    try:
        while True:
            command=[ssh,'-F','none','-T','-o','BatchMode=yes','-o','IdentitiesOnly=yes',
                '-o','IdentityFile=none','-o','StrictHostKeyChecking=accept-new',
                '-o','UserKnownHostsFile='+str(WORK/'recovery-known-hosts'),
                '-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3',
                '-o','ExitOnForwardFailure=yes','-o','ConnectTimeout=20',
                '-R',f'80:127.0.0.1:{args.port}','nokey@localhost.run','--','--output','json']
            with (WORK/'share-ssh.stderr.log').open('a',encoding='utf-8') as errors:
                current=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,text=True,
                    encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                for line in current.stdout:
                    urls=URL_PATTERN.findall(line)
                    if urls:
                        url=urls[-1]
                        content=url+'\n\nTemporary address. Keep this computer on and online. The provider may change the address; this file is updated automatically.\n'
                        args.link_file.write_text(content,encoding='utf-8')
                        (WORK/'public-url.txt').write_text(url,encoding='utf-8')
                        print(url,flush=True)
                code=current.wait()
                print(f'Tunnel disconnected ({code}); retrying in 5 seconds.',flush=True)
            time.sleep(5)
    finally:
        if current and current.poll() is None:
            current.terminate()
            try:current.wait(timeout=10)
            except subprocess.TimeoutExpired:current.kill()

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:pass
