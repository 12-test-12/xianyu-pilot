<template>
  <div class="m-home">
    <header class="m-home-head">
      <h1>店铺概览</h1>
      <p>查看账号、商品、订单和发货情况</p>
    </header>

    <div v-if="statsWarning" class="m-section m-data-warning" role="status">
      <span>{{ statsWarning }}</span>
      <button type="button" @click="loadStats">重试</button>
    </div>

    <div class="m-stats">
      <button type="button" class="m-stat-card" @click="navigate('accounts')">
        <span class="m-stat-icon">
          <MIcon name="account" :size="24" />
        </span>
        <span class="m-stat-info">
          <span class="m-stat-label">闲鱼账号</span>
          <span class="m-stat-value">{{ availability.accounts ? stats.accounts : '—' }}</span>
          <span class="m-stat-desc m-text-green">{{ availability.accounts ? `${stats.onlineAccounts} 个在线` : '账号统计不可用' }}</span>
        </span>
      </button>
      <button type="button" class="m-stat-card" @click="navigate('products')">
        <span class="m-stat-icon">
          <MIcon name="bag" :size="24" />
        </span>
        <span class="m-stat-info">
          <span class="m-stat-label">商品总数</span>
          <span class="m-stat-value">{{ availability.products ? stats.products : '—' }}</span>
          <span class="m-stat-desc m-text-green">{{ availability.products ? `在售 ${stats.onSale}` : '在售统计不可用' }}</span>
        </span>
      </button>
      <button type="button" class="m-stat-card" @click="navigate('data')">
        <span class="m-stat-icon">
          <MIcon name="package" :size="24" />
        </span>
        <span class="m-stat-info">
          <span class="m-stat-label">待发货</span>
          <span class="m-stat-value">{{ availability.dashboard ? stats.pendingDelivery : '—' }}</span>
          <span class="m-stat-desc m-text-orange">待处理</span>
        </span>
      </button>
      <button type="button" class="m-stat-card" @click="navigate('delivery-records')">
        <span class="m-stat-icon">
          <MIcon name="truck" :size="24" />
        </span>
        <span class="m-stat-info">
          <span class="m-stat-label">发货成功</span>
          <span class="m-stat-value">{{ availability.dashboard ? stats.deliverySuccess : '—' }}</span>
          <span class="m-stat-desc m-text-green">今日</span>
        </span>
      </button>
      <button type="button" class="m-stat-card" @click="navigate('data')">
        <span class="m-stat-icon">
          <MIcon name="trendDown" :size="24" />
        </span>
        <span class="m-stat-info">
          <span class="m-stat-label">今日订单</span>
          <span class="m-stat-value">{{ availability.dashboard ? stats.todayOrders : '—' }}</span>
          <span class="m-stat-desc">订单数</span>
        </span>
      </button>
      <button type="button" class="m-stat-card" @click="tabChange('message')">
        <span class="m-stat-icon">
          <MIcon name="chat" :size="24" />
        </span>
        <span class="m-stat-info">
          <span class="m-stat-label">最近通知</span>
          <span class="m-stat-value">{{ notificationAvailable ? notifications.length : '—' }}</span>
          <span class="m-stat-desc m-text-green">
            {{ notificationAvailable ? (notifications.length > 0 ? '已加载最近记录' : '暂无最近通知') : '通知列表不可用' }}
          </span>
        </span>
      </button>
    </div>

    <div class="m-section">
      <div class="m-section-header">
        <h2>快捷功能</h2>
        <button class="m-section-more" @click="emit('force-desktop')">全部功能 <MIcon name="chevronRight" :size="14" /></button>
      </div>
      <div class="m-quick-grid">
        <button type="button" class="m-quick-item" @click="navigate('data')">
          <span class="m-quick-icon"><MIcon name="chart" :size="26" /></span>
          <span class="m-quick-info">
            <span class="m-quick-title">数据看板</span>
            <span class="m-quick-desc">查看订单、发货和自动化概况</span>
          </span>
          <MIcon name="chevronRight" :size="18" class="m-quick-arrow" />
        </button>
        <button type="button" class="m-quick-item" @click="tabChange('message')">
          <span class="m-quick-icon"><MIcon name="chat" :size="26" /></span>
          <span class="m-quick-info">
            <span class="m-quick-title">在线消息</span>
            <span class="m-quick-desc">快速进入买家会话处理入口</span>
          </span>
          <MIcon name="chevronRight" :size="18" class="m-quick-arrow" />
        </button>
        <button type="button" class="m-quick-item" @click="navigate('accounts')">
          <span class="m-quick-icon"><MIcon name="shield" :size="26" /></span>
          <span class="m-quick-info">
            <span class="m-quick-title">账号状态</span>
            <span class="m-quick-desc">检查 Cookie、连接和验证状态</span>
          </span>
          <MIcon name="chevronRight" :size="18" class="m-quick-arrow" />
        </button>
        <button type="button" class="m-quick-item" @click="navigate('products')">
          <span class="m-quick-icon"><MIcon name="bag" :size="26" /></span>
          <span class="m-quick-info">
            <span class="m-quick-title">商品管理</span>
            <span class="m-quick-desc">商品查看、发布、改价与状态管理</span>
          </span>
          <MIcon name="chevronRight" :size="18" class="m-quick-arrow" />
        </button>
        <button type="button" class="m-quick-item" @click="navigate('settings-notify')">
          <span class="m-quick-icon"><MIcon name="bell" :size="26" /></span>
          <span class="m-quick-info">
            <span class="m-quick-title">通知设置</span>
            <span class="m-quick-desc">配置异常提醒和应用内通知</span>
          </span>
          <MIcon name="chevronRight" :size="18" class="m-quick-arrow" />
        </button>
        <button type="button" class="m-quick-item" @click="navigate('auto-delivery')">
          <span class="m-quick-icon"><MIcon name="package" :size="26" /></span>
          <span class="m-quick-info">
            <span class="m-quick-title">自动发货</span>
            <span class="m-quick-desc">设置发货规则并查看实际执行结果</span>
          </span>
          <MIcon name="chevronRight" :size="18" class="m-quick-arrow" />
        </button>
      </div>
    </div>

    <div class="m-section">
      <div class="m-section-header">
        <h2>新手快速开始</h2>
        <button class="m-section-more" @click="emit('force-desktop')">查看全部 <MIcon name="chevronRight" :size="14" /></button>
      </div>
      <div class="m-starter-row">
        <button type="button" class="m-starter-item" :class="{ done: onboarding.addedAccount }" @click="navigate('accounts')">
          <span class="m-starter-icon" :class="onboarding.addedAccount ? 'm-starter-done' : 'm-starter-blue'">
            <MIcon :name="onboarding.addedAccount ? 'check' : 'userPlus'" :size="24" />
          </span>
          <span class="m-starter-title">添加闲鱼账号</span>
          <span class="m-starter-desc">{{ onboarding.addedAccount ? '已完成' : '扫码或手动添加' }}</span>
          <MIcon name="arrowRight" :size="16" class="m-starter-arrow" />
        </button>
        <button type="button" class="m-starter-item" :class="{ done: onboarding.syncedProducts }" @click="navigate('products')">
          <span class="m-starter-icon" :class="onboarding.syncedProducts ? 'm-starter-done' : 'm-starter-orange'">
            <MIcon :name="onboarding.syncedProducts ? 'check' : 'box'" :size="24" />
          </span>
          <span class="m-starter-title">同步线上商品</span>
          <span class="m-starter-desc">{{ onboarding.syncedProducts ? '已完成' : '进入商品管理' }}</span>
          <MIcon name="arrowRight" :size="16" class="m-starter-arrow" />
        </button>
        <button type="button" class="m-starter-item" :class="{ done: onboarding.configuredDelivery }" @click="navigate('auto-delivery')">
          <span class="m-starter-icon" :class="onboarding.configuredDelivery ? 'm-starter-done' : 'm-starter-green'">
            <MIcon :name="onboarding.configuredDelivery ? 'check' : 'rocket'" :size="24" />
          </span>
          <span class="m-starter-title">开启自动化</span>
          <span class="m-starter-desc">{{ onboarding.configuredDelivery ? '已完成' : '创建发货规则' }}</span>
          <MIcon name="arrowRight" :size="16" class="m-starter-arrow" />
        </button>
      </div>
      <div class="m-onboard-progress">
        <div class="m-onboard-bar" :style="{ width: onboardingProgress + '%' }"></div>
        <span class="m-onboard-text">{{ onboardingDoneCount }}/3 已完成</span>
      </div>
    </div>

    <div v-if="recentEvents.length > 0" class="m-section">
      <div class="m-section-header">
        <h2>实时动态</h2>
        <span class="m-live-badge"><span class="m-live-dot"></span>实时</span>
      </div>
      <div class="m-event-list">
        <div v-for="(evt, i) in recentEvents" :key="i" class="m-event-item">
          <div class="m-event-dot" :class="eventColorClass(evt)"></div>
          <div class="m-event-body">
            <div class="m-event-text">{{ formatEventText(evt) }}</div>
            <div class="m-event-time">{{ formatEventTime(evt) }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="notifications.length > 0" class="m-section">
      <div class="m-section-header">
        <h2>最近通知</h2>
      </div>
      <div class="m-notice-list">
        <div v-for="n in notifications" :key="n.id || n.title" class="m-notice-item">
          <div class="m-notice-icon" :class="'m-notice-' + (n.type || 'info')">
            <MIcon :name="n.icon || 'bell'" :size="16" />
          </div>
          <div class="m-notice-body">
            <div class="m-notice-title">{{ n.title }}</div>
            <div class="m-notice-desc">{{ n.content || n.message || n.desc }}</div>
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="notificationError" class="m-section m-data-warning" role="status">{{ notificationError }}</div>

    <div class="m-pc-notice">
      <div class="m-pc-notice-icon">
        <MIcon name="warning" :size="28" />
      </div>
      <div class="m-pc-notice-content">
        <div class="m-pc-notice-title">推荐在 PC 端完成复杂操作</div>
        <div class="m-pc-notice-desc">商品发布、批量删除、自动发货规则编辑等操作涉及较高风险，建议回到桌面端执行，保障账号安全。</div>
      </div>
      <div class="m-pc-notice-illus">
        <MIcon name="monitor" :size="48" />
      </div>
    </div>

    <div class="m-bottom-actions">
      <button class="m-btn m-btn-outline" @click="emit('logout')">
        <MIcon name="logout" :size="18" />退出登录
      </button>
      <button class="m-btn m-btn-primary" @click="emit('force-desktop')">
        <MIcon name="desktop" :size="18" />继续进入桌面版
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import MIcon from './MIcon.vue'
import { getAccountSummary } from '../api/accounts.js'
import { getGoodsStats } from '../api/goods.js'
import { getDashboardSummary } from '../api/dashboard.js'
import { getNavigationNotifications } from '../api/navigation.js'

const emit = defineEmits(['navigate', 'logout', 'force-desktop', 'tab-change'])

function navigate(page) { emit('navigate', page) }
function tabChange(tab) { emit('tab-change', tab) }

const stats = ref({
  accounts: 0, onlineAccounts: 0, products: 0, onSale: 0,
  pendingDelivery: 0, deliverySuccess: 0, deliveryFail: 0,
  todayOrders: 0
})
const availability = ref({ accounts: false, products: false, dashboard: false })
const statsLoading = ref(true)
const statsWarning = computed(() => {
  if (statsLoading.value) return ''
  const missing = Object.entries(availability.value).filter(([, ready]) => !ready).map(([key]) => ({
    accounts: '账号', products: '商品', dashboard: '运营'
  })[key])
  return missing.length ? `${missing.join('、')}统计暂不可用；未加载的数据以“—”显示。` : ''
})

const onboarding = ref({ addedAccount: false, syncedProducts: false, configuredDelivery: false })
const onboardingDoneCount = computed(() => Object.values(onboarding.value).filter(Boolean).length)
const onboardingProgress = computed(() => (onboardingDoneCount.value / 3) * 100)

const recentEvents = ref([])
const notifications = ref([])
const notificationError = ref('')
const notificationAvailable = ref(false)

async function loadStats() {
  statsLoading.value = true
  try {
    const [accRes, goodsRes, dashRes] = await Promise.allSettled([
      getAccountSummary(),
      getGoodsStats(),
      getDashboardSummary()
    ])
    if (accRes.status === 'fulfilled' && accRes.value?.data) {
      availability.value.accounts = true
      stats.value.accounts = accRes.value.data.total ?? 0
      stats.value.onlineAccounts = accRes.value.data.wsOnline ?? 0
      onboarding.value.addedAccount = stats.value.accounts > 0
    } else availability.value.accounts = false
    if (goodsRes.status === 'fulfilled' && goodsRes.value?.data) {
      availability.value.products = true
      stats.value.products = goodsRes.value.data.total ?? 0
      stats.value.onSale = goodsRes.value.data.onSale ?? 0
      onboarding.value.syncedProducts = stats.value.products > 0
    } else availability.value.products = false
    if (dashRes.status === 'fulfilled' && dashRes.value?.data) {
      availability.value.dashboard = true
      const d = dashRes.value.data
      stats.value.pendingDelivery = d.pendingDelivery ?? d.pendingDeliveryCount ?? 0
      stats.value.deliverySuccess = d.deliverySuccess ?? d.deliverySuccessCount ?? 0
      stats.value.deliveryFail = d.deliveryFail ?? d.deliveryFailCount ?? 0
      stats.value.todayOrders = d.todayOrderCount ?? d.orderCount ?? 0
      onboarding.value.configuredDelivery = (stats.value.deliverySuccess > 0) || (d.autoDeliveryEnabled === true)
    } else availability.value.dashboard = false
  } finally {
    statsLoading.value = false
  }
}

async function loadNotifications() {
  notificationError.value = ''
  notificationAvailable.value = false
  try {
    const res = await getNavigationNotifications({ limit: 3 })
    const records = Array.isArray(res?.data) ? res.data : res?.data?.records
    if (!Array.isArray(records)) throw new Error('invalid notification response')
    notifications.value = records.slice(0, 3)
    notificationAvailable.value = true
  } catch {
    notifications.value = []
    notificationError.value = '最近通知暂不可用，请稍后刷新。'
  }
}

function onSseEvent(event) {
  const detail = event?.detail || {}
  if (!detail.type && !detail.eventType) return
  recentEvents.value.unshift({
    type: detail.type || detail.eventType,
    direction: detail.direction,
    message: detail.message || detail.content || detail.text,
    time: new Date()
  })
  if (recentEvents.value.length > 8) recentEvents.value.length = 8
}

function formatEventText(evt) {
  if (evt.message) return evt.message
  const t = evt.type || ''
  const dir = String(evt.direction || '').toUpperCase()
  if (t === 'message' && dir !== 'OUT') return '收到新消息'
  if (t === 'message' && dir === 'OUT') return '消息已发送'
  if (t.includes('cookie')) return 'Cookie 状态已更新'
  if (t.includes('account')) return '账号状态变更'
  if (t.includes('delivery')) return '自动发货通知'
  if (t.includes('workflow')) return '工作流执行通知'
  return t || '系统通知'
}

function formatEventTime(evt) {
  const d = evt.time instanceof Date ? evt.time : new Date(evt.time)
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`
}

function eventColorClass(evt) {
  const t = evt.type || ''
  if (t === 'message') return 'm-dot-blue'
  if (t.includes('error') || t.includes('fail')) return 'm-dot-red'
  if (t.includes('success') || t.includes('delivery')) return 'm-dot-green'
  return 'm-dot-gray'
}

onMounted(() => {
  loadStats()
  loadNotifications()
  window.addEventListener('xya-sse-event', onSseEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener('xya-sse-event', onSseEvent)
})
</script>

<style scoped>
.m-home {
  padding: 12px 16px 0;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  overflow-x: hidden;
}

.m-home-head {
  margin: 4px 0 14px;
}
.m-home-head h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.2;
  text-wrap: balance;
}
.m-home-head p {
  margin: 6px 0 0;
  color: var(--muted);
  line-height: 1.5;
  text-wrap: pretty;
}

.m-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 96px), 1fr));
  gap: 8px;
  margin-bottom: 14px;
}
.m-stat-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
  min-width: 0;
  padding: 9px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  text-align: left;
}
.m-stat-card:active { background: #edf2fa; }
.m-stat-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  color: var(--primary);
}
.m-stat-icon :deep(svg) { width: 20px; height: 20px; }
.m-stat-label, .m-stat-desc { display: block; font-size: 12px; color: var(--muted); }
.m-stat-value {
  display: block;
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.m-stat-info { min-width: 0; overflow-wrap: anywhere; }
.m-text-green { color: #067647; }
.m-text-orange { color: #9a4e08; }

.m-section {
  background: var(--card); border-radius: var(--radius); padding: 12px; margin-bottom: 14px;
  border: 1px solid var(--line);
}
.m-data-warning {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #8a4b08;
  background: #fff8e8;
  border-color: #f6d58a;
  font-size: 13px;
  line-height: 1.5;
}
.m-data-warning button {
  min-height: 44px;
  padding: 0 16px;
  flex-shrink: 0;
  border: 1px solid #e2ad3b;
  border-radius: 12px;
  color: #744006;
  background: white;
  font-weight: 600;
  cursor: pointer;
}
.m-section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; gap: 8px; }
.m-section-header h2 { margin: 0; font-size: 17px; font-weight: 700; color: #15213d; min-width: 0; }
.m-section-more {
  display: inline-flex; align-items: center; gap: 2px;
  background: none; border: none; font-size: 13px; color: #72809a;
  padding: 4px 8px; min-height: 44px; box-sizing: border-box; cursor: pointer; flex-shrink: 0;
}
.m-section-more :deep(svg) { color: #72809a; }
.m-live-badge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; color: #ff5252; font-weight: 600;
}
.m-live-dot {
  width: 8px; height: 8px; border-radius: 50%; background: #ff5252;
  animation: m-live-pulse 1.5s infinite;
}
@keyframes m-live-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.3); }
}

.m-quick-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 206px), 1fr)); gap: 8px; }
.m-quick-item {
  display: flex; align-items: center; gap: 10px; min-width: 0; min-height: 54px;
  padding: 8px; background: var(--bg); border: 0; border-radius: 8px; text-align: left;
}
.m-quick-item:active { background: #edf2fa; }
.m-quick-icon {
  display: grid; place-items: center; flex-shrink: 0; width: 34px; height: 34px;
  border-radius: 7px; background: #eaf1fd; color: var(--primary);
}
.m-quick-icon :deep(svg) { width: 20px; height: 20px; }
.m-quick-info { flex: 1; min-width: 0; }
.m-quick-title { display: block; font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 2px; }
.m-quick-desc { display: block; font-size: 12px; color: var(--muted); line-height: 1.45; text-wrap: pretty; }
.m-quick-arrow { color: var(--muted); flex-shrink: 0; }

.m-starter-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
.m-starter-item {
  background: var(--bg); border: 0; border-radius: 8px; padding: 10px; min-width: 0;
  text-align: left; cursor: pointer; position: relative; transition: background 0.15s;
}
.m-starter-item.done { background: #e8f8ee; }
.m-starter-item:active { background: #eef4ff; }
.m-starter-icon {
  width: 44px; height: 44px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center; margin-bottom: 10px;
}
.m-starter-blue { background: #e8f1ff; color: #0d6bff; }
.m-starter-orange { background: #fff4e0; color: #ff9f22; }
.m-starter-green { background: #e2f8ee; color: #16bf78; }
.m-starter-done { background: #d4f5e2; color: #16bf78; }
.m-starter-title { display: block; font-size: 13px; font-weight: 600; color: #15213d; margin-bottom: 2px; }
.m-starter-desc { display: block; font-size: 11px; color: #8c98ae; }
.m-starter-arrow {
  position: absolute; top: 12px; right: 10px; color: #c4cddb;
  width: 22px; height: 22px; background: rgba(255,255,255,0.8); border-radius: 50%; padding: 3px;
}
.m-onboard-progress {
  margin-top: 14px; height: 8px; background: #f0f4fa; border-radius: 4px; position: relative; overflow: hidden;
}
.m-onboard-bar {
  height: 100%; background: var(--primary);
  border-radius: 4px; transition: width 0.3s;
}
.m-onboard-text {
  position: absolute; right: 0; top: -20px; font-size: 11px; color: #8c98ae;
}

.m-event-list { display: flex; flex-direction: column; gap: 10px; }
.m-event-item { display: flex; gap: 10px; align-items: flex-start; }
.m-event-dot {
  width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0;
}
.m-dot-blue { background: #0d6bff; }
.m-dot-red { background: #ff5252; }
.m-dot-green { background: #16bf78; }
.m-dot-gray { background: #c4cddb; }
.m-event-body { flex: 1; min-width: 0; }
.m-event-text { font-size: 13px; color: #15213d; font-weight: 500; }
.m-event-time { font-size: 11px; color: #b0bacb; margin-top: 2px; }

.m-notice-list { display: flex; flex-direction: column; gap: 8px; }
.m-notice-item { display: flex; gap: 10px; padding: 10px; background: #f8faff; border-radius: 12px; }
.m-notice-icon {
  width: 32px; height: 32px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.m-notice-info { background: #e8f1ff; color: #0d6bff; }
.m-notice-warn { background: #fff4e0; color: #ff9f22; }
.m-notice-error { background: #ffeaea; color: #ff5252; }
.m-notice-success { background: #e2f8ee; color: #16bf78; }
.m-notice-body { flex: 1; min-width: 0; }
.m-notice-title { font-size: 13px; font-weight: 600; color: #15213d; margin-bottom: 2px; }
.m-notice-desc { font-size: 12px; color: #8c98ae; line-height: 1.5; }

.m-pc-notice {
  background: linear-gradient(135deg, #fff9e8 0%, #fffdf5 100%);
  border: 1px solid #ffeec2; border-radius: 16px; padding: 16px;
  display: flex; gap: 12px; margin-bottom: 16px; position: relative; overflow: hidden;
}
.m-pc-notice-icon {
  width: 44px; height: 44px; border-radius: 50%;
  background: linear-gradient(135deg, #ffd88a, #ffb94a); color: white;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.m-pc-notice-content { flex: 1; min-width: 0; }
.m-pc-notice-title { font-size: 15px; font-weight: 700; color: #8a5a00; margin-bottom: 4px; }
.m-pc-notice-desc { font-size: 12px; color: #a07020; line-height: 1.6; }
.m-pc-notice-illus { position: absolute; right: 12px; bottom: 8px; color: #f0c56a; opacity: 0.6; }

.m-bottom-actions { display: flex; gap: 10px; padding: 4px 0 0; }
.m-btn {
  flex: 1; height: 48px; min-width: 0; border-radius: 24px; border: none;
  font-size: 15px; font-weight: 600;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  cursor: pointer; transition: transform 0.1s;
}
.m-btn:active { transform: scale(0.97); }
.m-btn-outline { background: white; color: #15213d; border: 1.5px solid #e0e6f0; }
.m-btn-primary { background: var(--primary); color: white; }

@media (max-width: 360px) {
  .m-home { padding-inline: 12px; }
}
</style>
