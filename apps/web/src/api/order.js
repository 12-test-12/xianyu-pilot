import request from '../utils/request.js'

export const listOrders = data => request.post('/order/list', data)

// 批量刷新订单：后端会先触发平台订单同步，再回读本地最新数据。
// 同步失败不会抛异常，错误原因在返回体 data.syncErrors 中。
export const refreshOrders = (data, config) => request.post('/order/batchRefresh', data, {
  timeout: 300000,
  ...config
})
