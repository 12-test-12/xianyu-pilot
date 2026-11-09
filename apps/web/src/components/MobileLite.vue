<template>
  <div class="mobile-shell">
    <header v-if="!subPage" class="m-topbar">
      <button type="button" class="m-brand" aria-label="返回移动端首页" @click="switchTab('home')">
        <img src="/xya/brand/app-icon.png" alt="" />
        <span>闲鱼助手</span>
      </button>
      <button type="button" class="m-user" aria-label="打开个人中心" @click="switchTab('profile')">
        <span class="m-user-name">{{ username }}</span>
        <span class="m-user-avatar"><MIcon name="user" :size="20" /></span>
      </button>
    </header>

    <!-- 子页面顶栏（带返回按钮） -->
    <header v-else class="m-topbar m-topbar-sub">
      <button class="m-back-btn" type="button" @click="backToMain">
        <MIcon name="chevronLeft" :size="22" />
        <span>返回</span>
      </button>
      <div class="m-sub-title">{{ subPageTitle }}</div>
      <button class="m-desktop-btn" type="button" aria-label="切换到桌面版" @click="goDesktop">
        <MIcon name="desktop" :size="20" />
      </button>
    </header>

    <main ref="contentRef" class="m-content">
      <!-- 子页面视图 -->
      <MobileProducts
        v-if="subPage === 'products'"
        @navigate="onSubNavigate"
        @force-desktop="goDesktop"
        @back="backToMain"
      />
      <MobileAccounts
        v-else-if="subPage === 'accounts'"
        @navigate="onSubNavigate"
        @force-desktop="goDesktop"
        @back="backToMain"
      />
      <MobileData
        v-else-if="subPage === 'data'"
        @navigate="onSubNavigate"
        @force-desktop="goDesktop"
        @back="backToMain"
      />

      <!-- 主 Tab 视图 -->
      <template v-else>
        <MobileHome
          v-if="activeTab === 'home'"
          @navigate="onNavigate"
          @logout="emit('logout')"
          @force-desktop="goDesktop"
          @tab-change="switchTab"
        />
        <MobileMessages
          v-else-if="activeTab === 'message'"
          @navigate="onNavigate"
          @force-desktop="goDesktop"
        />
        <MobileAutomation
          v-else-if="activeTab === 'automation'"
          @navigate="onNavigate"
          @force-desktop="goDesktop"
        />
        <MobileProfile
          v-else-if="activeTab === 'profile'"
          :user="userInfo"
          @navigate="onNavigate"
          @logout="emit('logout')"
          @force-desktop="goDesktop"
          @tab-change="switchTab"
        />
      </template>
    </main>

    <nav v-if="!subPage" class="m-tabbar" aria-label="移动版导航">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="m-tab"
        :aria-current="activeTab === tab.key ? 'page' : undefined"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        <MIcon :name="tab.icon" :size="24" />
        <span>{{ tab.label }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import MIcon from '../mobile/MIcon.vue'
import MobileHome from '../mobile/MobileHome.vue'
import MobileMessages from '../mobile/MobileMessages.vue'
import MobileAutomation from '../mobile/MobileAutomation.vue'
import MobileProfile from '../mobile/MobileProfile.vue'
import MobileProducts from '../mobile/MobileProducts.vue'
import MobileAccounts from '../mobile/MobileAccounts.vue'
import MobileData from '../mobile/MobileData.vue'
import { getCachedUsername } from '../utils/auth.js'
import { currentUser } from '../api/system.js'

const emit = defineEmits(['navigate', 'logout', 'force-desktop'])

const tabs = [
  { key: 'home', label: '首页', icon: 'home' },
  { key: 'message', label: '消息', icon: 'message' },
  { key: 'automation', label: '自动化', icon: 'bot' },
  { key: 'profile', label: '我的', icon: 'user' }
]

// 移动端支持的子页面：除了这3个外，其他 navigate 都跳转到 PC 端
const mobileSubPages = {
  products: '商品管理',
  accounts: '账号管理',
  data: '数据看板'
}

const activeTab = ref('home')
const subPage = ref(null)
const contentRef = ref(null)
const username = ref(getCachedUsername() || '未登录用户')
const userInfo = ref({ username: username.value })

const subPageTitle = computed(() => mobileSubPages[subPage.value] || '')

async function loadUser() {
  try {
    const res = await currentUser()
    if (res?.data) {
      userInfo.value = { ...userInfo.value, ...res.data }
      username.value = res.data.username || username.value
    }
  } catch { /* Cached username remains available while the profile API is unavailable. */ }
}

function switchTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  nextTick(() => {
    if (contentRef.value) contentRef.value.scrollTop = 0
  })
}

function goDesktop() {
  emit('force-desktop')
}

// 处理 navigate 事件：若是移动端支持的子页面则切换到子页面视图，否则跳到桌面版
function onNavigate(pageKey) {
  if (mobileSubPages[pageKey]) {
    subPage.value = pageKey
    nextTick(() => {
      if (contentRef.value) contentRef.value.scrollTop = 0
    })
  } else {
    goPcPage(pageKey)
  }
}

// 子页面内部再次 navigate（仍优先尝试子页面，否则去桌面版）
function onSubNavigate(pageKey) {
  if (mobileSubPages[pageKey] && pageKey !== subPage.value) {
    subPage.value = pageKey
    nextTick(() => {
      if (contentRef.value) contentRef.value.scrollTop = 0
    })
  } else {
    goPcPage(pageKey)
  }
}

function backToMain() {
  subPage.value = null
  nextTick(() => {
    if (contentRef.value) contentRef.value.scrollTop = 0
  })
}

function goPcPage(pageKey) {
  emit('force-desktop')
  setTimeout(() => {
    emit('navigate', pageKey)
  }, 100)
}

onMounted(() => {
  loadUser()
})
</script>

<style scoped>
.mobile-shell {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--bg);
}

.m-topbar {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: calc(6px + env(safe-area-inset-top)) max(12px, env(safe-area-inset-right)) 6px max(12px, env(safe-area-inset-left));
  background: var(--card);
  border-bottom: 1px solid var(--line);
}

.m-brand,
.m-user,
.m-back-btn,
.m-desktop-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 44px;
  padding: 0 6px;
  background: transparent;
  border: 0;
  border-radius: 8px;
  color: var(--text);
}

.m-brand:active,
.m-user:active,
.m-back-btn:active,
.m-desktop-btn:active {
  background: var(--bg);
}

.m-brand {
  flex-shrink: 0;
  font-size: 16px;
  font-weight: 700;
  padding-left: 0;
}

.m-brand img {
  width: 34px;
  height: 34px;
}

.m-user {
  min-width: 0;
}

.m-user-name,
.m-sub-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}

.m-user-name {
  max-width: 14ch;
}

.m-user-avatar {
  display: grid;
  place-items: center;
  flex: 0 0 32px;
  height: 32px;
  border-radius: 50%;
  background: #eaf1fd;
  color: var(--primary);
}

.m-sub-title {
  flex: 1;
  text-align: center;
  font-size: 16px;
}

.m-desktop-btn {
  min-width: 44px;
  color: var(--muted);
}

.m-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  padding: 0 env(safe-area-inset-right) 0 env(safe-area-inset-left);
}

.m-content:last-child {
  padding-bottom: env(safe-area-inset-bottom);
}

.m-tabbar {
  display: flex;
  flex: 0 0 auto;
  background: var(--card);
  border-top: 1px solid var(--line);
  padding: 4px env(safe-area-inset-right) max(4px, env(safe-area-inset-bottom)) env(safe-area-inset-left);
}

.m-tab {
  flex: 1;
  min-height: 44px;
  padding: 4px 0;
  background: transparent;
  border: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  color: var(--muted);
  font-size: 12px;
}
.m-tab.active {
  color: var(--primary);
  font-weight: 700;
}
</style>
