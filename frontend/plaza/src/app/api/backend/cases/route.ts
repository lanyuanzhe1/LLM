import { proxySse } from '@/lib/backend'

export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  return proxySse(request, '/v1/cases/analyze')
}
