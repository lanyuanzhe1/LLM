import { backendUrl, backendUnavailable } from '@/lib/backend'

export const dynamic = 'force-dynamic'

// 非 SSE 的文件下载代理：把 FastAPI 的 .pptx 响应（含 Content-Disposition）原样透传给浏览器
export async function POST(request: Request) {
  try {
    const body = await request.text()

    const upstream = await fetch(backendUrl('/v1/assistant/pptx'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      cache: 'no-store'
    })

    const headers = new Headers({
      'Content-Type': upstream.headers.get('content-type') || 'application/octet-stream'
    })

    const disposition = upstream.headers.get('content-disposition')

    if (disposition) headers.set('Content-Disposition', disposition)

    return new Response(upstream.body, { status: upstream.status, headers })
  } catch (error) {
    return backendUnavailable(error)
  }
}
