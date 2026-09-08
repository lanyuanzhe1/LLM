const DEFAULT_WEBUI_URL = 'http://127.0.0.1:8080'

const requestHeaders = (request: Request) => {
  const headers = new Headers()

  for (const name of ['accept', 'authorization', 'content-type', 'cookie']) {
    const value = request.headers.get(name)

    if (value) headers.set(name, value)
  }

  return headers
}

export const proxyAuthRequest = async (
  request: Request,
  path: string[],
  configuredBaseUrl = process.env.WEBUI_BASE_URL || DEFAULT_WEBUI_URL
) => {
  const baseUrl = configuredBaseUrl.replace(/\/+$/, '')
  const upstreamPath = path.length === 1 && path[0] === 'me' ? [] : path
  const suffix = upstreamPath.map(segment => encodeURIComponent(segment)).join('/')
  const upstreamUrl = `${baseUrl}/api/v1/auths/${suffix}`
  const hasBody = request.method !== 'GET' && request.method !== 'HEAD'

  const upstream = await fetch(upstreamUrl, {
    method: request.method,
    headers: requestHeaders(request),
    body: hasBody ? await request.text() : undefined,
    cache: 'no-store',
    redirect: 'manual'
  })

  const headers = new Headers()
  const contentType = upstream.headers.get('content-type')
  const setCookie = upstream.headers.get('set-cookie')
  const location = upstream.headers.get('location')

  if (contentType) headers.set('content-type', contentType)
  if (setCookie) headers.set('set-cookie', setCookie)
  if (location) headers.set('location', location)

  return new Response(upstream.body, {
    status: upstream.status,
    headers
  })
}
