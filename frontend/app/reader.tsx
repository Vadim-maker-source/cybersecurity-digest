'use client';
import {useEffect,useState} from 'react';
import {ShieldCheck,ArrowUpRight,ArrowRight,Calendar,Mail,FileText,Copy,Download,RefreshCw,Loader2} from 'lucide-react';

type Source={source:string,url:string,published_at:string,updated_at?:string};
type Story={id:string,title:string,summary:string[],consequences:string,sources:Source[],status_notes:string[],selection_reason:string,is_update:boolean};
export type Digest={id:string,revision:number,status:string,title:string,subject:string,period:string,control_time:string,full:string,post:string,zero_events_reason:string,items:Story[]};
const date=(value:string)=>value?new Date(value).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'})+' МСК':'Дата не подтверждена';

export default function Reader({initialDigests=[],initialTab='full',initialId='',initialError=''}:{initialDigests?:Digest[],initialTab?:string,initialId?:string,initialError?:string}){
 const [digests,setDigests]=useState<Digest[]>(initialDigests),[selected,setSelected]=useState(initialId),[tab,setTab]=useState(initialTab),[loading,setLoading]=useState(false),[error,setError]=useState(initialError),[message,setMessage]=useState('');
 const digest=digests.find(d=>d.id===selected)||digests[0];
 async function load(){
  setLoading(true);setError('');
  try{const response=await fetch('/api/v1/public/digests',{cache:'no-store',credentials:'omit'});if(!response.ok)throw new Error('Не удалось загрузить выпуски. Попробуйте ещё раз.');const data=await response.json();setDigests(data.items)}
  catch(e){setError(e instanceof Error?e.message:'Сервер недоступен. Попробуйте ещё раз.')}
  finally{setLoading(false)}
 }
 useEffect(()=>{if(!message)return;const timer=setTimeout(()=>setMessage(''),4000);return()=>clearTimeout(timer)},[message]);
 const text=digest?(tab==='post'?digest.post:tab==='email'?'Тема: '+digest.subject+'\n\n'+digest.full:digest.full):'';
 async function copy(){try{await navigator.clipboard.writeText(text);setMessage('Текст скопирован')}catch{setMessage('Не удалось скопировать. Скачайте текст кнопкой рядом.')}}
 function download(){const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='cyber-digest-'+(tab==='post'?'post':'full')+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 return <div className="reader-shell">
  <header className="reader-header"><a href="/" className="reader-brand"><span className="logo"><ShieldCheck size={23}/></span><span>КиберСводка<small>Ежедневный дайджест по кибербезопасности</small></span></a><a className="btn reader-login" href="/editor">Вход редактора <ArrowRight size={15}/></a></header>
  <main className="reader-main">
   <section className="reader-intro"><span className="eyebrow">ДЛЯ РУКОВОДИТЕЛЕЙ И СПЕЦИАЛИСТОВ ПО ИБ</span><h1>Что произошло.<br/><span>Кого затронуло. Какие последствия.</span></h1><p>До пяти событий за сутки. Факты, оговорки и ссылки на исходные публикации.</p></section>
   <div className="reader-controls"><label>Выпуск<select value={digest?.id||''} disabled={!digests.length} onChange={e=>{setSelected(e.target.value);setTab('full')}}>{digests.length?digests.map(d=><option key={d.id} value={d.id}>{d.period}</option>):<option value="">Пока нет выпусков</option>}</select></label><button className="btn" disabled={loading} onClick={()=>void load()}><RefreshCw size={15} className={loading?'spin':''}/> Обновить</button></div>
   {error&&<div className="error-box" role="alert">{error} <button className="text-button" onClick={()=>void load()}>Повторить</button></div>}
   {loading&&!digest?<div className="panel reader-empty" role="status"><Loader2 className="spin"/> Загружаем выпуски…</div>:!digest?error?null:<div className="panel reader-empty"><FileText size={30}/><h2>Выпуск готовится</h2><p>Проверенные материалы появятся здесь после обработки редакцией.</p></div>:<>
    <div className="reader-meta"><span><Calendar size={15}/>{digest.period}</span><span>{digest.items.length} из 5 событий</span><span>Ревизия {digest.revision}</span></div>
    <div className={'reader-status '+(digest.status==='approved'?'approved':'')}><ShieldCheck size={18}/><div><b>{digest.status==='approved'?'Выпуск утверждён редактором':'Предпросмотр выпуска · ожидает утверждения редактором'}</b><p>Автоматические проверки пройдены. Контрольное время: {date(digest.control_time)}.</p></div></div>
    <section className="panel reader-digest"><div className="reader-tabs" role="tablist" aria-label="Формат дайджеста">{[['full','Дайджест'],['reason','Почему выбрано'],['email','Письмо'],['post','Короткий пост']].map(([id,label])=><a key={id} href={'/?format='+id+'&digest='+digest.id} role="tab" aria-selected={tab===id} aria-controls="digest-content" id={'tab-'+id} onClick={event=>{event.preventDefault();setTab(id)}} className={tab===id?'active':''}>{label}</a>)}</div>
     <div id="digest-content" role="tabpanel" aria-labelledby={'tab-'+tab} className="reader-body">
      {tab==='full'?<><span className="eyebrow">КИБЕРБЕЗОПАСНОСТЬ · СОБЫТИЯ ЗА СУТКИ</span><h2>{digest.title}</h2>{digest.items.length===0&&<p>Подходящих событий за период нет. {digest.zero_events_reason}</p>}{digest.items.map((item,i)=><article className="reader-story" key={item.id}><div className="reader-story-heading"><span>{String(i+1).padStart(2,'0')}</span><h3>{item.is_update&&'Обновление: '}{item.title}</h3></div>{item.summary.map((line,n)=><p key={n}>{line}</p>)}<p><strong>Последствия:</strong> {item.consequences}</p>{item.status_notes.length>0&&<div className="reader-caveat"><strong>Статус сообщения:</strong> {item.status_notes.join(' ')}</div>}<div className="reader-sources">{item.sources.map((source,n)=><a href={source.url} key={n} target="_blank" rel="noopener noreferrer"><span>{source.source||'Исходная публикация'} <ArrowUpRight size={14}/></span><small>{date(source.published_at)}{source.updated_at&&' · Обновлено: '+date(source.updated_at)}</small></a>)}</div></article>)}{digest.items.length>0&&digest.items.length<5&&<p className="reader-explanation">{digest.zero_events_reason||'Выпуск содержит только события, прошедшие отбор и проверки за указанный период.'}</p>}</>:tab==='reason'?<><h2>Почему эти события вошли в выпуск</h2><p className="reader-explanation">При отборе учитываются последствия, масштаб и срочность по исходным публикациям.</p>{digest.items.map((item,i)=><article className="reader-story" key={item.id}><h3>{i+1}. {item.title}</h3><p>{item.selection_reason||'Обоснование не указано в этом выпуске.'}</p></article>)}{!digest.items.length&&<p>{digest.zero_events_reason}</p>}</>:tab==='email'?<><div className="reader-mail-subject"><Mail size={20}/><div><small>Тема письма</small><h2>{digest.subject}</h2></div></div><p className="reader-explanation">Предпросмотр. Отправка доступна редактору после утверждения выпуска.</p><pre className="reader-text">{digest.full}</pre></>:<><h2>Короткий пост</h2><pre className="reader-text">{digest.post}</pre></>}
     </div>{tab!=='reason'&&<div className="reader-actions"><button className="btn" onClick={()=>void copy()}><Copy size={15}/> Скопировать текст</button><button className="btn" onClick={download}><Download size={15}/> Скачать TXT</button></div>}
    </section>
   </>}
   <footer className="reader-footer"><span>КиберСводка · Europe/Moscow</span><span>Исходные публикации доступны по ссылкам в событиях.</span></footer>
  </main>{message&&<div className="toast" role="status">{message}</div>}
 </div>
}
