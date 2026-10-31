import { defineAsyncComponent, h } from 'vue'

const Loading = {
  render: () => h('div', { class: 'page-loading', role: 'status' }, '页面加载中...'),
}
const ErrorPage = {
  render: () => h('div', { class: 'page-load-error', role: 'alert' }, [
    h('span', '页面加载失败。'),
    h('button', { type: 'button', onClick: () => location.reload() }, '重新加载'),
  ]),
}

export const asyncPage = loader => defineAsyncComponent({
  loader,
  loadingComponent: Loading,
  errorComponent: ErrorPage,
  delay: 120,
  timeout: 30000,
  onError(_error, retry, fail, attempts) {
    if (navigator.onLine !== false && attempts < 2) retry()
    else fail()
  },
})
