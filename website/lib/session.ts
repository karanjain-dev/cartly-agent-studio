// Transport only. Eligibility, model calls, state and approvals live in Python.
import {env} from 'cloudflare:workers';
export const noStore = {'Cache-Control':'no-store'};
export function jsonError(error:string,status=400){return Response.json({error},{status,headers:noStore})}
export function sameOrigin(req:Request){return req.headers.get('origin')===new URL(req.url).origin}
export function cookieId(req:Request){return (req.headers.get('cookie')||'').match(/(?:^|;\s*)cartly_python_session=([A-Za-z0-9_-]{40,128})(?:;|$)/)?.[1]||null}
export function sessionCookie(token:string,req:Request){return `cartly_python_session=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400${new URL(req.url).protocol==='https:'?'; Secure':''}`}
export async function backend(req:Request,path:string,method='GET',body?:unknown,authenticated=true){
  const config=env as unknown as {CARTLY_BACKEND_URL?:string;CARTLY_SERVICE_KEY?:string};
  if(!config.CARTLY_BACKEND_URL||!config.CARTLY_SERVICE_KEY)throw Error('The Python backend connection is not configured.');
  const token=cookieId(req);
  if(authenticated&&!token)return jsonError('Please reload to start a session.',401);
  const headers:Record<string,string>={'Content-Type':'application/json','X-Cartly-Service-Key':config.CARTLY_SERVICE_KEY};
  if(authenticated)headers.Authorization=`Bearer ${token}`;
  if(method!=='GET')headers['Idempotency-Key']=req.headers.get('Idempotency-Key')||crypto.randomUUID();
  return fetch(config.CARTLY_BACKEND_URL.replace(/\/$/,'')+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),redirect:'manual'});
}
export async function forward(req:Request,path:string,method='GET',body?:unknown){
  try{
    const r=await backend(req,path,method,body);
    if(!r.ok){const v:any=await r.json();return jsonError(typeof v.error==='string'?v.error:v.error?.message||'The backend rejected this request.',r.status)}
    return new Response(r.body,{status:r.status,headers:{...noStore,'Content-Type':r.headers.get('Content-Type')||'application/json'}});
  }catch{return jsonError('The Python backend is unavailable. Check that the local service is running.',503)}
}
