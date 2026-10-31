<template>
  <div class="settings-layout">
    <ConfigNav :active="active" @navigate="$emit('navigate', $event)" @prefetch="onPrefetch" />
    <div class="settings-main">
      <Transition name="settings-fade" mode="out-in">
        <component :is="current" :key="active" :active="active" @navigate="$emit('navigate', $event)" />
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { asyncPage } from '../components/asyncPage.js'
import ConfigNav from '../components/ConfigNav.vue'

const props = defineProps({ active: String })
defineEmits(['navigate'])

const map = {
  'settings-system': asyncPage(() => import('./admin/SystemSettingsPage.vue')),
  'settings-ai-cs': asyncPage(() => import('./settings/AiCsSettings.vue')),
  'settings-model': asyncPage(() => import('./admin/ModelSettingsPage.vue')),
  'settings-embedding': asyncPage(() => import('./admin/EmbeddingSettingsPage.vue')),
  'settings-rag': asyncPage(() => import('./admin/RagSettingsPage.vue')),
  'settings-product': asyncPage(() => import('./settings/ProductOpSettings.vue')),
  'settings-about': asyncPage(() => import('./settings/AboutSettings.vue')),
  'settings-notify': asyncPage(() => import('./settings/NotifySettings.vue'))
}

const current = computed(() => map[props.active] || map['settings-system'])

function onPrefetch(key) {
  if (map[key]?.prefetch) {
    map[key].prefetch().catch(() => {})
  }
}

onMounted(() => {
  const idle = window.requestIdleCallback || (cb => setTimeout(cb, 300))
  idle(() => {
    Object.values(map).forEach(page => {
      if (page?.prefetch) page.prefetch().catch(() => {})
    })
  })
})
</script>

<style scoped>
.settings-layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.settings-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 480px;
}

.settings-fade-enter-active,
.settings-fade-leave-active {
  transition: opacity 0.16s cubic-bezier(0.2, 0, 0, 1), transform 0.16s cubic-bezier(0.2, 0, 0, 1);
  will-change: opacity, transform;
}

.settings-fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

.settings-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (max-width: 1260px) {
  .settings-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 900px) {
  .settings-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }

  .settings-main {
    gap: 12px;
    min-width: 0;
  }
}
</style>
