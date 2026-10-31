import { defineAsyncComponent, h } from 'vue'

const LoadingSkeleton = {
  render: () =>
    h('div', { class: 'page-skeleton-placeholder', role: 'status', 'aria-label': '页面内容加载中' }, [
      h('div', { class: 'skeleton-shimmer skeleton-head' }),
      h('div', { class: 'skeleton-grid' }, [
        h('div', { class: 'skeleton-shimmer skeleton-card' }),
        h('div', { class: 'skeleton-shimmer skeleton-card' }),
        h('div', { class: 'skeleton-shimmer skeleton-card' }),
        h('div', { class: 'skeleton-shimmer skeleton-card' }),
      ]),
      h('div', { class: 'skeleton-shimmer skeleton-panel' }),
    ]),
}

const ErrorPage = {
  render: () =>
    h('div', { class: 'page-load-error', role: 'alert' }, [
      h('span', '页面加载失败，请检查网络或刷新重试。'),
      h('button', { type: 'button', onClick: () => location.reload() }, '重新加载'),
    ]),
}

// Keep the current page mounted until the destination code is ready. The
// fallback deadline still lets defineAsyncComponent display its error state.
export async function prefetchPage(component, timeout = 30000) {
  if (!component?.prefetch) return
  let timer
  try {
    await Promise.race([
      component.prefetch(),
      new Promise(resolve => { timer = setTimeout(resolve, timeout) }),
    ])
  } catch {
    // The async component owns loading errors and retries.
  } finally {
    clearTimeout(timer)
  }
}

export const asyncPage = loader => {
  let modulePromise = null
  const load = () => {
    if (!modulePromise) {
      modulePromise = Promise.resolve().then(loader)
    }
    return modulePromise
  }

  const component = defineAsyncComponent({
    loader: load,
    loadingComponent: LoadingSkeleton,
    errorComponent: ErrorPage,
    delay: 240, // 避免瞬时加载（已预加载或缓存中）时的闪烁与白页
    timeout: 30000,
    onError(_error, retry, fail, attempts) {
      if (navigator.onLine !== false && attempts < 2) {
        modulePromise = null // 重试前清除可能失败的缓存 promise
        retry()
      } else {
        fail()
      }
    },
  })

  component.prefetch = load
  return component
}
