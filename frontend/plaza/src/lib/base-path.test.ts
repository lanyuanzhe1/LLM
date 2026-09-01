import assert from 'node:assert/strict'
import test from 'node:test'

import { withBasePath } from './base-path'

test('prefixes root-relative application paths exactly once', () => {
  assert.equal(withBasePath('/api/auths/signin', '/agents'), '/agents/api/auths/signin')
  assert.equal(withBasePath('/agents/images/avatar.png', '/agents'), '/agents/images/avatar.png')
})

test('normalizes missing and trailing slashes', () => {
  assert.equal(withBasePath('login', 'agents/'), '/agents/login')
  assert.equal(withBasePath('/login', ''), '/login')
})
