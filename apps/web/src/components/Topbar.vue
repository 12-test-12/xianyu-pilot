<template>
  <div class="topbar">
    <div class="top-user-wrap">
      <button class="top-user" type="button" @click="$emit('open-profile-center')">
        <div class="avatar small avatar-img"></div>
        <span>{{ displayName }}</span>
        <em>{{ sseLabel }}</em>
        <b v-if="showLogout" aria-hidden="true">⌄</b>
      </button>

      <div v-if="showLogout" class="top-user-menu logout-only">
        <button type="button" @click="$emit('logout')">退出登录</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  user: { type: Object, default: () => ({}) },
  sseStatus: { type: String, default: 'disconnected' },
  showLogout: { type: Boolean, default: true },
  unreadCount: { type: [String, Number], default: 0 }
})

defineEmits(['logout', 'open-profile-center'])

const displayName = computed(() => props.user?.username || props.user?.displayName || props.user?.name || '管理员')
const sseLabel = computed(() => ({
  connected: '在线',
  connecting: '连接中',
  reconnecting: '重连中',
  disconnected: '离线',
  failed: '连接失败',
}[props.sseStatus] || '状态未知'))
</script>

<style scoped>
.top-user-wrap {
  position: relative;
  min-width: 0;
}

.top-user {
  max-width: 100%;
  min-height: 36px;
  padding: 4px 10px 4px 5px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--card);
  color: var(--text);
}

.top-user > span {
  max-width: 18ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-user > em {
  flex-shrink: 0;
}

.top-user-menu {
  position: absolute;
  right: 0;
  top: 100%;
  background: #fff;
  border: 1px solid #e8eef8;
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 8px;
  z-index: 20;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-6px);
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.top-user-wrap:hover .top-user-menu,
.top-user-wrap:focus-within .top-user-menu {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

.top-user-menu button {
  white-space: nowrap;
  border: 0;
  background: transparent;
  padding: 10px 18px;
  border-radius: 10px;
  cursor: pointer;
  color: #ef4444;
  font-weight: 800;
}

.top-user-menu button:hover {
  background: #fff5f5;
}
</style>
