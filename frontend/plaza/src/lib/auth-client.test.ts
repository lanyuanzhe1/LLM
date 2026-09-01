import assert from 'node:assert/strict'
import test from 'node:test'

import { signin, signout, signup, validateSession } from './auth-client'

const session = {
  token: 'token-123',
  token_type: 'Bearer',
  id: 'user-1',
  email: 'grain@example.com',
  name: 'Grain User',
  role: 'user'
}

test('signin sends the webui contract through the base-path auth endpoint', async () => {
  let observed: { url: string; init?: RequestInit } | undefined

  const fetcher: typeof fetch = async (url, init) => {
    observed = { url: String(url), init }
    
return Response.json(session)
  }

  const result = await signin('grain@example.com', 'secret', fetcher, '/agents')

  assert.deepEqual(result, session)
  assert.equal(observed?.url, '/agents/api/auths/signin')
  assert.equal(observed?.init?.method, 'POST')
  assert.equal(observed?.init?.body, JSON.stringify({ email: 'grain@example.com', password: 'secret' }))
})

test('signup and session validation preserve the shared token contract', async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = []

  const fetcher: typeof fetch = async (url, init) => {
    requests.push({ url: String(url), init })
    
return Response.json(session)
  }

  await signup('Grain User', 'grain@example.com', 'secret', fetcher, '/agents')
  await validateSession('token-123', fetcher, '/agents')

  assert.equal(requests[0]?.url, '/agents/api/auths/signup')
  assert.equal(requests[0]?.init?.body, JSON.stringify({ name: 'Grain User', email: 'grain@example.com', password: 'secret' }))
  assert.equal(requests[1]?.url, '/agents/api/auths/me')
  assert.deepEqual(requests[1]?.init?.headers, { Authorization: 'Bearer token-123' })
})

test('auth errors expose the provider detail without leaking a raw response', async () => {
  const fetcher: typeof fetch = async () => Response.json({ detail: 'Incorrect email or password' }, { status: 400 })

  await assert.rejects(() => signin('grain@example.com', 'bad', fetcher, '/agents'), {
    message: 'Incorrect email or password'
  })
})

test('signout uses both bearer and cookie credentials', async () => {
  let observed: { url: string; init?: RequestInit } | undefined

  const fetcher: typeof fetch = async (url, init) => {
    observed = { url: String(url), init }
    
return Response.json(true)
  }

  await signout('token-123', fetcher, '/agents')

  assert.equal(observed?.url, '/agents/api/auths/signout')
  assert.equal(observed?.init?.method, 'POST')
  assert.deepEqual(observed?.init?.headers, { Authorization: 'Bearer token-123' })
  assert.equal(observed?.init?.credentials, 'same-origin')
})
