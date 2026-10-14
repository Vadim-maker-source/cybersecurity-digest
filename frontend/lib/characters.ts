export function countCharacters(text:string, urls:string[]):number {
  for(const url of [...new Set(urls)].sort((a,b)=>b.length-a.length)) {
    const escaped=url.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    text=text.replace(new RegExp('(?<![\\p{L}\\p{N}_/:?&%#=+~.\\-])'+escaped+'(?![\\p{L}\\p{N}_/:?&%#=+~.\\-])','gu'),'');
  }
  return Array.from(text).length;
}
function moscowDate(raw:string):string {
  const d=new Date(raw);
  return Number.isNaN(d.valueOf())?'дата не подтверждена':d.toLocaleString('ru-RU',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).replace(',','')+' МСК';
}
export function renderPlain(data:Record<string,any>,items:Record<string,any>[],short=false):string {
  const header=data.title+'\nПериод: '+data.period+'\nКонтрольное время: '+moscowDate(data.control_time);
  const parts=[header];
  if(!items.length) parts.push('Подходящих событий за период нет. '+data.zero_events_reason);
  else {
    if(items.length<5)parts.push('Выбрано событий: '+items.length+'. '+data.zero_events_reason);
    items.forEach((item,i)=>{
      const sources=data.events[i].sources.map((s:Record<string,any>)=>(s.source||'Источник не указан')+' · '+moscowDate(s.published_at)+(s.updated_at?' (обновление '+moscowDate(s.updated_at)+')':'')+' · ID '+s.id+'\n'+s.url).join('\n');
      const title=(data.events[i].is_update?'Обновление старого события: ':'')+item.title.text;
      const notes=data.events[i].status_notes?.length?'\nСтатус сообщения: '+data.events[i].status_notes.map((n:Record<string,any>)=>n.text).join(' '):'';
      const sourceText=short?data.events[i].sources.map((s:Record<string,any>)=>s.url).join('\n'):sources;
      parts.push((i+1)+'. '+title+'\n'+(short?item.short.text:item.summary.map((s:Record<string,any>)=>s.text).join(' '))+(short?'':'\nПоследствия: '+item.consequences.text)+notes+'\nИсточники:\n'+sourceText);
    });
  }
  return parts.join('\n\n');
}
