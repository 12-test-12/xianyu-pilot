// The versioned tree's `id` identifies a UI node, not a marketplace category.
export function publishCategoryFromNode(node, source = 'local') {
  if (!node || typeof node !== 'object') return null
  return {
    catName: String(node.catName || node.label || node.title || node.name || ''),
    catId: String(node.catId || ''),
    channelCatId: String(node.channelCatId || ''),
    tbCatId: String(node.tbCatId || ''),
    isLeaf: node.isLeaf !== false && !(node.children?.length),
    invalidated: node.invalidated === true,
    categoryPath: Array.isArray(node.categoryPath) ? [...node.categoryPath] : [node.channelCat1Name, node.channelCat2Name, node.channelCat3Name, node.catName || node.label || node.title || node.name].filter(Boolean),
    source,
  }
}

export function isCategoryRecoveryCurrent(payload, current) {
  if (!payload || !current) return false
  return String(payload.xianyuAccountId ?? '') === String(current.accountId ?? '')
    && String(payload.title || '') === String(current.title || '')
    && String(payload.description || '') === String(current.description || '')
    && String(payload.imageUrls?.[0] || '') === String(current.coverImageUrl || '')
}

export function categoryNodeAtPath(tree, ids) {
  let nodes = tree, selected = null
  for (const id of ids || []) {
    selected = (nodes || []).find(node => String(node.id) === String(id))
    if (!selected) return null
    nodes = selected.children
  }
  return selected
}
