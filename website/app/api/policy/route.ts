import {forward} from '@/lib/session';
export async function GET(req:Request){return forward(req,'/web/policy')}
