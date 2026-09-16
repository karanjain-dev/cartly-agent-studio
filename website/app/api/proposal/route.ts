import {forward,jsonError,sameOrigin} from '@/lib/session';
export async function PATCH(req:Request){
  if(!sameOrigin(req))return jsonError('This request must come from the Cartly website.',403);
  try{const b:any=await req.json();if(typeof b.proposalId!=='string'||typeof b.termsHash!=='string'||typeof b.accept!=='boolean')return jsonError('The proposal acceptance is incomplete.');return forward(req,'/web/proposal','PATCH',{proposalId:b.proposalId,termsHash:b.termsHash,accept:b.accept})}catch{return jsonError('Invalid request.')}
}
