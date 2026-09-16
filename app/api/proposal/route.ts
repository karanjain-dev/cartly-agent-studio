import { acceptAndExecute } from '@/lib/guarded-flow'
import { cookieId, jsonError, load, noStore, persist, runtime, sameOrigin, setBusy, snapshot } from '@/lib/session'

export async function PATCH(req: Request) {
  if (!sameOrigin(req)) return jsonError('This request must come from the Cartly website.', 403)
  let id: string | null = null
  let locked = false
  try {
    const body: any = await req.json()
    if (!body || typeof body.proposalId !== 'string' || typeof body.termsHash !== 'string' || typeof body.accept !== 'boolean') return jsonError('The proposal acceptance is incomplete.')
    id = cookieId(req)
    if (!id) return jsonError('Please reload to start a session.', 401)
    const guard = await runtime().DB.prepare('UPDATE demo_sessions SET busy = 1 WHERE id = ? AND busy = 0').bind(id).run()
    if (!guard.meta.changes) return jsonError('Please wait for the current request to finish.', 409)
    locked = true
    const row = await load(id)
    if (!row) throw new Error('Please reload to start a session.')
    const session = JSON.parse(row.payload)
    await acceptAndExecute(session, body.proposalId, body.termsHash, body.accept)
    await persist(id, session)
    return Response.json(snapshot(session), { headers: noStore })
  } catch (error: any) {
    return jsonError(error?.message || 'The acceptance could not be completed. Please try again.', 409)
  } finally {
    if (id && locked) await setBusy(id, 0).catch(() => {})
  }
}
