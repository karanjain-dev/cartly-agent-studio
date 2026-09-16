import { CartlyTools, changes, clone } from './tools'
import type { Event, Proposal, Session, SupportRequest } from './session'

type Decision = {
  outcome: 'proposal' | 'decline' | 'escalate'
  action?: 'create_return' | 'issue_refund' | 'cancel_order' | 'issue_coupon'
  orderId: string
  itemId?: string
  reason?: string
  amount?: number
  method?: string
  shippingRefunded?: boolean
  timing?: string
  rules: string[]
  explanation: string
}

const DAMAGE = new Set(['damaged', 'defective', 'wrong_item'])
const RETURN_REASONS = new Set(['change_of_mind', 'damaged', 'defective', 'wrong_item'])
const NON_RETURNABLE = new Set(['innerwear', 'perishables', 'personalized'])
const DEMO_USERS: Record<string, string> = { return: 'U018', cancel: 'U014', delay: 'U031' }

function daysBetween(start: string, end: string) {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000)
}

function stableText(decision: Decision) {
  if (decision.action === 'create_return') {
    return `Create a return for item ${decision.itemId} on order ${decision.orderId}. Refund ₹${decision.amount?.toFixed(2)} to ${decision.method} automatically after pickup completes. Do you agree?`
  }
  if (decision.action === 'issue_refund') {
    return `Issue an immediate refund of ₹${decision.amount?.toFixed(2)} to ${decision.method} for item ${decision.itemId} on order ${decision.orderId}. No return is needed. Do you agree?`
  }
  if (decision.action === 'cancel_order') {
    return `Cancel order ${decision.orderId} and refund ₹${decision.amount?.toFixed(2)} to ${decision.method}. Do you agree?`
  }
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
  const order = session.state.orders.find((row: any) => row.order_id === orderId && row.user_id === session.verified)
  if (!order) throw new Error('This order is unavailable for the signed-in customer.')
  return order
}

function decisionFor(session: Session, request: SupportRequest): Decision {
  const order = orderFor(session, request.orderId)
  const prior = session.state.refunds.filter((refund: any) => refund.order_id === order.order_id && refund.status === 'completed')
  const historyStart = new Date(Date.parse(`${session.state.config.today}T00:00:00Z`) - 90 * 86_400_000).toISOString().slice(0, 10)
  const qualifyingHistory = session.state.refunds.filter((refund: any) => refund.user_id === session.verified && refund.status === 'completed' && RETURN_REASONS.has(refund.reason) && refund.date >= historyStart && refund.date <= session.state.config.today)

  if (request.kind === 'cancel') {
    if (!['Placed', 'Packed'].includes(order.status)) {
      return { outcome: 'decline', orderId: order.order_id, rules: ['C2'], explanation: 'This order has already moved beyond the cancellation stage. You can refuse delivery or request a return after it is delivered.' }
    }
    const amount = session.state.order_items.filter((item: any) => item.order_id === order.order_id).reduce((total: number, item: any) => total + item.price * item.quantity, 0) + order.shipping_fee
    return { outcome: 'proposal', action: 'cancel_order', orderId: order.order_id, amount, method: method(order), shippingRefunded: true, rules: ['C1', 'E7', 'E9'], explanation: 'This order can be cancelled now with a full refund.' }
  }

  if (request.kind === 'coupon') {
    const deliveredOrToday = order.actual_delivery_date || session.state.config.today
    const lateness = daysBetween(order.promised_delivery_date, deliveredOrToday)
    if (lateness <= 5 || order.coupon_issued || session.state.coupons.some((coupon: any) => coupon.order_id === order.order_id)) {
      return { outcome: 'decline', orderId: order.order_id, rules: ['F1'], explanation: 'A late-delivery coupon is available only when an order is more than 5 days late and has not already received one.' }
    }
    return { outcome: 'proposal', action: 'issue_coupon', orderId: order.order_id, amount: 100, rules: ['F1', 'F2'], explanation: `This order is ${lateness} days late, so one ₹100 coupon is available.` }
  }

  const item = session.state.order_items.find((row: any) => row.order_id === order.order_id && row.item_id === request.itemId)
  if (!item) throw new Error('This item is unavailable for the signed-in customer.')
  if (qualifyingHistory.length >= 3) {
    return { outcome: 'escalate', orderId: order.order_id, itemId: item.item_id, rules: ['E10'], explanation: 'This request needs a specialist review because the refund-history threshold is met.' }
  }
  if (prior.some((refund: any) => refund.item_id === item.item_id)) {
    return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E8'], explanation: 'This item has already been refunded.' }
  }
  if (session.state.returns.some((ret: any) => ret.item_id === item.item_id)) {
    return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['G5'], explanation: 'A return is already scheduled for this item. Its refund will happen automatically after pickup.' }
  }
  if (order.status !== 'Delivered' || !order.actual_delivery_date) {
    return { outcome: 'escalate', orderId: order.order_id, itemId: item.item_id, rules: ['A3'], explanation: 'This return request needs a specialist review because the delivery status does not support a standard return.' }
  }
  if (!request.reason || !RETURN_REASONS.has(request.reason)) {
    return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E11'], explanation: 'Choose why you are requesting the return so Cartly can apply the correct policy.' }
  }

  const reason = request.reason
  if (reason === 'wrong_item') {
    const different = ['product_name', 'size', 'color', 'quantity'].some(attribute => item[`ordered_${attribute}`] !== item[`delivered_${attribute}`])
    if (!different) return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E11'], explanation: 'The order details show the ordered and delivered item match. Please choose change of mind for a fit or preference issue.' }
  }
  const days = daysBetween(order.actual_delivery_date, session.state.config.today)
  const window = item.category === 'electronics' ? 7 : 10
  if (days < 0 || days > window) {
    return { outcome: DAMAGE.has(reason) ? 'escalate' : 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E1', 'H1'], explanation: `This request is outside the ${window}-day return window for this category.` }
  }
  if (NON_RETURNABLE.has(item.category)) {
    if (reason === 'change_of_mind') return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E2'], explanation: 'This category cannot be returned for a change of mind.' }
    const ageHours = (Date.parse(session.state.config.reference_datetime) - Date.parse(order.actual_delivery_at)) / 3_600_000
    if (ageHours < 0 || ageHours > 48) return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E2'], explanation: 'Damage and wrong-item claims for this category must be reported within 48 hours.' }
  }
  if (reason === 'change_of_mind' && request.unused !== true) {
    return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E4'], explanation: 'A change-of-mind return requires confirmation that the item is unused.' }
  }
  const value = item.price * item.quantity
  if (DAMAGE.has(reason) && value > 2000 && !item.evidence_photo_uploaded) {
    return { outcome: 'decline', orderId: order.order_id, itemId: item.item_id, rules: ['E6'], explanation: 'This claim needs an uploaded photo before a return can be created.' }
  }
  const shippingRefunded = DAMAGE.has(reason) && !prior.some((refund: any) => refund.shipping_refunded)
  const amount = value - (reason === 'change_of_mind' ? 99 : 0) + (shippingRefunded ? order.shipping_fee : 0)
  if (prior.reduce((total: number, refund: any) => total + refund.amount, 0) + amount > 5000) {
    return { outcome: 'escalate', orderId: order.order_id, itemId: item.item_id, rules: ['E9', 'H2'], explanation: 'This request needs a specialist review because it would take total refunds on this order above ₹5,000.' }
  }
  const immediate = DAMAGE.has(reason) && value < 500
  return {
    outcome: 'proposal', action: immediate ? 'issue_refund' : 'create_return', orderId: order.order_id, itemId: item.item_id,
    reason, amount, method: method(order), shippingRefunded, timing: immediate ? 'Immediate' : 'After pickup',
    rules: [reason === 'change_of_mind' ? 'E4' : 'E3', 'E5', 'E7', 'E12'],
    explanation: immediate ? 'This qualifying item is eligible for an immediate refund.' : 'This qualifying item can be returned. The refund is released automatically after pickup.'
  }
}

function sameDecision(a: Decision, b: Decision) {
  return a.outcome === b.outcome && a.action === b.action && a.orderId === b.orderId && a.itemId === b.itemId && a.reason === b.reason && a.amount === b.amount && a.method === b.method && a.shippingRefunded === b.shippingRefunded
}

export async function createProposal(session: Session, request: SupportRequest) {
  session.verified ||= DEMO_USERS[session.demo] || null
  session.revision = (session.revision || 0) + 1
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
  if (!proposal || proposal.id !== proposalId || proposal.status !== 'proposed') throw new Error('This proposal is no longer available. Please review a new resolution.')
  if (proposal.termsHash !== termsHash) throw new Error('The displayed terms have changed. Please review the latest resolution.')
  if (!accept) {
    proposal.status = 'rejected'
    session.notice = 'No action was taken. You can start a different request whenever you are ready.'
    event(session, 'state', 'Proposal declined', 'No order or payment change was made.')
    return
  }
  session.revision = (session.revision || 0) + 1
  proposal.status = 'accepted'
  proposal.acceptanceRevision = session.revision
  event(session, 'state', 'Customer accepted exact terms', 'The action, amount, and method matched the displayed proposal.', { proposal_id: proposal.id })
  const current = decisionFor(session, proposal.request)
  if (!sameDecision(proposal.decision, current)) {
    proposal.status = 'stale'
    session.notice = 'The order or eligibility changed before execution. Please review a new resolution.'
    event(session, 'error', 'Proposal needs review', session.notice, { previous: proposal.decision, current })
    return
  }
  const tools = new CartlyTools(session.state, session.verified)
  const args: any = { order_id: current.orderId, confirmed: true }
  if (current.action === 'create_return' || current.action === 'issue_refund') Object.assign(args, { item_id: current.itemId, reason: current.reason })
  const before = clone(tools.state)
  const result = tools.call(current.action!, args)
  session.state = tools.state
  session.verified = tools.verified
  session.calls += 1
  session.toolLog.push(tools.logs.at(-1))
  if (!result.ok) {
    proposal.status = 'stale'
    session.notice = result.error.message
    event(session, 'error', 'Action was not completed', result.error.message, { action: current.action })
    return
  }
  proposal.status = 'executed'
  proposal.result = result.result
  const delta = changes(before, tools.state)
  event(session, 'tool', current.action === 'create_return' ? 'Create return pickup' : current.action === 'cancel_order' ? 'Cancel order' : current.action === 'issue_coupon' ? 'Issue late-delivery coupon' : 'Issue immediate refund', 'The approved action was executed after a final policy recheck.', { arguments: args, result: result.result })
  if (delta.length) event(session, 'state', 'Save approved change', `${delta.length} session change applied.`, delta)
  session.notice = current.action === 'create_return' ? `Return created. ₹${current.amount?.toFixed(2)} will go to ${current.method} automatically after pickup.` : current.action === 'cancel_order' ? `Order cancelled. ₹${current.amount?.toFixed(2)} will go to ${current.method}.` : current.action === 'issue_coupon' ? '₹100 coupon issued for this late order.' : `₹${current.amount?.toFixed(2)} refund issued to ${current.method}.`
}
