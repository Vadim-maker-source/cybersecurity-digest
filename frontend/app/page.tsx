import Reader,{type Digest} from './reader';

export default async function Home({searchParams}:{searchParams:Promise<{format?:string,digest?:string}>}){
 const query=await searchParams;
 const tab=['full','reason','email','post'].includes(query.format||'')?query.format!:'full';
 let digests:Digest[]=[];
 let error='';
 let serverTime=new Date().toISOString();
 try{
  const base=process.env.INTERNAL_API_URL||'http://127.0.0.1:8000';
  const response=await fetch(base+'/api/v1/public/digests',{cache:'no-store',signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw new Error('Unavailable');
  const data=await response.json();digests=data.items;serverTime=data.server_time||serverTime;
 }catch{error='Не удалось загрузить выпуски. Попробуйте обновить страницу.'}
 return <Reader initialDigests={digests} initialTab={tab} initialId={query.digest||''} initialError={error} initialNow={serverTime}/>;
}
