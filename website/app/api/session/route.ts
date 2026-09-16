import {backend,cookieId,forward,jsonError,noStore,sameOrigin,sessionCookie} from '@/lib/session';
async function create(req:Request,demo='return'){
  try{
    const r=await backend(req,'/web/session','POST',{demo},false);
    const v:any=await r.json();
    if(!r.ok)return jsonError(v.error?.message||'Cannot start this conversation.',r.status);
    return Response.json(v.snapshot,{headers:{...noStore,'Set-Cookie':sessionCookie(v.token,req)}});
  }catch(error){console.error('Cartly backend session failed:',error instanceof Error?error.message:'connection failure');return jsonError('The Python backend is unavailable. Start the local workspace first.',503)}
}
export async function GET(req:Request){return cookieId(req)?forward(req,'/web/session'):create(req)}
export async function POST(req:Request){
  if(!sameOrigin(req))return jsonError('This request must come from the Cartly website.',403);
  try{const body:any=await req.json();if(!['return','cancel','delay'].includes(body.demo))return jsonError('Choose a valid demo customer.');return create(req,body.demo)}catch{return jsonError('Invalid request.')}
}
