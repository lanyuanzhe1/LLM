import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'

import { proxyAuthRequest } from './auth-proxy'

test('forwards auth method, body and credentials and returns the session cookie', async t => {
  let observed: { method?: string; url?: string; body?: string; authorization?: string; cookie?: string } = {}

  const server = createServer((request, response) => {
    let body = ''

    request.setEncoding('utf8')
    request.on('data', chunk => {
      body += chunk
    })
    request.on('end', () => {
      observed = {
        method: request.method,
        url: request.url,
        body,
        authorization: request.headers.authorization,
        cookie: request.headers.cookie
      }
      response.statusCode = 201
      response.setHeader('content-type', 'application/json')
      response.setHeader('set-cookie', 'token=shared-token; Path=/; HttpOnly; SameSite=Lax')
      response.end(JSON.stringify({ token: 'shared-token' }))
    })
  })

  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  t.after(() => server.close())
  const address = server.address()

  assert(address && typeof address === 'object')

  const request = new Request('http://local.test/agents/api/auths/signin', {
    method: 'POST',
    headers: {
      authorization: 'Bearer old-token',
      'content-type': 'application/json',
      cookie: 'token=old-token'
    },
    body: JSON.stringify({ email: 'grain@example.com', password: 'secret' })
  })

  const response = await proxyAuthRequest(request, ['signin'], `http://127.0.0.1:${address.port}`)

  assert.deepEqual(observed, {
    method: 'POST',
    url: '/api/v1/auths/signin',
    body: JSON.stringify({ email: 'grain@example.com', password: 'secret' }),
    authorization: 'Bearer old-token',
    cookie: 'token=old-token'
  })
  assert.equal(response.status, 201)
  assert.equal(response.headers.get('set-cookie'), 'token=shared-token; Path=/; HttpOnly; SameSite=Lax')
  assert.deepEqual(await response.json(), { token: 'shared-token' })
})

test('maps the public me alias to the webui session endpoint', async t => {
  let observedUrl = ''

  const server = createServer((request, response) => {
    observedUrl = request.url || ''
    response.setHeader('content-type', 'application/json')
    response.end('{}')
  })

  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  t.after(() => server.close())
  const address = server.address()

  assert(address && typeof address === 'object')

  await proxyAuthRequest(
    new Request('http://local.test/agents/api/auths/me'),
    ['me'],
    `http://127.0.0.1:${address.port}`
  )

  assert.equal(observedUrl, '/api/v1/auths/')
})
