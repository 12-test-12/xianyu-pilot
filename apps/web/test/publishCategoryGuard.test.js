import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

// Execute the page's real validate() so the pre-flight guard cannot drift from it.
const page = readFileSync(new URL('../src/pages/ProductPublishPage.vue', import.meta.url), 'utf8')
const source = page.slice(page.indexOf('function validate()'), page.indexOf('// 发布前主动调用'))

function validate({ category = { catId: '', isLeaf: true }, name = '本地分类', accountsAvailable = true } = {}) {
  const state = {
    accountsAvailable: { value: accountsAvailable },
    error: { value: '' },
    selectedCategoryNeedsPlatformConfirm: { value: Boolean(name) && !category?.catId },
    checks: { value: [] },
  }
  vm.createContext(state)
  vm.runInContext(source, state)
  return { ok: state.validate(), error: state.error.value }
}

test('a category without a marketplace catId never reaches the publish request', () => {
  const result = validate()
  assert.equal(result.ok, false)
  assert.match(result.error, /平台类目 ID/)
  assert.match(result.error, /重新识别分类/)
})

test('the page source keeps the guard wired to the live category check', () => {
  const template = page.slice(page.indexOf('<CardPanel title="商品分类"'), page.indexOf('<CardPanel title="发布地区"'))
  assert.match(template, /v-if="selectedCategoryNeedsPlatformConfirm"/)
  assert.match(template, /重新识别分类/)
  assert.match(page, /const selectedCategoryNeedsPlatformConfirm = computed\(\(\) =>/)
})

test('a marketplace category still passes validation', () => {
  const result = validate({ category: { catId: '91000001', isLeaf: true } })
  assert.equal(result.ok, true)
  assert.equal(result.error, '')
})

test('an unknown account list still blocks first', () => {
  const result = validate({ accountsAvailable: false })
  assert.equal(result.ok, false)
  assert.match(result.error, /账号列表状态未知/)
})
