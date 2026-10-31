// Delay quick requests and hold visible feedback long enough to avoid flashes.
export function createBusyIndicator(onChange, { delay = 300, minVisible = 350 } = {}) {
  let timer = null, visible = false, shownAt = 0, disposed = false, active = false
  function clearTimer() {
    if (timer !== null) clearTimeout(timer)
    timer = null
  }
  function update(busy) {
    if (disposed || active === busy) return
    active = busy
    clearTimer()
    if (busy && !visible) {
      timer = setTimeout(() => {
        timer = null
        visible = true
        shownAt = Date.now()
        onChange(true)
      }, delay)
    } else if (!busy && visible) {
      timer = setTimeout(() => {
        timer = null
        visible = false
        onChange(false)
      }, Math.max(0, minVisible - (Date.now() - shownAt)))
    }
  }
  return { update, dispose() { disposed = true; clearTimer() } }
}
