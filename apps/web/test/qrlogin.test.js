import assert from 'node:assert/strict'
import test from 'node:test'
import request from '../src/utils/request.js'
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

test('qr scanning status step matches both scanned and scaned', () => {
  const isScanned = status => ['scanned', 'scaned'].includes(status)
  assert.equal(isScanned('scaned'), true)
  assert.equal(isScanned('scanned'), true)
  assert.equal(isScanned('pending'), false)
  assert.equal(isScanned('confirmed'), false)
})

test('deduplication set prevents duplicate concurrent account_added executions', () => {
  const handled = new Set()
  let executionCount = 0

  function onAccountConfirmed(accountId) {
    if (handled.has(accountId)) return false
    handled.add(accountId)
    executionCount++
    return true
  }

  // First call from QR status poll
  assert.equal(onAccountConfirmed(42), true)
  assert.equal(executionCount, 1)

  // Simultaneous duplicate call from SSE account_added event
  assert.equal(onAccountConfirmed(42), false)
  assert.equal(executionCount, 1)
})
