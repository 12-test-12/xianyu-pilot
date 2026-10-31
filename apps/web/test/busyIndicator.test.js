import assert from 'node:assert/strict'
import test from 'node:test'
import { createBusyIndicator } from '../src/utils/busyIndicator.js'

test('quick or overlapping requests do not flash a loading banner', t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const changes = []
  const busy = createBusyIndicator(value => changes.push(value))
  busy.update(true)
  t.mock.timers.tick(200)
  busy.update(false)
  t.mock.timers.tick(1000)
  assert.deepEqual(changes, [])
  busy.update(true)
  t.mock.timers.tick(200)
  busy.update(true)
  t.mock.timers.tick(100)
  assert.deepEqual(changes, [true])
  busy.dispose()
})

test('visible feedback stays stable across adjacent requests and hides after completion', t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const changes = []
  const busy = createBusyIndicator(value => changes.push(value))
  busy.update(true)
  t.mock.timers.tick(300)
  busy.update(false)
  t.mock.timers.tick(100)
  busy.update(true)
  t.mock.timers.tick(250)
  assert.deepEqual(changes, [true])
  busy.update(false)
  t.mock.timers.tick(1)
  assert.deepEqual(changes, [true, false])
  busy.dispose()
})

test('unmount cancels pending feedback', t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const busy = createBusyIndicator(() => assert.fail('disposed indicator updated the view'))
  busy.update(true)
  busy.dispose()
  t.mock.timers.tick(1000)
})
