import schemas from './reference/tool-schema.json'
import {WRITES} from './tools'

const parameters={
  type:'object',
  properties:{
    kind:{type:'string',enum:['return','cancel','coupon','address']},
    orderId:{type:'string'},
    itemId:{type:'string'},
    reason:{type:'string',enum:['change_of_mind','damaged','defective','wrong_item']},
    unused:{type:'boolean',description:'Use only after the customer says whether the item is unused. Never assume.'},
    address:{type:'object',properties:Object.fromEntries(['line1','city','state','pincode','country'].map(k=>[k,{type:'string'}])),required:['line1','city','state','pincode','country'],additionalProperties:false}
  },
  required:['kind','orderId'],additionalProperties:false
}
export const chatTools=[
  ...(schemas as any[]).filter(t=>!WRITES.has(t.name)),
  {type:'function',name:'decide_policy',description:'Read-only deterministic eligibility, amount, method and timing check. Ask for missing facts when outcome is clarify. Escalate only when required by the policy.',parameters,strict:false},
  {type:'function',name:'propose_action',description:'Prepare the exact proposal for the customer to approve inside chat. This does not execute the action. Use after clarifying the request and running decide_policy.',parameters,strict:false}
]
export const chatInstructions=`

Hosted interaction contract:
Have a natural conversation: understand the request, verify identity, read the relevant order and policy, ask focused questions, and explain the result in ordinary language.
Before an order-changing action, use decide_policy, then propose_action if eligible. These tools compute eligibility and refund amounts from the database.
Use the supplied field names exactly: kind, orderId, itemId, reason, unused, address. Never infer unused; ask the customer.
If the decision requires clarification, ask the customer for the missing information. If the rule is clear, answer it yourself. Required escalations use escalate_to_human with the full G3 summary.
The server renders a proposal card with the exact terms. The customer approves using its "Accept and proceed" button, which is bound to those terms. You cannot approve or execute it.
A typed agreement is still a chat message; ask the customer to use the card. A new message invalidates the previous proposal, so recheck and recreate it when appropriate.
Never claim an action completed until its successful server result appears in conversation memory. Never instruct the customer to use a separate request form.
An unused-item proposal includes the customer's confirmation of condition. Customer approval covers that condition as well as the action, amount and method.
All actions and human handoffs here affect synthetic demo records only; no payment, pickup or staff notification is sent.
`
