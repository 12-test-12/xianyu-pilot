import assert from 'node:assert/strict'
import test from 'node:test'
import { asyncPage } from '../src/components/asyncPage.js'

test('asyncPage creates a component with prefetch capability', async () => {
  let loadCalls = 0
  const mockComponent = { name: 'MockPage' }
  const loader = async () => {
    loadCalls++
    return mockComponent
  }

  const page = asyncPage(loader)
  assert.equal(typeof page.prefetch, 'function')

  // Calling prefetch returns the loaded module
  const p1 = page.prefetch()
  const p2 = page.prefetch()
  assert.equal(p1, p2)

  const res = await p1
  assert.equal(res, mockComponent)
  assert.equal(loadCalls, 1)
})

test('asyncPage avoids redundant loader executions on repeated prefetch', async () => {
  let loadCount = 0
  const loader = () => {
    loadCount++
    return Promise.resolve({ template: '<div>Dashboard</div>' })
  }

  const page = asyncPage(loader)
  await Promise.all([page.prefetch(), page.prefetch(), page.prefetch()])
  assert.equal(loadCount, 1)
})
