<template>
  <aside class="sidebar" :class="{ open }">
    <button class="sidebar-close" type="button" aria-label="关闭菜单" @click="$emit('close')">
      <svg viewBox="0 0 24 24" class="ui-icon"><path d="M6 6l12 12M18 6 6 18" /></svg>
    </button>
    <button type="button" class="brand brand-image" aria-label="返回首页" @click="$emit('navigate','dashboard')" @mouseenter="$emit('prefetch', 'dashboard')" @focus="$emit('prefetch', 'dashboard')">
      <img src="/xya/brand/app-icon.png" alt="" class="brand-logo brand-icon" />
      <span class="sidebar-brand-name">闲鱼助手<small>Xianyu Pilot</small></span>
    </button>
    <nav class="nav-scroll">
      <div v-for="group in groups" :key="group.title" class="nav-group">
        <div class="nav-title">{{ group.title }}</div>
        <button
          v-for="item in group.items"
          :key="item.key"
          :class="['nav-item', { active: isActive(item.key), child: item.child }]"
          @click="$emit('navigate', item.key)"
          @mouseenter="$emit('prefetch', item.key)"
          @focus="$emit('prefetch', item.key)"
        >
          <span class="nav-icon"><Icon :name="item.icon" /></span>
          <span>{{ item.label }}</span>
          <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
        </button>
      </div>
    </nav>
    <button type="button" class="side-user" aria-label="打开个人中心" @click="$emit('navigate','profile')" @mouseenter="$emit('prefetch', 'profile')" @focus="$emit('prefetch', 'profile')">
      <div class="avatar avatar-img"></div>
      <div class="side-user-main">
        <strong>{{ displayName }}</strong>
        <span>管理员</span>
      </div>
      <span class="online-dot"></span><span class="online-text">在线</span>
    </button>
    <button class="sidebar-logout" type="button" @click="$emit('logout')">退出登录</button>
    <div class="version">© {{ copyrightYear }} XianYuAssistant<br />v{{ APP_VERSION }}</div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { navGroups } from '../data/nav.js'
import Icon from './Icon.vue'
import { APP_VERSION, getCopyrightYear } from '../utils/appMeta.js'
defineEmits(['navigate', 'close', 'logout', 'prefetch'])
const props = defineProps({ active: { type: String, required: true }, user: { type: Object, default: () => ({}) }, open: { type: Boolean, default: false } })
const groups = navGroups
const displayName = computed(() => props.user?.username || props.user?.displayName || props.user?.name || '管理员')
const copyrightYear = getCopyrightYear()
function isActive(key) {
  if (props.active.startsWith('settings-') && props.active !== 'settings-notify' && key === 'settings-system') return true
  return props.active === key
}
</script>

<style scoped>
.brand.brand-image {
  gap: 12px;
  text-align: left;
}
.sidebar-brand-name {
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: var(--text);
  font-size: 21px;
  font-weight: 800;
  white-space: nowrap;
}
.sidebar-brand-name small {
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: .5px;
}
</style>
