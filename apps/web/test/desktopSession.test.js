import assert from 'node:assert/strict'
import test from 'node:test'
import { initializeDesktopSession } from '../src/utils/desktopSession.js'
import { getToken, clearAuth } from '../src/utils/auth.js'

test('server pages retain login flow; desktop exchanges its bootstrap capability for a local session', async () => {
  const previous = { document: globalThis.document, fetch: globalThis.fetch, sessionStorage: globalThis.sessionStorage, localStorage: globalThis.localStorage }
  const storage = () => { const values = new Map(); return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) } }
  try {
    globalThis.sessionStorage = storage()
    globalThis.localStorage = storage()
    globalThis.document = { querySelector: () => null }
    globalThis.fetch = () => assert.fail('ordinary server startup must not request a desktop session')
    await initializeDesktopSession()
    let removed = false
    globalThis.document = { querySelector: () => ({ content: 'fixture-bootstrap', remove() { removed = true } }) }
    globalThis.fetch = async (url, options) => {
      assert.equal(url, '/api/desktop/session')
      assert.equal(options.headers['X-Desktop-Bootstrap'], 'fixture-bootstrap')
      return { ok: true, json: async () => ({ code: 200, data: { token: 'fixture-session', username: '本机管理员' } }) }
    }
    await initializeDesktopSession()
    assert.equal(getToken(), 'fixture-session')
    assert.equal(removed, true)
    clearAuth()
  } finally { Object.assign(globalThis, previous) }
})
