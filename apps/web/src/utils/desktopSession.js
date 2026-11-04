import { setAuth } from './auth.js'

// Desktop hosts inject a bootstrap capability into the original index.html.
// A regular server build has no marker and retains its original login flow.
export async function initializeDesktopSession() {
  const marker = document.querySelector('meta[name="xianyu-desktop-bootstrap"]')
  if (!marker) return
  const response = await fetch('/api/desktop/session', {
    method: 'POST',
    headers: { 'X-Desktop-Bootstrap': marker.content, 'Content-Type': 'application/json' },
    body: '{}',
  })
  if (!response.ok) throw new Error('本地会话初始化失败，请重新打开客户端')
  const result = await response.json()
  if (result.code !== 200 || !result.data?.token) throw new Error('本地会话返回异常')
  setAuth(result.data.token, result.data.username)
  marker.remove()
}
