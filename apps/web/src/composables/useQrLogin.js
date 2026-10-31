import { computed, reactive } from 'vue'
import { generateQrLogin, getQrLoginStatus } from '../api/qrlogin.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

// Each modal session owns its generation request and polling chain. Closing or
// refreshing invalidates outstanding responses, even if HTTP cannot be cancelled.
export function useQrLogin({ onConfirmed, generate = generateQrLogin, getStatus = getQrLoginStatus }) {
  const qr = reactive({ loading: false, sessionId: '', qrUrl: '', status: '', message: '', mode: 'create', accountId: null })
  const generation = createLatestRequestGuard()
  const polling = createLatestRequestGuard()
  let timer = null

  function stopQrPolling() {
    polling.invalidate()
    if (timer !== null) clearTimeout(timer)
    timer = null
  }

  function cancelQrLogin() {
    generation.invalidate()
    stopQrPolling()
  }

  function resetQrState() {
    cancelQrLogin()
    Object.assign(qr, { loading: false, sessionId: '', qrUrl: '', status: '', message: '', mode: 'create', accountId: null })
  }

  async function checkQrStatus(request) {
    const sessionId = qr.sessionId
    if (!sessionId || !request.isCurrent()) return
    try {
      const res = await getStatus(sessionId, qr.accountId ? { accountId: qr.accountId } : {})
      if (!request.isCurrent()) return
      const data = res.data || {}
      qr.status = data.status || qr.status
      if (['scanned', 'scaned'].includes(qr.status)) {
        qr.message = data.message || '已成功扫码，请在手机上点击确认登录'
      } else {
        qr.message = data.message || qr.message
      }
      if (qr.status === 'confirmed') {
        if (data.accountId) {
          const context = { mode: qr.mode, sessionId }
          stopQrPolling()
          await onConfirmed(data, context)
        } else {
          qr.message = data.credentialsAvailable
            ? '扫码已确认，服务端正在安全同步账号信息...'
            : (data.message || '扫码已确认，等待服务端完成账号同步...')
        }
      } else if (['error', 'expired', 'failed'].includes(qr.status)) {
        stopQrPolling()
        if (qr.status === 'error') qr.message = data.message || '账号保存失败，请重试'
      }
    } catch (e) {
      if (request.isCurrent()) qr.message = e.message || '查询扫码状态失败'
    }
  }

  function startQrPolling() {
    stopQrPolling()
    const request = polling.begin()
    const poll = async () => {
      timer = null
      await checkQrStatus(request)
      if (request.isCurrent()) timer = setTimeout(poll, 2000)
    }
    timer = setTimeout(poll, 2000)
  }

  async function startQrLogin() {
    // The inline refresh link and primary button share this same guard.
    if (qr.loading) return
    const request = generation.begin()
    stopQrPolling()
    qr.loading = true
    qr.status = 'generating'
    qr.message = '正在生成新二维码，请稍候...'
    try {
      const res = await generate(qr.accountId ? { accountId: qr.accountId } : {})
      if (!request.isCurrent()) return
      const data = res.data || {}
      const sessionId = data.sessionId || data.id || ''
      const qrUrl = data.qrCodeBase64 || data.qrImage || data.qrUrl || data.qrcodeUrl || data.qrCodeUrl || data.url || ''
      if (!sessionId || !qrUrl) throw new Error('二维码服务响应不完整，请稍后重试')
      // Validate both fields before replacing the previous image/session.
      Object.assign(qr, { sessionId, qrUrl, status: data.status || 'pending', message: data.message || '请使用闲鱼 App 扫码' })
      startQrPolling()
    } catch (e) {
      if (!request.isCurrent()) return
      qr.status = 'error'
      qr.message = e.message || '生成二维码失败'
    } finally {
      if (request.isCurrent()) qr.loading = false
    }
  }

  return {
    qr,
    qrReady: computed(() => Boolean(qr.sessionId && qr.qrUrl && !qr.loading && !['error', 'expired', 'failed'].includes(qr.status))),
    qrGenerationFailed: computed(() => qr.status === 'error'),
    startQrLogin, cancelQrLogin, resetQrState,
  }
}
