import{runtime,cookieId,load,sameOrigin,jsonError,setBusy}from'@/lib/session';
import{runAgent}from'@/lib/agent';
export async function POST(req:Request){if(!sameOrigin(req))return jsonError('This request must come from the Cartly website.',403);if(!runtime().OPENAI_API_KEY)return jsonError('Live chat is awaiting the owner’s API connection. You can explore the workspace and policy.',503);
 if(Number(req.headers.get('content-length')||0)>16000)return jsonError('Keep your message under 3,000 characters.',413);
 let id:string|null=null,locked=false;
 try{const body:any=await req.json();if(typeof body.message!=='string'||!body.message.trim()||body.message.length>3000)return jsonError('Enter a message between 1 and 3,000 characters.');id=cookieId(req);if(!id)return jsonError('Please reload to start a session.',401);
 const guard=await runtime().DB.prepare('UPDATE demo_sessions SET busy = 1 WHERE id = ? AND busy = 0').bind(id).run();if(!guard.meta.changes)return jsonError('A reply is already in progress for this session.',409);locked=true;
 const row=await load(id);if(!row){await setBusy(id,0);return jsonError('Please reload to start a session.',401)}const s=JSON.parse(row.payload);if(s.ended||s.turns>=20){await setBusy(id,0);return jsonError('Start a new conversation to continue.',409)}
 const encoder=new TextEncoder(),abort=new AbortController();let connected=true;const sid=id;
 const stream=new ReadableStream({async start(controller){const emit=(event:any)=>{if(connected){try{controller.enqueue(encoder.encode(JSON.stringify(event)+'\n'))}catch{connected=false;abort.abort()}}};try{await runAgent(sid,s,body.message.trim(),emit,abort.signal)}catch{emit({type:'error',message:'The session could not be saved. Please start a new conversation.'});await setBusy(sid,0).catch(()=>{})}finally{if(connected){try{controller.close()}catch{}}}},cancel(){connected=false;abort.abort()}});
 return new Response(stream,{headers:{'Content-Type':'application/x-ndjson; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
 }catch{if(id&&locked)await setBusy(id,0).catch(()=>{});return jsonError('The request could not be completed. Please try again.',503)}
}
