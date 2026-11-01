import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { captureProductAsyncContext, isProductAsyncRequestCurrent } from '../src/utils/productPublishState.js'
import { publishCategoryFromNode } from '../src/utils/publishCategory.js'

const page = readFileSync(new URL('../src/pages/ProductPublishPage.vue', import.meta.url), 'utf8')
const source = [
  page.slice(page.indexOf('function markManualCategorySelection('), page.indexOf('function selectLevel1(')),
  page.slice(page.indexOf('async function triggerAutoCategory('), page.indexOf('async function refreshCategoriesInBackground(')),
  page.slice(page.indexOf('function applyAutoCategory('), page.indexOf('function selectCategoryByPath(')),
].join('\n')
const ref = value => ({ value })
const candidate = { catId: '91000001', catName: '新推荐分类', channelCatId: '92000001' }

function flow(selected = true) {
  let resolve
  const calls = []
  const state = {
    form: { accountId: 1, title: '标题', description: '描述', imageUrls: ['cover'] },
    categoryRevision: 0, autoCategoryRequestVersion: 0, aiCategoryRequestVersion: 0,
    autoCategoryLoading: ref(false), aiCategoryLoading: ref(false),
    userManuallySelectedCategory: ref(selected),
    autoCategoryMessage: ref(''), autoCategoryMsgType: ref(''), autoCategoryCandidates: ref([]), autoSelectedCatId: ref(''), autoCategorySource: ref(null),
    selectedCategoryName: ref(selected ? '当前分类' : ''), selectedCategoryPath: ref(''),
    selectedPublishCategory: ref(selected ? { catId: '91000002', catName: '当前分类' } : null),
    selectedCategoryIds: ref([]), level1Id: ref(null), level2Id: ref(null), level3Id: ref(null), level2List: ref([]), level3List: ref([]),
    autoCategory: (account, body) => { calls.push({ account, body }); return new Promise(done => { resolve = done }) },
    isProductAsyncRequestCurrent, publishCategoryFromNode,
    findCategoryOption: () => null, refreshCategoriesInBackground: async () => {},
  }
  state.productAsyncContext = () => captureProductAsyncContext({
    accountId: state.form.accountId, title: state.form.title, description: state.form.description,
    coverImageUrl: state.form.imageUrls[0], categoryRevision: state.categoryRevision,
  })
  vm.createContext(state)
  vm.runInContext(source, state)
  return { state, calls, respond: () => resolve({ data: { success: true, selectedCategory: candidate, candidates: [candidate] } }) }
}

test('forced refresh bypasses the cache but preserves the selected category', async () => {
  const { state, calls, respond } = flow()
  const selected = state.selectedPublishCategory.value
  const pending = state.triggerAutoCategory(true)
  respond()
  await pending
  assert.equal(calls[0].body.forceRefresh, true)
  assert.equal(state.selectedPublishCategory.value, selected)
  assert.equal(state.selectedCategoryName.value, '当前分类')
  assert.equal(state.autoCategoryCandidates.value[0].catId, candidate.catId)
})

test('recognition can fill an empty selection once', async () => {
  const { state, respond } = flow(false)
  const pending = state.triggerAutoCategory()
  respond()
  await pending
  assert.equal(state.selectedPublishCategory.value.catId, candidate.catId)
  assert.equal(state.categoryRevision, 1)
  assert.equal(state.autoCategoryLoading.value, false)
})

test('a pending result cannot overwrite a later manual or AI selection', async () => {
  for (const manual of [true, false]) {
    const { state, respond } = flow(false)
    const pending = state.triggerAutoCategory()
    state.applyAutoCategory({ catId: '91000999', catName: '后来选择的分类' }, { manual })
    respond()
    await pending
    assert.equal(state.selectedPublishCategory.value.catId, '91000999')
    assert.equal(state.selectedCategoryName.value, '后来选择的分类')
    assert.equal(state.autoCategoryLoading.value, false)
  }
})

test('recognition responses from an old account, title or cover are ignored', async () => {
  for (const change of [state => { state.form.accountId = 2 }, state => { state.form.title = '新标题' }, state => { state.form.imageUrls = ['new-cover'] }]) {
    const { state, respond } = flow(false)
    const pending = state.triggerAutoCategory()
    change(state)
    respond()
    await pending
    assert.equal(state.selectedPublishCategory.value, null)
    assert.equal(state.autoCategoryCandidates.value.length, 0)
  }
})
