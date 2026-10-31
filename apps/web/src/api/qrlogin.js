import request from '../utils/request.js'

export const generateQrLogin = (data = {}) => request.post(
  '/qrlogin/generate',
  data,
  { background: true, suppressGlobalError: true }
)

// 扫码状态轮询与扫码流程均标记为 background，避免闲鱼 API 响应慢导致请求堆积时
// 触发全局"正在同步数据..."横幅遮挡扫码模态框，且不因轮询偶发抖动弹出全局错误横幅。
export const getQrLoginStatus = (sessionId, data = {}) => request.post(
  `/qrlogin/status/${encodeURIComponent(sessionId)}`,
  data,
  { background: true, suppressGlobalError: true },
)

export const cleanupQrLogin = () => request.post(
  '/qrlogin/cleanup',
  {},
  { background: true, suppressGlobalError: true }
)

