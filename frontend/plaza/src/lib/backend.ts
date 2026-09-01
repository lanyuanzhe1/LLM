import 'server-only'

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8000'

export const backendUrl = (path: string) => {
  const baseUrl = (process.env.GRAIN_API_BASE_URL || DEFAULT_BACKEND_URL).replace(/\/$/, '')

  return `${baseUrl}${path}`
}

export const backendUnavailable = (error: unknown) => {
  const detail = error instanceof Error ? error.message : 'unknown error'

  return Response.json(
    {
      code: 'BACKEND_UNAVAILABLE',
      message: '粮储智能服务暂时不可用，请确认 FastAPI 已启动。',
      detail
    },
    { status: 502 }
  )
}

export const proxySse = async (request: Request, path: string) => {
  try {
    const body = await request.text()

    const upstream = await fetch(backendUrl(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      cache: 'no-store'
    })

    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        'Content-Type': upstream.headers.get('content-type') || 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform'
      }
    })
  } catch (error) {
    return backendUnavailable(error)
  }
}
