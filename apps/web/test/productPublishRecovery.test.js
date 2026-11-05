import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { canEditFailedPublishIntent } from '../src/utils/productPublishState.js'
import { isCategoryRecoveryCurrent } from '../src/utils/publishCategory.js'

// Execute the page's actual recovery/request handlers with controlled I/O.
const page = readFileSync(new URL('../src/pages/ProductPublishPage.vue', import.meta.url), 'utf8')
const handlers = page.slice(page.indexOf('function createPublishIntentKey()'), page.indexOf('// ---- 草稿'))
const ref = value => ({ value })

function flow({ outcome = null, publish, confirm = async () => true } = {}) {
  const storage = new Map()
  const payload = { xianyuAccountId: 1, title: '原商品', description: '描述', imageUrls: ['image'], price: '1', shippingMode: 'free' }
  const state = {
    publishIntent: { idempotencyKey: 'original-key', payload },
    publishOutcome: ref(outcome), submitting: ref(false), accountsAvailable: ref(true),
    autoDelivery: { enabled: false, sourceId: null },
    categoryRevision: 0, isCategoryRecoveryCurrent,
    error: ref(''), warning: ref(''), success: ref(''),
    PUBLISH_INTENT_KEY: 'intent',
    sessionStorage: {
      setItem: (key, value) => storage.set(key, value),
      getItem: key => storage.get(key),
      removeItem: key => storage.delete(key),
    },
    form: { accountId: 1, title: '修改后的商品', description: '描述', imageUrls: ['image'], price: '2', stock: 1 },
    shippingMode: ref('free'), selectedAddress: ref(null), selectedCategoryName: ref('分类'), selectedCategoryPath: ref('分类'), setShipping: () => {},
    selectedPublishCategory: ref({ catId: '91000002', catName: '分类', channelCatId: '92000002', tbCatId: '93000002', source: 'xianyu', isLeaf: true }),
    normalizePublishAddress: () => null,
    validate: () => true, ensureSelectedAccountCookieValid: async () => true,
    createSecureId: () => 'new-key',
    confirmationPayload: ref(payload), resolveIntentAccountName: () => '账号',
    buildPublishIntentSummary: () => '商品摘要',
    confirmAction: confirm,
    publishItem: publish,
  }
  state.productAsyncContext = () => ({ accountId: state.form.accountId, title: state.form.title, description: state.form.description, coverImageUrl: state.form.imageUrls[0] })
  state.applyAutoCategory = cat => { state.selectedPublishCategory.value = cat; state.selectedCategoryName.value = cat.catName }
  state.canEditFailedIntent = { get value() {
    return canEditFailedPublishIntent({ submitting: state.submitting.value, hasIntent: Boolean(state.publishIntent.payload), outcome: state.publishOutcome.value })
  } }
  vm.createContext(state)
  vm.runInContext(handlers, state)
  return { state, storage }
}

test('refusal releases busy state; editing retains content and creates a fresh request', async () => {
  const requests = []
  const { state, storage } = flow({ publish: async payload => {
    requests.push(payload)
    throw { message: '请先签署协议', data: { status: 'failed', retrySafe: true, retryScope: 'remote' } }
  } })
  await state.submit()
  assert.equal(state.submitting.value, false)
  assert.equal(state.canEditFailedIntent.value, true)
  assert.equal(requests[0].title, '原商品')
  state.editFailedPublish()
  assert.equal(state.form.title, '修改后的商品')
  assert.equal(state.publishIntent.payload, null)
  assert.equal(storage.has('intent'), false)
  await state.submit()
  assert.equal(requests[1].title, '修改后的商品')
  assert.equal(requests[1].idempotencyKey, 'new-key')
  assert.equal(requests[1].categoryInfo.catId, '91000002')
})

test('retry and legacy recovery keep the original payload and key', async () => {
  for (const retrySafe of [true, false]) {
    const requests = []
    const { state } = flow({ outcome: { status: 'failed', retrySafe }, publish: async payload => {
      requests.push(payload)
      throw { data: { status: 'failed', retrySafe: true } }
    } })
    await state.submit()
    assert.equal(requests[0].idempotencyKey, 'original-key')
    assert.equal(requests[0].title, '原商品')
  }
})

test('ambiguous and remotely confirmed requests cannot be cleared by returning to editing', async () => {
  for (const status of ['unknown', 'in_progress', 'remote_confirmed']) {
    const { state } = flow({ outcome: { status, retrySafe: false } })
    const original = state.publishIntent.payload
    state.editFailedPublish()
    assert.equal(state.publishIntent.payload, original)
    if (status !== 'remote_confirmed') await state.submit()
    assert.equal(state.publishOutcome.value.status, status)
  }
})

test('double click during confirmation issues only one request and cancellation releases busy state', async () => {
  let resolve, count = 0
  const { state } = flow({
    confirm: () => new Promise(done => { resolve = done }),
    publish: async () => { count++; throw { data: { status: 'failed', retrySafe: true } } },
  })
  const first = state.submit()
  await state.submit()
  assert.equal(state.submitting.value, true)
  resolve(true)
  await first
  assert.equal(count, 1)
  assert.equal(state.submitting.value, false)
  const pending = state.submit()
  resolve(false)
  await pending
  assert.equal(count, 1)
  assert.equal(state.submitting.value, false)
})

test('disposed category requires returning to editing rather than repeating the stale intent', async () => {
  const requests = []
  const { state } = flow({ publish: async payload => {
    requests.push(payload)
    throw { message: '该类目已废弃（错误码：FAIL_BIZ_CATEGORY_DISPOSED）', data: { status: 'failed', retrySafe: true } }
  } })
  await state.submit()
  assert.equal(state.publishOutcome.value.categoryInvalid, true)
  await state.submit()
  assert.equal(requests.length, 1)
  state.editFailedPublish()
  await state.submit()
  assert.equal(requests.length, 2)
  assert.equal(requests[1].idempotencyKey, 'new-key')
})

test('category rejection codes mark category invalid and prevent repeating', async () => {
  for (const code of ['FAIL_BIZ_ITEM_CATEGORY_INVALID', 'FAIL_BIZ_ITEM_CATEGORY_NOT_MATCH']) {
    const { state } = flow({ publish: async () => {
      throw { message: `分类不匹配（错误码：${code}）`, data: { status: 'failed', retrySafe: true } }
    } })
    await state.submit()
    assert.equal(state.publishOutcome.value.categoryInvalid, true)
  }
})

test('category recovery preserves content and only replaces the selection after an explicit click', async () => {
  const candidate = { catId: '91000999', catName: '新候选分类', isLeaf: true }
  const { state } = flow({ publish: async () => {
    throw { message: '类目需要更新', data: { status: 'failed', retrySafe: true, categoryRefreshRequired: true, categoryCandidates: [candidate] } }
  } })
  state.form.title = '原商品'
  const originalName = state.selectedCategoryName.value
  await state.submit()
  assert.equal(state.selectedCategoryName.value, originalName)
  assert.equal(state.selectedPublishCategory.value.invalidated, true)
  assert.equal(state.publishOutcome.value.categoryCandidates[0].catId, '91000999')
  state.chooseRecoveredCategory(candidate)
  assert.equal(state.selectedPublishCategory.value.catId, '91000999')
  assert.equal(state.form.title, '原商品')
  assert.equal(state.publishIntent.payload, null)
})

test('old recovery choices cannot be applied after the account or product changes', () => {
  const { state } = flow({ outcome: { status: 'failed', retrySafe: true, categoryInvalid: true } })
  const original = state.selectedPublishCategory.value
  state.chooseRecoveredCategory({ catId: '91000999', catName: '旧请求候选' })
  assert.equal(state.selectedPublishCategory.value, original)
  assert.equal(state.publishIntent.idempotencyKey, 'original-key')
})

test('restoring a failed intent into an empty form keeps its category invalid until reselected', () => {
  const { state } = flow({ outcome: { status: 'failed', retrySafe: true, categoryInvalid: true } })
  state.form.title = ''
  state.selectedCategoryName.value = ''
  state.selectedPublishCategory.value = null
  state.publishIntent.payload.category = '旧分类'
  state.publishIntent.payload.categoryInfo = { catId: '91000001', catName: '旧分类', isLeaf: true }
  state.editFailedPublish()
  assert.equal(state.form.title, '原商品')
  assert.equal(state.selectedPublishCategory.value.invalidated, true)
})
