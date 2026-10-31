import request from '../utils/request.js'

export function getNotificationSettings() { return request.get('/notification-settings') }
export function saveNotificationSettings(data) { return request.post('/notification-settings', data) }
export function getNotifications(params = {}) { return request.get('/notifications', { params }) }
export function markNotificationRead(id) { return request.post(`/notifications/${id}/read`, {}) }
export function testNotification(data = {}) {
  return request.post('/notifications/test', data, { timeout: 65000, suppressGlobalError: true })
}
export function resolveNotificationTestAttempt(attemptId, data = {}) {
  return request.post(`/notifications/test/attempts/${attemptId}/resolve`, data)
}
export function getNotificationTestStatus(attemptId, data = {}) {
  return request.post(`/notifications/test/attempts/${attemptId}/status`, data, { suppressGlobalError: true })
}
export function getNotificationDeliveryLogs(params = {}) { return request.get('/notifications/delivery-logs', { params }) }
