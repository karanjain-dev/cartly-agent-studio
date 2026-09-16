import { CartlyTools, changes, clone, WRITES } from './tools'
import type { Event, Proposal, Session, SupportRequest } from './session'

type Decision = {
  outcome: 'proposal' | 'decline' | 'escalate' | 'clarify'
  action?: 'create_return' | 'issue_refund' | 'cancel_order' | 'issue_coupon' | 'update_address'
  orderId: string
  itemId?: string
  reason?: string
  amount?: number
  method?: string
  shippingRefunded?: boolean
  timing?: string
  address?: Record<string,string>
  rules: string[]
  explanation: string
}

const DAMAGE = new Set(['damaged', 'defective', 'wrong_item'])
const RETURN_REASONS = new Set(['change_of_mind', 'damaged', 'defective', 'wrong_item'])
const NON_RETURNABLE = new Set(['innerwear', 'perishables', 'personalized'])

function daysBetween(start: string, end: string) {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000)
}

function stableText(decision: Decision) {
  if (decision.action === 'create_return') {
    return `Create a return for item ${decision.itemId} on order ${decision.orderId}. Refund ₹${decision.amount?.toFixed(2)} to ${decision.method} automatically after pickup completes.${decision.reason === 'change_of_mind' ? ' You confirm that the item is unused.' : ''} Do you agree?`
  }
  if (decision.action === 'issue_refund') {
    return `Issue an immediate refund of ₹${decision.amount?.toFixed(2)} to ${decision.method} for item ${decision.itemId} on order ${decision.orderId}. No return is needed. Do you agree?`
  }
  if (decision.action === 'cancel_order') {
    return `Cancel order ${decision.orderId} and refund ₹${decision.amount?.toFixed(2)} to ${decision.method}. Do you agree?`
  }
  if (decision.action === 'update_address') return `Update the delivery address for order ${decision.orderId} to: ${Object.values(decision.address!).join(', ')}. Do you agree?`
  return `Issue one ₹100 coupon for order ${decision.orderId}. Do you agree?`
}

async function digest(value: string) {
  const bytes = new TextEncoder().encode(value)
  const result = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(result)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}

function event(session: Session, type: Event['type'], title: string, detail: string, data?: unknown) {
  session.events.push({ id: crypto.randomUUID(), type, title, detail, data })
}

function method(order: any) {
  return order.payment_method === 'COD' ? 'Cartly Wallet' : order.payment_method
}

function orderFor(session: Session, orderId: string) {
  if (!session.verified) throw new Error('verification required')
  const order = session.state.orders.find((row: any) => row.order_id === orderId && row.user_id === session.verified)
  if (!order) throw new Error('order or item unavailable for this session')
  return order
}

export function decisionFor(session: Session, request: SupportRequest): Decision {
  if (!request || !['return','cancel','coupon','address'].includes(request.kind)) throw new Error('Unsupported request. Use policy A3 for uncovered requests.')
  const guard = (rule:string, label:string, passed:boolean, facts:unknown) => { event(session, 'guardrail', label, passed ? 'Passed' : 'Blocked or needs clarification', {rule, passed, facts}); return passed }

  const order = orderFor(session, request.orderId)
  guard('A1/A2','Identity and order ownership', true, {verified_user:session.verified, order_id:order.order_id})
  const prior = session.state.refunds.filter((refund: any) => refund.order_id === order.order_id && refund.status === 'completed')
  const historyStart = new Date(Date.parse(`${session.state.config.today}T00:00:00Z`) - 90 * 86_400_000).toISOString().slice(0, 10)
  const qualifyingHistory = session.state.refunds.filter((refund: any) => refund.user_id === session.verified && refund.status === 'completed' && RETURN_REASONS.has(refund.reason) && refund.date >= historyStart && refund.date <= session.state.config.today)

  if (request.kind === 'cancel') {
    if (!guard('C1/C2','Cancellation state', ['Placed', 'Packed'].includes(order.status), {status:order.status})) {
      return { outcome: ['Shipped','Out for delivery'].includes(order.status) ? 'decline' : 'escalate', orderId: order.order_id, rules: ['Shipped','Out for delivery'].includes(order.status) ? ['C2'] : ['A3'], explanation: 'This order has already moved beyond the cancellation stage. You can refuse delivery or request a return after it is delivered.' }
    }
    if (prior.length) return {outcome:'decline',orderId:order.order_id,rules:['E12'],explanation:'This order already has a refund.'}
    guard('E9/H2', 'Cancellation exemption', true, 'Placed and Packed cancellations are exempt from the ₹5,000 authority limit.')
    const amount = session.state.order_items.filter((item: any) => item.order_id === order.order_id).reduce((total: number, item: any) => total + item.price * item.quantity, 0) + order.shipping_fee
    return { outcome: 'proposal', action: 'cancel_order', orderId: order.order_id, amount, method: method(order), shippingRefunded: order.shipping_fee > 0, rules: ['C1', 'E7', 'E9'], explanation: 'This order can be cancelled now with a full refund.' }
  }

  if (request.kind === 'address') {
    if (!guard('D1','Address-change state',order.status==='Placed',{status:order.status})) return {outcome:'decline',orderId:order.order_id,rules:['D1'],explanation:'Address changes require Placed state.'}
    if (!request.address || ['line1','city','state','pincode','country'].some(k=>typeof request.address?.[k]!=='string'||!request.address[k].trim())) return {outcome:'clarify',orderId:order.order_id,rules:['D3'],explanation:'Ask for the full delivery address: street, city, state, pincode and country.'}
    if (!guard('D2','Delivery coverage',session.state.serviceable_pincodes.serviceable_pincodes.includes(request.address.pincode),{pincode:request.address.pincode})) return {outcome:'decline',orderId:order.order_id,rules:['D2'],explanation:'This pincode is not serviceable. Ask for an alternative serviceable address.'}
    return {outcome:'proposal',action:'update_address',orderId:order.order_id,address:clone(request.address),rules:['D1','D2','D3'],explanation:'The complete address is eligible for a change after exact approval.'}
  }
  if (request.kind === 'coupon') {
    const deliveredOrToday = order.actual_delivery_date || session.state.config.today
    const lateness = daysBetween(order.promised_delivery_date, deliveredOrToday)
    if (!guard('F1','Late-delivery coupon eligibility',lateness > 5 && !order.coupon_issued && !session.state.coupons.some((coupon:any)=>coupon.order_id===order.order_id), {lateness_days:lateness,already_issued:!!order.coupon_issued})) {
      return { outcome: 'decline', orderId: order.order_id, rules: ['F1'], explanation: 'A late-delivery coupon is available only when an order is more than 5 days late and has not already received one.' }
    }
    return { outcome: 'proposal', action: 'issue_coupon', orderId: order.order_id, amount: 100, rules: ['F1', 'F2'], explanation: `This order is ${lateness} days late, so one ₹100 coupon is available.` }
  }

  const item = session.state.order_items.find((row: any) => row.order_id === order.order_id && row.item_id === request.itemId)
  if (!item) throw new Error('order or item unavailable for this session')
  if (!guard('E10','Refund-history limit',qualifyingHistory.length < 3,{qualifying_refunds:qualifyingHistory.length,window_days:90,cancellations_excluded:true})) {
    return { outcome: 'escalate', orderId: order.order_id, itemId: item.item_id, rules: ['E10'], explanation: 'This request needs a specialist review because the refund-history threshold is met.' }
  }
  if (!guard('E8','No duplicate item refund',!prior.some((refund: any) => refund.item_id === item.item_id),{item_id:item.item_id})) {
    return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E8'], explanation: 'This item has already been refunded.' }
  }
  if (!guard('G5','No duplicate return',!session.state.returns.some((ret: any) => ret.item_id === item.item_id),{item_id:item.item_id})) {
    return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['G5'], explanation: 'A return is already scheduled for this item. Its refund will happen automatically after pickup.' }
  }
  if (order.status !== 'Delivered' || !order.actual_delivery_date) {
    return { outcome: 'escalate', orderId: order.order_id, itemId: item.item_id, rules: ['A3'], explanation: 'This return request needs a specialist review because the delivery status does not support a standard return.' }
  }
  if (!request.reason || !RETURN_REASONS.has(request.reason)) {
    return { outcome: 'clarify', orderId: order.order_id, itemId: item.item_id, rules: ['E11'], explanation: 'Ask why you are requesting the return so Cartly can apply the correct policy.' }
  }

  const reason = request.reason
  if (reason === 'wrong_item') {
    const different = ['product_name', 'size', 'color', 'quantity'].some(attribute => item[`ordered_${attribute}`] !== item[`delivered_${attribute}`])
    if (!guard('E11','Ordered versus delivered attributes',different,{attributes_match:!different})) return { outcome: 'clarify', orderId: order.order_id, itemId: item.item_id, rules: ['E11'], explanation: 'The order details show the ordered and delivered item match. Please choose change of mind for a fit or preference issue.' }
  }
  const days = daysBetween(order.actual_delivery_date, session.state.config.today)
  const window = item.category === 'electronics' ? 7 : 10
  if (!guard('E1/H1','Return window',days >= 0 && days <= window,{days_since_delivery:days,window_days:window,timezone:'IST'})) {
    return { outcome: ['damaged','defective'].includes(reason) ? 'escalate' : 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E1', 'H1'], explanation: `This request is outside the ${window}-day return window for this category.` }
  }
  if (NON_RETURNABLE.has(item.category)) {
    if (!guard('E2','Non-returnable category exception',reason !== 'change_of_mind',{category:item.category,reason})) return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E2'], explanation: 'This category cannot be returned for a change of mind.' }
    const ageHours = (Date.parse(session.state.config.reference_datetime) - Date.parse(order.actual_delivery_at)) / 3_600_000
    if (!guard('E2','Report within 48 hours',Number.isFinite(ageHours) && ageHours >= 0 && ageHours <= 48,{hours_since_delivery:ageHours,claim_at:session.state.config.reference_datetime})) return { outcome: Number.isFinite(ageHours)?'decline':'clarify', orderId: order.order_id, itemId: item.item_id, rules: ['E2'], explanation: 'Damage and wrong-item claims for this category must be reported within 48 hours.' }
  }
  if (reason === 'change_of_mind' && !guard('E4','Unused item confirmation',request.unused === true,{unused:request.unused ?? 'unknown',source:'customer statement; must be reconfirmed in the approved terms'})) {
    return { outcome: request.unused===false?'decline':'clarify', orderId: order.order_id, itemId: item.item_id, rules: ['E4'], explanation: 'A change-of-mind return requires confirmation that the item is unused.' }
  }
  const value = item.price * item.quantity
  if (reason==='change_of_mind' && value<99) return {outcome:'escalate',orderId:order.order_id,rules:['A3','E4'],explanation:'The pickup fee would exceed the item value. Human review required.'}
  if (!guard('E6','Photo evidence',!(DAMAGE.has(reason) && value > 2000 && !item.evidence_photo_uploaded),{item_value:value,photo_uploaded:item.evidence_photo_uploaded,photo_required:DAMAGE.has(reason)&&value>2000})) {
    return { outcome: 'clarify', orderId: order.order_id, itemId: item.item_id, rules: ['E6'], explanation: 'This claim needs an uploaded photo before a return can be created.' }
  }
  const shippingRefunded = DAMAGE.has(reason) && order.shipping_fee > 0 && !prior.some((refund: any) => refund.shipping_refunded)
  const amount = value - (reason === 'change_of_mind' ? 99 : 0) + (shippingRefunded ? order.shipping_fee : 0)
  guard('E12/H4/E7','Database refund and shipping calculation',true,{item_value:value,shipping_refunded:shippingRefunded,refund_amount:amount,method:method(order),pickup_fee:reason==='change_of_mind'?99:0})
  const cumulative=prior.reduce((total:number, refund:any)=>total+refund.amount,0)+amount
  if (!guard('E9/H2','Cumulative refund limit',cumulative<=5000,{cumulative_refund:cumulative,limit:5000})) {
    return { outcome: 'escalate', orderId: order.order_id, itemId: item.item_id, rules: ['E9', 'H2'], explanation: 'This request needs a specialist review because it would take total refunds on this order above ₹5,000.' }
  }
  const immediate = DAMAGE.has(reason) && value < 500
  guard('E5','Refund timing',true,{immediate,item_value:value,timing:immediate?'Immediate, no return':'Automatically after pickup'})
  return {
    outcome: 'proposal', action: immediate ? 'issue_refund' : 'create_return', orderId: order.order_id, itemId: item.item_id,
    reason, amount, method: method(order), shippingRefunded, timing: immediate ? 'Immediate' : 'After pickup',
    rules: [reason === 'change_of_mind' ? 'E4' : 'E3', 'E5', 'E7', 'E12'],
    explanation: immediate ? 'This qualifying item is eligible for an immediate refund.' : 'This qualifying item can be returned. The refund is released automatically after pickup.'
  }
}

function sameDecision(a: Decision, b: Decision) {
  return a.outcome === b.outcome && a.action === b.action && a.orderId === b.orderId && a.itemId === b.itemId && a.reason === b.reason && a.amount === b.amount && a.method === b.method && a.shippingRefunded === b.shippingRefunded && JSON.stringify(a.address) === JSON.stringify(b.address)
}

export async function createProposal(session: Session, request: SupportRequest) {
  if (session.proposal?.status === 'proposed' || session.proposal?.status === 'accepted') session.proposal.status = 'superseded'
  event(session, 'context', 'Load signed-in order', `Order ${request.orderId} is loaded for the verified demo customer.`, { order_id: request.orderId, verified_user: session.verified })
  const decision = decisionFor(session, request)
  event(session, 'policy', 'Apply Cartly policy', decision.explanation, { rules: decision.rules, outcome: decision.outcome })
  if (decision.outcome !== 'proposal' || !decision.action) {
    session.notice = decision.explanation
    if (decision.outcome === 'escalate') event(session, 'state', 'Specialist review required', 'No order change was made. Cartly will prepare the review summary.', { rules: decision.rules })
    return null
  }
  const terms = stableText(decision)
  const proposal: Proposal = {
    id: crypto.randomUUID(), status: 'proposed', revision: session.revision, request, decision, terms,
    termsHash: await digest(terms), createdAt: session.state.config.reference_datetime
  }
  session.proposal = proposal
  session.notice = ''
  event(session, 'state', 'Exact proposal ready', 'Review the action, amount, and method before accepting.', { action: decision.action, amount: decision.amount, method: decision.method, timing: decision.timing })
  return proposal
}

export async function acceptAndExecute(session: Session, proposalId: string, termsHash: string, accept: boolean) {
  const proposal = session.proposal
  if (!proposal || proposal.id !== proposalId || proposal.termsHash !== termsHash) throw new Error('The proposal or displayed terms do not match. Please review the latest proposal.')
  if (proposal.status === 'executed' && accept) return
  if (proposal.status !== 'proposed' || proposal.revision !== session.revision) throw new Error('This proposal is no longer available. Please ask for a new proposal.')
  if (!accept) {
    say(session,'user','No, do not proceed with this proposal.')
    proposal.status = 'rejected'
    session.notice = 'No action was taken. You can start a different request whenever you are ready.'
    say(session,'assistant',session.notice)
    event(session, 'state', 'Proposal declined', 'No order or payment change was made.')
    return
  }
  session.revision = (session.revision || 0) + 1
  proposal.status = 'accepted'
  proposal.acceptanceRevision = session.revision
  say(session,'user','I agree to this exact proposal: '+proposal.terms)
  event(session, 'guardrail', 'Customer accepted exact terms', 'The action, amount, and method matched the displayed proposal.', { proposal_id: proposal.id })
  const current = decisionFor(session, proposal.request)
  if (!sameDecision(proposal.decision, current)) {
    proposal.status = 'stale'
    session.notice = 'The order or eligibility changed before execution. Please review a new resolution.'
    event(session, 'error', 'Proposal needs review', session.notice, { previous: proposal.decision, current })
    say(session,'assistant',session.notice)
    return
  }
  const tools = new CartlyTools(session.state, session.verified)
  const args: any = { order_id: current.orderId, confirmed: true }
  if (current.action === 'create_return' || current.action === 'issue_refund') Object.assign(args, { item_id: current.itemId, reason: current.reason })
  if (current.action === 'update_address') args.address=current.address
  const before = clone(tools.state)
  const result = tools.call(current.action!, args)
  session.state = tools.state
  session.verified = tools.verified
  session.calls += 1
  session.toolLog.push({...tools.logs.at(-1),mode:'guarded-proposal',proposal_id:proposal.id})
  if (!result.ok) {
    proposal.status = 'stale'
    session.notice = result.error.message
    say(session,'assistant',session.notice || 'Action not completed.')
    event(session, 'tool', current.action!, result.error.message, { arguments: args, ...result })
    return
  }
  proposal.status = 'executed'
  proposal.result = result.result
  const delta = changes(before, tools.state)
  event(session, 'tool', current.action!, 'The approved action was executed after a final policy recheck.', { arguments: args, result: result.result })
  if (delta.length) event(session, 'state', 'Save approved change', `${delta.length} session change applied.`, delta)
  session.notice = current.action === 'update_address' ? 'Your delivery address has been updated.' : current.action === 'create_return' ? `Return created. ₹${current.amount?.toFixed(2)} will go to ${current.method} automatically after pickup.` : current.action === 'cancel_order' ? `Order cancelled. ₹${current.amount?.toFixed(2)} will go to ${current.method}.` : current.action === 'issue_coupon' ? '₹100 coupon issued for this late order.' : `₹${current.amount?.toFixed(2)} refund issued to ${current.method}.`
  say(session,'assistant',session.notice)
}

export function say(s:Session,role:'user'|'assistant',content:string) {s.messages.push({role,content});s.input.push({role,content})}
export function invalidateProposal(s:Session) {
  s.revision=(s.revision||0)+1
  if(s.proposal&&['proposed','accepted'].includes(s.proposal.status)) {
    s.proposal.status='superseded'
    event(s,'guardrail','Previous proposal invalidated','A new customer message requires a fresh proposal and approval.',{rule:'G1/H5',proposal_id:s.proposal.id})
  }
}
export async function agentTool(s:Session,name:string,args:any) {
  let result:any
  try {
    if(WRITES.has(name))throw Error('G1/H3/H5: direct action blocked. Use propose_action; only the customer can approve and execute the exact proposal.')
    if(name==='decide_policy')result={ok:true,result:decisionFor(s,args)}
    else if(name==='propose_action') {const proposal=await createProposal(s,args);result={ok:true,result:proposal?{proposal}:{decision:decisionFor(s,args)}}}
    else {
      if(name==='verify_user'&&s.verified&&args.user_id!==s.verified)throw Error('Start a new conversation to verify a different customer.')
      const tools=new CartlyTools(s.state,s.verified);result=tools.call(name,args);s.state=tools.state
      if(result.ok)s.verified=tools.verified
      if(result.ok&&name==='get_order'&&!s.seenOrders.includes(args.order_id))s.seenOrders.push(args.order_id)
      if(result.ok&&name==='escalate_to_human')s.ended=true
    }
  }catch(e:any){result={ok:false,error:{message:e.message}}}
  s.calls++;s.toolLog.push({timestamp:s.state.config.reference_datetime,tool_name:name,arguments:clone(args),...clone(result),mode:'guarded-proposal'})
  if(!result.ok)event(s,'guardrail','Tool request blocked',result.error.message,{tool:name,passed:false})
  return result
}
