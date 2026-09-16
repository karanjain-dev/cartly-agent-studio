import {env} from 'cloudflare:workers';
import {CartlyTools,freshWorld,changes,clone} from './tools';
export const runtime=()=>env as unknown as {DB:D1Database;OPENAI_API_KEY?:string;DEMO_BUDGET_USD?:string};
export type Event={id:string;type:string;title:string;detail?:string;data?:unknown;status?:string};
export type SupportRequest={kind:'return'|'cancel'|'coupon'|'address';orderId:string;itemId?:string;reason?:'change_of_mind'|'damaged'|'defective'|'wrong_item';unused?:boolean;address?:Record<string,string>};
export type Proposal={id:string;status:'proposed'|'accepted'|'executed'|'rejected'|'superseded'|'stale';revision:number;acceptanceRevision?:number;request:SupportRequest;decision:any;terms:string;termsHash:string;createdAt:string;result?:any};
export type Session={demo:string;state:any;verified:string|null;input:any[];messages:{role:string;content:string}[];events:Event[];turns:number;cost:number;calls:number;model:string;ended:boolean;seenOrders:string[];toolLog:any[];revision:number;proposal?:Proposal;notice?:string};
export function fresh(demo='return'):Session{return{demo,state:freshWorld(),verified:null,input:[],messages:[],events:[],turns:0,cost:0,calls:0,model:'gpt-6-astra',ended:false,seenOrders:[],toolLog:[],revision:0,notice:''}}
export function snapshot(s:Session,busy=false){const user=s.verified,orders=s.state.orders.filter((o:any)=>o.user_id===user&&s.seenOrders.includes(o.order_id));return{demo:s.demo,messages:s.messages,events:s.events,turns:s.turns,cost:s.cost,verifiedUser:user,orders,items:s.state.order_items.filter((item:any)=>orders.some((order:any)=>order.order_id===item.order_id)),changes:changes(freshWorld(),s.state),toolCalls:s.calls,model:s.model,ended:s.ended,busy,ready:!!runtime().OPENAI_API_KEY,date:s.state.config.today,proposal:s.proposal||null,notice:s.notice||''}}
export function cookieId(req:Request){const m=(req.headers.get('cookie')||'').match(/(?:^|;\s*)cartly_session=([a-f0-9-]{36})\b/);return m?.[1]??null}
export function sessionCookie(id:string,req:Request){return `cartly_session=${id}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400${new URL(req.url).protocol==='https:'?'; Secure':''}`}
export function sameOrigin(req:Request){return req.headers.get('origin')===new URL(req.url).origin}
export async function load(id:string){return runtime().DB.prepare('SELECT payload, busy FROM demo_sessions WHERE id = ?').bind(id).first<{payload:string;busy:number}>()}
export async function persist(id:string,s:Session){await runtime().DB.prepare('UPDATE demo_sessions SET payload = ? WHERE id = ?').bind(JSON.stringify(s),id).run()}
export async function setBusy(id:string,busy:number){await runtime().DB.prepare('UPDATE demo_sessions SET busy = ? WHERE id = ?').bind(busy,id).run()}
export const noStore={'Cache-Control':'no-store'};
export function jsonError(message:string,status=400){return Response.json({error:message},{status,headers:noStore})}
