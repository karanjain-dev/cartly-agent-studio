import {forward,jsonError,sameOrigin} from '@/lib/session';
export async function POST(req:Request){
  if(!sameOrigin(req))return jsonError('This request must come from the Cartly website.',403);
  try{const body:any=await req.json();if(typeof body.message!=='string'||!body.message.trim()||body.message.length>3000)return jsonError('Enter a message between 1 and 3,000 characters.');return forward(req,'/web/chat','POST',{message:body.message.trim()})}catch{return jsonError('Invalid request.')}
}
