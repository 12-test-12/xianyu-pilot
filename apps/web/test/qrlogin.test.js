import assert from 'node:assert/strict'
import test from 'node:test'
import request from '../src/utils/request.js'
import { useQrLogin } from '../src/composables/useQrLogin.js'
import { generateQrLogin, getQrLoginStatus, cleanupQrLogin } from '../src/api/qrlogin.js'

test('qrlogin requests are configured with background mode and suppressed global errors', async t => {
  const calls = []
  const originalPost = request.post
  request.post = (url, data, config) => {
    calls.push({ url, data, config })
    return Promise.resolve({ data: { success: true } })
  }
  t.after(() => {
    request.post = originalPost
  })

  await generateQrLogin({ accountId: 101 })
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/qrlogin/generate')
  assert.deepEqual(calls[0].data, { accountId: 101 })
  assert.equal(calls[0].config?.background, true)
  assert.equal(calls[0].config?.suppressGlobalError, true)

  await getQrLoginStatus('session_test_123')
  assert.equal(calls.length, 2)
  assert.equal(calls[1].url, '/qrlogin/status/session_test_123')
  assert.equal(calls[1].config?.background, true)
  assert.equal(calls[1].config?.suppressGlobalError, true)

  await cleanupQrLogin()
  assert.equal(calls.length, 3)
  assert.equal(calls[2].url, '/qrlogin/cleanup')
  assert.equal(calls[2].config?.background, true)
  assert.equal(calls[2].config?.suppressGlobalError, true)
})

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

async function flush() {
  for (let i = 0; i < 10; i++) await Promise.resolve()
}

function flow(t, options = {}) {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const confirmed = []
  const state = useQrLogin({
    generate: async () => ({ data: { sessionId: 'first', qrUrl: 'image:first' } }),
    getStatus: async () => ({ data: { status: 'pending' } }),
    onConfirmed: (data, context) => { confirmed.push({ data, context }) },
    ...options,
  })
  t.after(state.cancelQrLogin)
  return { ...state, confirmed }
}

test('closing a modal ignores a late generation response and never starts polling', async t => {
  const pending = deferred()
  let polls = 0
  const state = flow(t, { generate: () => pending.promise, getStatus: () => { polls++ } })
  const loading = state.startQrLogin()
  state.resetQrState()
  pending.resolve({ data: { sessionId: 'closed', qrUrl: 'image:closed' } })
  await loading
  t.mock.timers.tick(10000)
  assert.equal(state.qr.sessionId, '')
  assert.equal(state.qr.loading, false)
  assert.equal(polls, 0)
})

test('an old generation cannot replace a reopened modal or clear its loading flag', async t => {
  const old = deferred(), fresh = deferred()
  let calls = 0
  const state = flow(t, { generate: () => (++calls === 1 ? old.promise : fresh.promise) })
  const first = state.startQrLogin()
  state.resetQrState()
  const second = state.startQrLogin()
  old.resolve({ data: { sessionId: 'old', qrUrl: 'image:old' } })
  await first
  assert.equal(state.qr.loading, true)
  assert.equal(state.qr.sessionId, '')
  fresh.resolve({ data: { sessionId: 'fresh', qrUrl: 'image:fresh' } })
  await second
  assert.equal(state.qr.sessionId, 'fresh')
  assert.equal(state.qr.loading, false)
})

test('both refresh entry points share a guard and failed refresh preserves the complete snapshot', async t => {
  const pending = deferred()
  let calls = 0
  const state = flow(t, { generate: () => {
    calls++
    return calls === 1 ? Promise.resolve({ data: { sessionId: 'first', qrUrl: 'image:first' } }) : pending.promise
  } })
  await state.startQrLogin()
  const refreshing = state.startQrLogin()
  await state.startQrLogin()
  assert.equal(calls, 2)
  assert.equal(state.qrReady.value, false)
  assert.equal(state.qr.qrUrl, 'image:first')
  pending.resolve({ data: { sessionId: 'incomplete' } })
  await refreshing
  assert.equal(state.qr.status, 'error')
  assert.equal(state.qr.sessionId, 'first')
  assert.equal(state.qr.qrUrl, 'image:first')
  assert.equal(state.qrReady.value, false)
})

test('late status replies cannot confirm a refreshed QR session or start a second polling chain', async t => {
  const pending = deferred()
  let polls = 0, generations = 0
  const state = flow(t, {
    generate: async () => ({ data: { sessionId: `session-${++generations}`, qrUrl: 'image' } }),
    getStatus: () => { polls++; return polls === 1 ? pending.promise : Promise.resolve({ data: { status: 'pending' } }) },
  })
  await state.startQrLogin()
  t.mock.timers.tick(2000)
  await state.startQrLogin()
  pending.resolve({ data: { status: 'confirmed', accountId: 42 } })
  await flush()
  assert.equal(state.confirmed.length, 0)
  assert.equal(state.qr.status, 'pending')
  t.mock.timers.tick(2000)
  await flush()
  assert.equal(polls, 2)
})

test('closing while a poll is pending ignores its error and keeps the exit image intact', async t => {
  const pending = deferred()
  const state = flow(t, { getStatus: () => pending.promise })
  await state.startQrLogin()
  t.mock.timers.tick(2000)
  state.cancelQrLogin()
  pending.reject(new Error('late error'))
  await flush()
  assert.equal(state.qr.status, 'pending')
  assert.equal(state.qr.qrUrl, 'image:first')
  assert.equal(state.confirmed.length, 0)
})

test('both scanned spellings reach mobile confirmation and persistence completes only once', async t => {
  const statuses = ['scaned', 'scanned', 'confirmed', 'confirmed']
  let calls = 0
  const state = flow(t, { getStatus: async () => ({ data: { status: statuses[calls++], ...(calls === 4 ? { accountId: 42 } : {}) } }) })
  state.qr.mode = 'rescan'
  state.qr.accountId = 42
  await state.startQrLogin()
  for (let i = 0; i < 4; i++) {
    t.mock.timers.tick(2000)
    await flush()
    if (i < 2) assert.match(state.qr.message, /手机/)
  }
  assert.equal(state.confirmed.length, 1)
  assert.equal(state.confirmed[0].context.mode, 'rescan')
  assert.equal(state.confirmed[0].context.sessionId, 'first')
  t.mock.timers.tick(10000)
  await flush()
  assert.equal(calls, 4)
})

for (const status of ['error', 'expired', 'failed']) {
  test(`terminal status ${status} stops polling`, async t => {
    let calls = 0
    const state = flow(t, { getStatus: async () => { calls++; return { data: { status } } } })
    await state.startQrLogin()
    t.mock.timers.tick(2000)
    await flush()
    t.mock.timers.tick(10000)
    assert.equal(calls, 1)
    assert.equal(state.qrReady.value, false)
  })
}
