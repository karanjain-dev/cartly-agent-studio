"use client"

import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, ArrowRight, BadgeCheck, BookOpen, Check, ChevronRight, CircleDollarSign, Clock3, FileText, PackageCheck, RefreshCw, ShieldCheck, Ticket, X } from 'lucide-react'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

type Activity = { id: string; type: string; title: string; detail?: string; data?: unknown; status?: string }
type Proposal = { id: string; status: string; terms: string; termsHash: string; decision: { action?: string; amount?: number; method?: string; timing?: string; explanation: string; rules: string[] } }
type Snapshot = { demo: string; verifiedUser: string | null; orders: any[]; items: any[]; events: Activity[]; proposal: Proposal | null; notice: string; changes: any[]; toolCalls: number; busy?: boolean; date?: string }

const demos = [
  { id: 'return', name: 'Siddharth Jain', user: 'U018', order: 'O0011', defaultKind: 'return', description: 'Return an unused kurta' },
  { id: 'cancel', name: 'Dev Patel', user: 'U014', order: 'O0075', defaultKind: 'cancel', description: 'Cancel a packed order' },
  { id: 'delay', name: 'Simran Kaur', user: 'U031', order: 'O0092', defaultKind: 'coupon', description: 'Request a late-delivery coupon' },
]
const blank: Snapshot = { demo: 'return', verifiedUser: null, orders: [], items: [], events: [], proposal: null, notice: '', changes: [], toolCalls: 0 }
const actionLabels: Record<string, string> = { create_return: 'Create return pickup', issue_refund: 'Issue immediate refund', cancel_order: 'Cancel order', issue_coupon: 'Issue ₹100 coupon' }

export default function Home() {
  const [state, setState] = useState<Snapshot>(blank)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [kind, setKind] = useState<'return' | 'cancel' | 'coupon'>('return')
  const [orderId, setOrderId] = useState('O0011')
  const [reason, setReason] = useState<'change_of_mind' | 'damaged' | 'defective' | 'wrong_item'>('change_of_mind')
  const [unused, setUnused] = useState(false)
  const [policyOpen, setPolicyOpen] = useState(false)
  const [policy, setPolicy] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)

  const demo = demos.find(item => item.id === state.demo) || demos[0]
  const order = state.orders.find(item => item.order_id === orderId)
  const item = state.items.find(item => item.order_id === orderId)
  const canReview = !!order && !working && !state.proposal && (kind !== 'return' || (item && (reason !== 'change_of_mind' || unused)))

  async function request(path: string, init?: RequestInit) {
    const response = await fetch(path, init)
    const body = await response.json()
    if (!response.ok) throw new Error(body.error || 'Something went wrong. Please try again.')
    setState(body)
    return body as Snapshot
  }

  async function refresh() {
    const response = await fetch('/api/session')
    const body = await response.json()
    if (!response.ok) throw new Error(body.error || 'Could not start this session.')
    setState(body)
    return body as Snapshot
  }

  useEffect(() => { refresh().catch(error => setError(error.message)).finally(() => setLoading(false)) }, [])

  async function chooseDemo(id: string) {
    const selected = demos.find(item => item.id === id) || demos[0]
    setWorking(true); setError(''); setConfirmOpen(false)
    try {
      await request('/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ demo: id }) })
      setKind(selected.defaultKind as any); setOrderId(selected.order); setReason('change_of_mind'); setUnused(false)
    } catch (error: any) { setError(error.message) } finally { setWorking(false) }
  }

  async function review() {
    if (!canReview) return
    setWorking(true); setError('')
    try {
      await request('/api/proposal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, orderId, itemId: item?.item_id, reason: kind === 'return' ? reason : undefined, unused }) })
    } catch (error: any) { setError(error.message) } finally { setWorking(false) }
  }

  async function respond(accept: boolean) {
    if (!state.proposal) return
    setWorking(true); setError(''); setConfirmOpen(false)
    try {
      await request('/api/proposal', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ proposalId: state.proposal.id, termsHash: state.proposal.termsHash, accept }) })
    } catch (error: any) { setError(error.message) } finally { setWorking(false) }
  }

  async function openPolicy() {
    setPolicyOpen(true)
    if (policy) return
    try { const response = await fetch('/api/policy'); const body = await response.json(); setPolicy(body.policy || '') } catch { setPolicy('The policy could not be loaded.') }
  }

  const orderItems = useMemo(() => state.items.filter(item => item.order_id === orderId), [state.items, orderId])

  return <main className="support-shell">
    <header className="support-header">
      <a className="wordmark" href="/"><span className="wordmark-mark">c</span>cartly</a>
      <div className="header-right"><span className="secure-label"><ShieldCheck size={15}/>Protected checkout actions</span><Button variant="ghost" onClick={openPolicy}><BookOpen size={16}/>Policy v0.8</Button></div>
    </header>

    <section className="support-hero">
      <div><p className="kicker">CUSTOMER SUPPORT</p><h1>Get help, then approve the exact outcome.</h1><p className="hero-copy">Cartly calculates every amount from the order, shows the terms clearly, and waits for your approval before changing anything.</p></div>
      <div className="reference-card"><Clock3 size={19}/><div><span>Reference date</span><strong>{state.date || '2026-09-15'} · IST</strong></div></div>
    </section>

    <section className="account-bar">
      <div className="account-identity"><span className="identity-icon"><BadgeCheck size={20}/></span><div><span className="label">SIGNED-IN DEMO CUSTOMER</span><strong>{demo.name}</strong><small>{demo.user} · synthetic data only</small></div></div>
      <Select value={state.demo} onValueChange={chooseDemo} disabled={working || loading}><SelectTrigger className="demo-select" aria-label="Choose demo customer"><SelectValue /></SelectTrigger><SelectContent>{demos.map(item => <SelectItem key={item.id} value={item.id}>{item.name} · {item.description}</SelectItem>)}</SelectContent></Select>
    </section>

    <div className="support-grid">
      <section className="request-panel">
        <div className="section-heading"><div><p className="kicker">STEP 1</p><h2>Tell us what you need</h2></div><Button variant="outline" size="sm" onClick={() => chooseDemo(state.demo)} disabled={working}><RefreshCw size={15}/>Start over</Button></div>

        <div className="field-group"><Label>What can we help with?</Label><RadioGroup className="choice-grid" value={kind} onValueChange={(value: any) => { setKind(value); setUnused(false) }} disabled={working || !!state.proposal}>
          <Label className="choice-card" htmlFor="return"><RadioGroupItem id="return" value="return"/><span><PackageCheck size={19}/><strong>Return or refund</strong><small>For a delivered item</small></span></Label>
          <Label className="choice-card" htmlFor="cancel"><RadioGroupItem id="cancel" value="cancel"/><span><X size={19}/><strong>Cancel order</strong><small>Before dispatch</small></span></Label>
          <Label className="choice-card" htmlFor="coupon"><RadioGroupItem id="coupon" value="coupon"/><span><Ticket size={19}/><strong>Late delivery</strong><small>Check coupon eligibility</small></span></Label>
        </RadioGroup></div>

        <div className="field-group"><Label htmlFor="order">Choose an order</Label><Select value={orderId} onValueChange={setOrderId} disabled={working || !!state.proposal}><SelectTrigger id="order"><SelectValue placeholder="Choose an order" /></SelectTrigger><SelectContent>{state.orders.map(current => <SelectItem key={current.order_id} value={current.order_id}>{current.order_id} · {current.status} · {current.payment_method}</SelectItem>)}</SelectContent></Select>{order && <div className="order-summary"><div><span>{order.status}</span><strong>{order.order_id}</strong><small>Placed {order.placed_date}</small></div><div><span>Payment</span><strong>{order.payment_method}</strong><small>Shipping ₹{order.shipping_fee}</small></div></div>}</div>

        {kind === 'return' && <><div className="field-group"><Label>Item</Label>{orderItems.map(current => <div className="item-card" key={current.item_id}><div className="item-icon"><PackageCheck size={20}/></div><div><strong>{current.product_name}</strong><small>{current.category} · ₹{current.price} × {current.quantity}</small></div><span>{current.item_id}</span></div>)}</div>
          <div className="field-group"><Label>Why are you requesting a return?</Label><RadioGroup className="reason-list" value={reason} onValueChange={(value: any) => setReason(value)} disabled={working || !!state.proposal}>
            <Label htmlFor="mind"><RadioGroupItem id="mind" value="change_of_mind"/>Changed my mind or it does not fit</Label>
            <Label htmlFor="damaged"><RadioGroupItem id="damaged" value="damaged"/>Item arrived damaged</Label>
            <Label htmlFor="defective"><RadioGroupItem id="defective" value="defective"/>Item does not work as described</Label>
            <Label htmlFor="wrong"><RadioGroupItem id="wrong" value="wrong_item"/>Received a different item, size, colour, or quantity</Label>
          </RadioGroup></div>
          {reason === 'change_of_mind' && <div className="condition-card"><Checkbox id="unused" checked={unused} onCheckedChange={value => setUnused(value === true)} disabled={working || !!state.proposal}/><Label htmlFor="unused"><strong>I confirm this item is unused.</strong><span>Change-of-mind returns require this confirmation.</span></Label></div>}
        </>}

        <Button className="review-button" disabled={!canReview || loading} onClick={review}>{working ? 'Checking your request…' : 'Review my resolution'}<ArrowRight size={18}/></Button>
        {kind === 'return' && reason === 'change_of_mind' && !unused && <p className="helper-text">Confirm that the item is unused to continue.</p>}
      </section>

      <aside className="resolution-panel">
        <div className="section-heading"><div><p className="kicker">STEP 2</p><h2>Your resolution</h2></div><CircleDollarSign className="heading-icon" size={22}/></div>
        {!state.proposal && !state.notice && <div className="empty-resolution"><div className="empty-icon"><FileText size={28}/></div><strong>Your exact terms will appear here.</strong><p>We will show the action, amount, payment method, and timing before anything changes.</p></div>}
        {state.notice && !state.proposal && <div className="notice-card"><AlertCircle size={20}/><div><strong>{state.notice}</strong><p>No action has been made unless it appears in the activity below.</p></div></div>}
        {state.proposal && <div className={`proposal-card proposal-${state.proposal.status}`}>
          <div className="proposal-status"><span>{state.proposal.status === 'executed' ? 'COMPLETED' : state.proposal.status === 'rejected' ? 'DECLINED' : 'READY FOR APPROVAL'}</span><ShieldCheck size={16}/></div>
          <h3>{state.proposal.status === 'executed' ? 'Your request is complete' : actionLabels[state.proposal.decision.action || ''] || 'Review this request'}</h3>
          <p>{state.proposal.status === 'executed' ? state.notice : state.proposal.decision.explanation}</p>
          <div className="terms-box"><span>EXACT TERMS</span><strong>{state.proposal.terms}</strong></div>
          <div className="term-grid">
            <div><span>Amount</span><strong>{state.proposal.decision.amount !== undefined ? `₹${state.proposal.decision.amount.toFixed(2)}` : '—'}</strong></div>
            <div><span>Method</span><strong>{state.proposal.decision.method || 'Cartly coupon'}</strong></div>
            <div><span>When</span><strong>{state.proposal.decision.timing || 'Immediate'}</strong></div>
          </div>
          {state.proposal.status === 'proposed' && <div className="proposal-actions"><Button variant="outline" disabled={working} onClick={() => respond(false)}>Not now</Button><Button disabled={working} onClick={() => setConfirmOpen(true)}>Review and accept<ChevronRight size={17}/></Button></div>}
          {state.proposal.status === 'executed' && <div className="completion-line"><Check size={17}/>Recorded in this demo session</div>}
        </div>}

        <div className="activity-heading"><TerminalIcon/><div><strong>What Cartly checked</strong><span>Visible system activity</span></div></div>
        <div className="activity-list">{state.events.length ? state.events.slice().reverse().map(activity => <details className="activity-row" key={activity.id}><summary><span className={`activity-dot dot-${activity.type}`}/><div><strong>{activity.title}</strong><p>{activity.detail}</p></div><ChevronRight size={15}/></summary>{activity.data !== undefined && <pre>{JSON.stringify(activity.data, null, 2)}</pre>}</details>) : <p className="activity-empty">Order checks, policy decisions, approvals, and final actions will appear here.</p>}</div>
      </aside>
    </div>

    {error && <div className="error-toast"><AlertCircle size={18}/>{error}<button onClick={() => setError('')} aria-label="Dismiss error"><X size={16}/></button></div>}

    <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Accept this exact resolution?</AlertDialogTitle><AlertDialogDescription>The action, amount, and method below will be applied only after you approve them.</AlertDialogDescription></AlertDialogHeader><div className="accept-terms">{state.proposal?.terms}</div><AlertDialogFooter><AlertDialogCancel>Go back</AlertDialogCancel><AlertDialogAction onClick={() => respond(true)}>I agree to these terms</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>

    <Dialog open={policyOpen} onOpenChange={setPolicyOpen}><DialogContent className="policy-dialog"><DialogHeader><DialogTitle>Cartly customer support policy</DialogTitle><DialogDescription>Policy v0.8 used by this guided flow</DialogDescription></DialogHeader><pre className="policy-text">{policy || 'Loading policy…'}</pre></DialogContent></Dialog>
  </main>
}

function TerminalIcon() { return <span className="terminal-icon">›_</span> }
