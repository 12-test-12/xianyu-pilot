import request from './request.js'
import { isDesktopSession } from './desktopSession.js'

// 桌面宿主（PySide6 QWebEngine）与网页之间的扫码登录桥。
// 主路径：POST /api/desktop/login-window，由原生宿主弹出登录窗口。
// 兜底：主文档跳转自定义协议，宿主在 acceptNavigationRequest 中拦截。
// 回传：宿主调用 window.__xianyuDesktopLogin({ cookie, accountId })。
const DESKTOP_LOGIN_PROTOCOL = 'xianyu-desktop://login'
const DESKTOP_LOGIN_GLOBAL = '__xianyuDesktopLogin'
const LOGIN_WINDOW_URL = '/desktop/login-window'

function normalizeAccountId(value) {
  if (value === null || value === undefined || value === '') return null
  const accountId = Number(value)
  return Number.isInteger(accountId) && accountId > 0 ? accountId : null
}

// 只接受宿主约定的最小载荷；Cookie 必须含 unb=，否则视为无效回传。
function normalizePayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  const cookie = typeof payload.cookie === 'string' ? payload.cookie.trim() : ''
  if (!cookie || !cookie.includes('unb=')) return null
  return { cookie, accountId: normalizeAccountId(payload.accountId) }
}

function protocolUrl(accountId) {
  return accountId === null ? DESKTOP_LOGIN_PROTOCOL : `${DESKTOP_LOGIN_PROTOCOL}?accountId=${accountId}`
}

export function isDesktopHost() {
  return isDesktopSession()
}

// 返回 true 表示已尝试唤起登录窗口；非桌面宿主不做任何跳转。
export async function requestDesktopLogin(accountId = null) {
  if (!isDesktopHost()) return false
  const targetAccountId = normalizeAccountId(accountId)
  const opened = await request({
    url: LOGIN_WINDOW_URL,
    method: 'post',
    data: { accountId: targetAccountId },
    background: true,
    suppressGlobalError: true,
  })
    .then(res => {
      // 路由未合并前可能返回 404/409，或返回 ok:false；这些情况都走协议兜底。
      const data = res?.data && typeof res.data === 'object' ? res.data : res
      return data?.ok !== false
    })
    .catch(() => false)
  if (opened) return true
  window.location.href = protocolUrl(targetAccountId)
  return true
}

export function registerDesktopLoginHandler(handler) {
  if (typeof handler !== 'function') return false
  window[DESKTOP_LOGIN_GLOBAL] = payload => {
    const login = normalizePayload(payload)
    if (!login) {
      // 不回显原始载荷，避免把 Cookie 写进控制台。
      console.warn('[desktopBridge] 已忽略不符合约定的桌面扫码登录回传')
      return Promise.resolve(false)
    }
    return Promise.resolve()
      .then(() => handler(login))
      .catch(error => {
        console.warn('[desktopBridge] 桌面扫码登录回传处理失败:', error?.message || error)
        return false
      })
  }
  return true
}
