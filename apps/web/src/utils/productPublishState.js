export function canSubmitPublishIntent({
  accountsAvailable,
  submitting,
  hasIntent,
  outcome,
}) {
  if (accountsAvailable !== true || submitting) return false
  const status = String(outcome?.status || '')
  if (status === 'unknown' || status === 'in_progress') return false
  if (hasIntent && status === 'failed' && outcome?.retrySafe !== true) return false
  return true
}

export function captureProductAsyncContext({
  accountId,
  title,
  description,
  coverImageUrl,
  categoryRevision = 0,
} = {}) {
  return {
    accountId: String(accountId ?? ''),
    title: String(title ?? ''),
    description: String(description ?? ''),
    coverImageUrl: String(coverImageUrl ?? ''),
    categoryRevision: Number(categoryRevision) || 0,
  }
}

export function isProductAsyncRequestCurrent({
  requestVersion,
  currentVersion,
  snapshot,
  current,
  fields = ['accountId', 'title', 'description', 'coverImageUrl', 'categoryRevision'],
} = {}) {
  if (requestVersion !== currentVersion || !snapshot) return false
  const normalizedCurrent = captureProductAsyncContext(current)
  return fields.every(field => Object.is(snapshot[field], normalizedCurrent[field]))
}

export function buildPublishIntentSummary(payload, resolveAccountName = () => '') {
  const intent = payload && typeof payload === 'object' ? payload : {}
  const accountId = intent.xianyuAccountId ?? intent.accountId ?? ''
  const resolvedAccount = resolveAccountName(accountId)
  const account = resolvedAccount || (accountId ? `账号 ID ${accountId}` : '未选择')
  const title = String(intent.title || '未填写')
  const category = String(intent.category || '未选择')
  let price = intent.price != null && intent.price !== '' ? String(intent.price) : ''
  let stock = intent.stock != null ? Number(intent.stock) : null
  if (!price && Array.isArray(intent.itemSkuList) && intent.itemSkuList.length > 0) {
    const skuPrices = intent.itemSkuList.map(s => Number(s.price) || 0).filter(p => p > 0)
    price = skuPrices.length ? Math.min(...skuPrices).toFixed(2) : '0.00'
  }
  if ((stock == null || !Number.isFinite(stock)) && Array.isArray(intent.itemSkuList) && intent.itemSkuList.length > 0) {
    stock = intent.itemSkuList.reduce((sum, s) => sum + (Number(s.quantity) || 0), 0)
  }
  if (!price) price = '0.00'
  if (stock == null || !Number.isFinite(stock)) stock = 0
  const shipping = { free: '包邮', none: '线上交付 / 无需邮寄', fixed: '一口价 / 运费' }[intent.shippingMode] || '未选择'
  const region = [intent.location?.prov, intent.location?.city, intent.location?.area].filter(Boolean).join(' ') || '未选择'
  return `账号：${account}\n商品：${title}\n分类：${category}\n价格：¥${price}\n库存：${Number.isFinite(stock) ? stock : '未知'}\n交付方式：${shipping}\n发布地区：${region}`
}

export function recoverPublishIntent(saved) {
  if (!saved?.idempotencyKey || !saved.payload || typeof saved.payload !== 'object' || Array.isArray(saved.payload)) return null
  return {
    idempotencyKey: String(saved.idempotencyKey),
    payload: saved.payload,
    // A missing receipt is ambiguous, even if the previous shipping mode is
    // unsupported. Keep the key and payload for reconciliation/local repair.
    outcome: saved.outcome || { status: 'unknown', retrySafe: false },
  }
}

export function markPendingProductSync(storage) {
  try {
    const target = storage ?? globalThis.localStorage
    target?.setItem?.('xianyu_pending_sync', 'true')
    return { stored: true }
  } catch {
    return { stored: false }
  }
}
