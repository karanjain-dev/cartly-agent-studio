import assert from 'node:assert/strict';
import {backend,cookieId,sessionCookie} from '../lib/session';
import {GET as getSession,POST as createSession} from '../app/api/session/route';
import {POST as chat} from '../app/api/chat/route';
import {PATCH as approve} from '../app/api/proposal/route';

let calls:any[]=[];
const token='a'.repeat(43);
globalThis.fetch=async (input:any,init:any)=>{
  calls.push({url:String(input),...init});
  return Response.json({token,snapshot:{messages:[],events:[]}});
};
const request=(method='GET',body?:unknown,origin='http://cartly.test')=>new Request('http://cartly.test/api/session',{
  method,headers:{Origin:origin,Cookie:'cartly_python_session='+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});

assert.equal(cookieId(request()),token);
assert.match(sessionCookie(token,request()),/HttpOnly; SameSite=Strict/);
assert.match(sessionCookie(token,new Request('https://cartly.test')),/Secure/);
await backend(request(),'\/web/session');
assert.equal(calls[0].headers.Authorization,'Bearer '+token);
assert.equal(calls[0].headers['X-Cartly-Service-Key'],'server-only-key');
assert.equal(calls[0].redirect,'manual');
console.log('PASS: private transport credentials and secure cookie');

calls=[];
const created=await getSession(new Request('http://cartly.test/api/session'));
const text=await created.text();
assert.equal(text.includes(token),false);
assert.equal(text.includes('server-only-key'),false);
assert.match(created.headers.get('Set-Cookie')!,/HttpOnly/);
console.log('PASS: session token excluded from browser-readable response');

calls=[];
const newCustomer=await createSession(request('POST',{demo:'U201'}));
assert.equal(newCustomer.status,200);
assert.deepEqual(JSON.parse(calls[0].body),{demo:'U201'});
assert.equal((await createSession(request('POST',{demo:42}))).status,400);
console.log('PASS: new demo customers forwarded to server validation');

calls=[];
assert.equal((await chat(request('POST',{message:'hello'},'https://evil.test'))).status,403);
assert.equal((await approve(request('PATCH',{proposalId:'x',termsHash:'y',accept:true},'https://evil.test'))).status,403);
assert.equal(calls.length,0);
console.log('PASS: cross-origin mutations blocked before Python');

assert.equal((await chat(request('POST',{message:''}))).status,400);
assert.equal((await approve(request('PATCH',{proposalId:'x',termsHash:'y',accept:'true'}))).status,400);
assert.equal(calls.length,0);
console.log('PASS: malformed mutation input blocked');

globalThis.fetch=async()=>new Response('{"type":"done"}\n',{headers:{'Content-Type':'application/x-ndjson'}});
const stream=await chat(request('POST',{message:'Hello'}));
assert.equal(await stream.text(),'{"type":"done"}\n');
console.log('PASS: activity stream forwarded unchanged');

globalThis.fetch=async()=>Response.json({ok:false,error:{message:'Terms changed',code:'proposal_changed'}},{status:409});
const rejection=await approve(request('PATCH',{proposalId:'x',termsHash:'y',accept:true}));
assert.equal(rejection.status,409);
assert.deepEqual(await rejection.json(),{error:'Terms changed'});
console.log('PASS: backend errors remain errors');
