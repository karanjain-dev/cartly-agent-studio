import {forward,jsonError,sameOrigin} from '@/lib/session';
export async function POST(req:Request){
  if(!sameOrigin(req))return jsonError('This request must come from the Cartly website.',403);
  try{const b:any=await req.json();if(typeof b.order_id!=='string'||typeof b.item_id!=='string'||typeof b.unused!=='boolean')return jsonError('Choose the item condition.');return forward(req,'/web/condition','POST',{order_id:b.order_id,item_id:b.item_id,unused:b.unused})}catch{return jsonError('Invalid request.')}
}
