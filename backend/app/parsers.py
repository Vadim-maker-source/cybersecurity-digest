import asyncio, csv, hashlib, io, ipaddress, json, re, socket, ssl, time, zipfile
import http.client,threading
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qsl, urljoin
from urllib.robotparser import RobotFileParser
import feedparser
from bs4 import BeautifulSoup
from docx import Document
import trafilatura
from .core import settings
from .validators import parse_date

class FetchError(ValueError): pass

_HOST_DELAYS={}
_HOST_LAST={}
_FETCH_LOCK=threading.Lock()

def rate_limit(host):
    with _FETCH_LOCK:
        delay=min(60,max(1,_HOST_DELAYS.get(host,1)))
        remaining=delay-(time.monotonic()-_HOST_LAST.get(host,0))
        if remaining>0:time.sleep(remaining)
        _HOST_LAST[host]=time.monotonic()

def clean_url(url):
    p=urlsplit(url)
    query=urlencode([(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')])
    return urlunsplit((p.scheme,p.netloc,p.path,query,''))

def public_address(host):
    try: addresses=socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)
    except OSError: raise FetchError('DNS_ERROR: не удалось определить адрес источника')
    ips=[a[4][0] for a in addresses]
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips): raise FetchError('SSRF_BLOCKED: служебные и частные адреса запрещены')
    return ips[0]

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,port,address,timeout):
        super().__init__(host,port,timeout=timeout,context=ssl.create_default_context()); self.address=address
    def connect(self):
        sock=socket.create_connection((self.address,self.port),self.timeout)
        self.sock=self._context.wrap_socket(sock,server_hostname=self.host)

def fetch(url,allowed_hosts=None):
    current=clean_url(url)
    for redirect in range(6):
        p=urlsplit(current)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password: raise FetchError('INVALID_URL')
        if p.port and p.port not in (80,443): raise FetchError('PORT_BLOCKED')
        if allowed_hosts and p.hostname not in allowed_hosts: raise FetchError('DOMAIN_NOT_AGREED: домен не согласован')
        address=public_address(p.hostname)
        rate_limit(p.hostname)
        if p.scheme=='https': conn=PinnedHTTPS(p.hostname,p.port or 443,address,settings.fetch_timeout_seconds)
        else:
            conn=http.client.HTTPConnection(address,p.port or 80,timeout=settings.fetch_timeout_seconds)
        try:
            path=p.path or '/'
            if p.query: path+='?'+p.query
            conn.request('GET',path,headers={'Host':p.netloc,'User-Agent':'CyberSvodkaPrototype/1.0 (+editor-approved RSS reader)','Accept-Encoding':'identity'})
            r=conn.getresponse()
            if r.status in (301,302,303,307,308):
                current=clean_url(urljoin(current,r.getheader('Location',''))); continue
            if r.status!=200: raise FetchError(f'SOURCE_HTTP_{r.status}')
            if int(r.getheader('Content-Length','0') or 0)>settings.max_fetch_response_mb*1024*1024: raise FetchError('RESPONSE_TOO_LARGE')
            body=r.read(settings.max_fetch_response_mb*1024*1024+1)
            if len(body)>settings.max_fetch_response_mb*1024*1024: raise FetchError('RESPONSE_TOO_LARGE')
            mime=r.getheader('Content-Type','').lower()
            if not any(m in mime for m in ('html','xml','rss','atom','text/plain','json')): raise FetchError('MIME_NOT_SUPPORTED')
            return body,current,mime
        except (OSError,TimeoutError,ssl.SSLError,http.client.HTTPException) as exc:
            raise FetchError('SOURCE_UNAVAILABLE: '+type(exc).__name__)
        finally: conn.close()
    raise FetchError('TOO_MANY_REDIRECTS')

def robots_allowed(url,allowed_hosts=None):
    p=urlsplit(url)
    robot_url=urlunsplit((p.scheme,p.netloc,'/robots.txt','',''))
    try:
        raw,_,_=fetch(robot_url,allowed_hosts)
        parser=RobotFileParser(); parser.parse(raw.decode('utf-8','replace').splitlines())
        if not parser.can_fetch('CyberSvodkaPrototype',url): raise FetchError('ROBOTS_DISALLOWED')
        return parser.crawl_delay('CyberSvodkaPrototype') or parser.crawl_delay('*') or 1
    except FetchError as exc:
        if 'SOURCE_HTTP_404' in str(exc): return 1
        raise

def article_html(raw,url,meta=None,feed_date=None):
    meta=meta or {}
    soup=BeautifulSoup(raw,'html.parser')
    for node in soup.select('script:not([type="application/ld+json"]),style,nav,footer,#current_issue_box,.banner,.promoblock__content,.ads'): node.decompose()
    title_node=soup.select_one('h1')
    title=title_node.get_text(' ',strip=True) if title_node else (soup.title.get_text(strip=True) if soup.title else '')
    selector=meta.get('body_selector')
    node=soup.select_one(selector) if selector else None
    if node:
        if 'cnews' in url:
            blocks=soup.select(selector) if selector and '>' in selector else node.find_all(['p','h2','h3'],recursive=False)
            text='\n'.join(x.get_text(' ',strip=True) for x in blocks)
        else: text=node.get_text('\n',strip=True)
    else: text=trafilatura.extract(raw,include_comments=False,include_tables=False) or ''
    raw_dates=[]
    for node in soup.select('meta[property="article:published_time"],meta[name="article:published_time"],meta[itemprop="datePublished"],time[datetime]'):
        value=node.get('content') or node.get('datetime')
        if value: raw_dates.append(value)
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data=json.loads(node.string or node.get_text())
            values=data if isinstance(data,list) else data.get('@graph',[data])
            raw_dates.extend(x['datePublished'] for x in values if isinstance(x,dict) and x.get('datePublished'))
        except (ValueError,TypeError): pass
    confirmed=[(x,parse_date(x)[0]) for x in raw_dates if parse_date(x)[0]]
    feed_parsed=parse_date(feed_date)[0] if feed_date else None
    conflict=bool(feed_parsed and any(abs((d-feed_parsed).total_seconds())>300 for _,d in confirmed))
    date=feed_date or (confirmed[0][0] if confirmed else (raw_dates[0] if raw_dates else None))
    canonical=soup.select_one('link[rel="canonical"]')
    return {'id':'WEB-'+hashlib.sha256(url.encode()).hexdigest()[:12],'title':title,'text':text,'url':url,
        'canonical_url':canonical.get('href') if canonical else url,'published_at':date,'date_candidates':raw_dates,
        'date_conflict':conflict,'fetched_at':datetime.now(timezone.utc).isoformat(),'source_snapshot_html':raw.decode('utf-8','replace'),
        'snapshot_hash':hashlib.sha256(raw).hexdigest(),'parser_version':'1.0','content_quality':'full' if len(text)>100 else 'insufficient'}

async def collect_source(source,limit=3):
    hosts=source.get('meta',{}).get('allowed_hosts') or [urlsplit(source['url']).hostname]
    meta=source.get('meta') or {}
    for host in hosts:_HOST_DELAYS[host]=max(1,int(meta.get('crawl_delay') or 1))
    feed_url=source.get('feed_url')
    if not feed_url:
        section=meta.get('candidate_section_url')
        if not section or not str(meta.get('adapter','')).endswith('html'):raise FetchError('ADAPTER_NOT_CONFIGURED: RSS/HTML адаптер не настроен')
        delay=await asyncio.to_thread(robots_allowed,section,hosts)
        raw,_,_=await asyncio.to_thread(fetch,section,hosts)
        soup=BeautifulSoup(raw,'html.parser')
        links=list(dict.fromkeys(urljoin(section,a.get('href')) for a in soup.select('article a[href]') if a.get('href')))
        articles=[];errors=[]
        for url in links[:max(1,min(limit,10))]:
            try:
                wait=await asyncio.to_thread(robots_allowed,url,hosts)
                await asyncio.sleep(min(60,max(delay,wait,meta.get('crawl_delay') or 1)))
                body,final,_=await asyncio.to_thread(fetch,url,hosts)
                article=await asyncio.to_thread(article_html,body,final,meta)
                article['source']=source['name'];articles.append(article)
            except FetchError as exc:errors.append({'url':url,'reason':str(exc)})
        return articles,errors
    delay=await asyncio.to_thread(robots_allowed,feed_url,hosts)
    raw,_,mime=await asyncio.to_thread(fetch,feed_url,hosts)
    parsed=feedparser.parse(raw)
    if not parsed.entries: raise FetchError('FEED_INVALID: лента не содержит корректных записей')
    articles=[]; errors=[]
    for entry in parsed.entries[:max(1,min(limit,10))]:
        url=clean_url(entry.get('link',''))
        published=entry.get('published_parsed')
        feed_date=datetime(*published[:6],tzinfo=timezone.utc).isoformat() if published else None
        try:
            wait=await asyncio.to_thread(robots_allowed,url,hosts)
            await asyncio.sleep(min(60,max(delay,wait,meta.get('crawl_delay') or 1)))
            html,final_url,_=await asyncio.to_thread(fetch,url,hosts)
            article=await asyncio.to_thread(article_html,html,final_url,meta,feed_date)
            article['source']=source['name'];article['publisher_type']=source.get('publisher_type');articles.append(article)
        except FetchError as exc:
            errors.append({'url':url,'reason':str(exc)})
            articles.append({'id':'WEB-'+hashlib.sha256(url.encode()).hexdigest()[:12],'title':entry.get('title',''),
                'text':'','source':source['name'],'url':url,'published_at':feed_date,'read_error':str(exc)})
    return articles,errors

def parse_import(raw,filename,metadata=None):
    metadata=metadata or {}
    suffix=filename.rsplit('.',1)[-1].lower()
    if len(raw)>settings.max_upload_mb*1024*1024: raise ValueError('Размер файла превышает лимит')
    if suffix in ('json','jsonl','csv','txt','html','htm'):
        text=raw.decode(metadata.get('encoding','utf-8-sig'))
        if suffix=='json':
            data=json.loads(text)
            if not isinstance(data,(dict,list)):raise ValueError('JSON должен содержать массив или объект записей')
            return data if isinstance(data,list) else data.get('articles',[data])
        if suffix=='jsonl':
            rows=[]
            for i,line in enumerate(text.splitlines(),1):
                if not line.strip(): continue
                try: rows.append(json.loads(line))
                except ValueError: rows.append({'id':f'ROW-{i}','read_error':'READ_ERROR: некорректный JSON в строке'})
            return rows
        if suffix=='csv':
            dialect=csv.Sniffer().sniff(text[:4000],delimiters=',;\t')
            rows=list(csv.DictReader(io.StringIO(text),dialect=dialect))
            mapping=metadata.get('mapping',{})
            return [{mapping.get(k,k):v for k,v in row.items()} for row in rows]
        if suffix in ('html','htm'):
            text=BeautifulSoup(text,'html.parser').get_text('\n',strip=True)
        return [{**metadata,'id':metadata.get('id',filename),'text':text}]
    if suffix=='docx':
        if not zipfile.is_zipfile(io.BytesIO(raw)): raise ValueError('Файл не является DOCX')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if sum(x.file_size for x in z.infolist())>40*1024*1024: raise ValueError('Превышен размер распакованного DOCX')
        doc=Document(io.BytesIO(raw))
        text='\n'.join(p.text for p in doc.paragraphs)
        return [{**metadata,'id':metadata.get('id',filename),'text':text}]
    if suffix=='zip':
        output=[]
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            entries=z.infolist()
            if len(entries)>200 or sum(x.file_size for x in entries)>40*1024*1024: raise ValueError('Превышен лимит ZIP')
            for entry in entries:
                if entry.is_dir(): continue
                if '..' in entry.filename.replace('\\','/').split('/') or entry.filename.startswith(('/','\\')) or ':' in entry.filename: raise ValueError('ZIP_PATH_TRAVERSAL')
                output.extend(parse_import(z.read(entry),entry.filename,metadata))
        return output
    raise ValueError('Формат не поддерживается')
