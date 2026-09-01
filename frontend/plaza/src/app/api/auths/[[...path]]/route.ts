import { proxyAuthRequest } from '@/lib/auth-proxy'

export const dynamic = 'force-dynamic'

type RouteContext = {
  params: { path?: string[] }
}

const handler = (request: Request, context: RouteContext) => proxyAuthRequest(request, context.params.path || [])

export const GET = handler
export const POST = handler
