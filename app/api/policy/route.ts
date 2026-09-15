import policy from '@/lib/reference/policy.json';
export async function GET(){return Response.json({policy:policy.policy})}
