import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'
import './auth-pages.css'
import { initializeDesktopSession } from './utils/desktopSession.js'
import { isDesktopHost, registerDesktopLoginHandler } from './utils/desktopBridge.js'
import { createAccountByCookie, updateAccountCookie } from './api/accounts.js'
import { extractKeyFields } from './utils/cookie.js'

// 与仓库既有约定一致：轻提示通过 xya-toast 事件广播，不在此处引入组件。
function notifyDesktopLogin(message, isError = false) {
  window.dispatchEvent(new CustomEvent('xya-toast', { detail: { message, isError } }))
}

// 宿主扫码成功后回灌 Cookie：accountId 为空表示新增账号，否则更新该账号。
async function handleDesktopLogin({ cookie, accountId }) {
  try {
    // 与手动添加/更新 Cookie 的调用保持一致，同时带上从 Cookie 解析出的关键字段。
    const keyFields = extractKeyFields(cookie)
    if (accountId !== null) {
      await updateAccountCookie(accountId, cookie, { unb: keyFields.unb, mH5Tk: keyFields.mH5Tk })
      notifyDesktopLogin('闲鱼账号 Cookie 已更新')
    } else {
      await createAccountByCookie({ cookie, extractedUnb: keyFields.unb, extractedMH5Tk: keyFields.mH5Tk })
      notifyDesktopLogin('闲鱼账号已添加')
    }
    window.dispatchEvent(new CustomEvent('xianyu:desktop-login', {
      detail: { ok: true, cookie, accountId },
    }))
  } catch (error) {
    notifyDesktopLogin(error?.message || '保存闲鱼账号 Cookie 失败', true)
    window.dispatchEvent(new CustomEvent('xianyu:desktop-login', {
      detail: { ok: false, cookie, accountId, message: error?.message || '' },
    }))
    throw error
  }
}

initializeDesktopSession()
  .catch(error => console.error(error.message))
  .finally(() => {
    if (isDesktopHost()) registerDesktopLoginHandler(handleDesktopLogin)
    createApp(App).mount('#app')
  })
