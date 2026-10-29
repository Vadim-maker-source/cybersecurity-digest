export function moscowMinute(value:Date=new Date()):string {
 const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(value);
 const part=(type:string)=>parts.find(p=>p.type===type)?.value||'';
 return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;
}

export function pastDailyPeriod(control:string,current:string):boolean {
 const end=Date.parse(control),now=Date.parse(current);
 return Number.isFinite(end)&&Number.isFinite(now)&&now-end>24*60*60*1000;
}
