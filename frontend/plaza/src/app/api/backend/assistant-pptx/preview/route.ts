import { backendUrl, backendUnavailable } from '@/lib/backend'

export const dynamic = 'force-dynamic'

// 预览是 JSON，不是 SSE/文件流：透传 content-type 即可
export async function POST(request: Request) {
  try {
    const body = await request.text()

    const upstream = await fetch(backendUrl('/v1/assistant/pptx/preview'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      cache: 'no-store'
    })

    return new Response(upstream.body, {
      status: upstream.status,
      headers: { 'Content-Type': upstream.headers.get('content-type') || 'application/json' }
    })
  } catch (error) {
    return backendUnavailable(error)
  }
}
