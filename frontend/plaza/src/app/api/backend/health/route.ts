import { backendUnavailable, backendUrl } from '@/lib/backend'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const upstream = await fetch(backendUrl('/ready'), {
      cache: 'no-store',
      signal: AbortSignal.timeout(5000)
    })

    const body = await upstream.text()

    return new Response(body, {
      status: upstream.status,
      headers: { 'Content-Type': upstream.headers.get('content-type') || 'application/json' }
    })
  } catch (error) {
    return backendUnavailable(error)
  }
}
