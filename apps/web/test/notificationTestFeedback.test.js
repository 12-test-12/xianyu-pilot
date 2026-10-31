import test from 'node:test'
import assert from 'node:assert/strict'
import { notificationTestErrorMessage } from '../src/utils/notificationTestFeedback.js'

test('only a confirmed pre-send failure offers retry and keeps the concrete reason', () => {
  const reason = '地址校验或连接失败，消息尚未发送'
  assert.equal(notificationTestErrorMessage({ attemptStatus: 'failed', retrySafe: true }, reason), reason)
  assert.match(notificationTestErrorMessage({ attemptStatus: 'failed', retrySafe: true }), /原测试重试/)
  assert.match(notificationTestErrorMessage({ attemptStatus: 'unknown', retrySafe: false }), /不会自动重发/)
})

test('in-progress and log repair feedback do not suggest a new send', () => {
  assert.match(notificationTestErrorMessage({ attemptStatus: 'in_progress' }), /正在发送/)
  assert.match(notificationTestErrorMessage({ attemptStatus: 'confirmed', logPersisted: false }), /只会补日志，不会重发/)
})
