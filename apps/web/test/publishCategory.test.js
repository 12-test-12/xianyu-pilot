import test from 'node:test'
import assert from 'node:assert/strict'
import { categoryNodeAtPath, publishCategoryFromNode } from '../src/utils/publishCategory.js'

test('UI node IDs never become marketplace IDs', () => {
  const node = { id: 5893, label: '本地分类' }
  const info = publishCategoryFromNode(node)
  assert.equal(info.catId, '')
  assert.equal(info.source, 'local')
  assert.equal(info.isLeaf, true)
  const live = publishCategoryFromNode({ ...node, catId: '91000001', channelCatId: '92000001', tbCatId: '93000001' }, 'xianyu')
  assert.equal(live.catId, '91000001')
  assert.equal(live.channelCatId, '92000001')
  assert.equal(live.tbCatId, '93000001')
})

test('four-level category paths resolve to the final leaf, while parents cannot pass the leaf check', () => {
  const tree = [{ id: 1, children: [{ id: 2, children: [{ id: 3, children: [{ id: 4, label: '叶子' }] }] }] }]
  assert.equal(publishCategoryFromNode(categoryNodeAtPath(tree, [1, 2, 3])).isLeaf, false)
  assert.equal(publishCategoryFromNode(categoryNodeAtPath(tree, ['1', '2', '3', '4'])).catName, '叶子')
  assert.equal(categoryNodeAtPath(tree, [1, 9]), null)
})
