export function notificationTestStatusLabel(status) {
  return ({ pending: '等待发送', in_progress: '发送中', confirmed: '结果已确认', failed: '尚未发送', unknown: '结果未知', blocked: '等待核对', resolved: '已核对关闭', conflict: '测试记录冲突' })[status] || '待核对'
}

export function notificationTestErrorMessage(data = {}, backendMessage = '') {
  if (data.attemptStatus === 'blocked') return '该渠道已有待核对记录，请使用原测试记录完成核对或补写投递日志。'
  if (data.attemptStatus === 'in_progress') return '当前测试正在发送，请稍后核对本次记录。'
  if (data.attemptStatus === 'confirmed' && data.logPersisted === false) return '通知结果已确认，投递日志待补写；核对本次记录只会补日志，不会重发。'
  if (data.attemptStatus === 'failed' && data.retrySafe === true) return backendMessage || '通知尚未发送，修复网络或配置后可使用原测试重试。'
  return backendMessage || '通知测试结果未知，请到对应渠道核对本次记录；系统不会自动重发。'
}
