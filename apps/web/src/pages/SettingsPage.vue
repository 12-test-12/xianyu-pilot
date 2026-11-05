<template>
  <div class="settings-layout">
    <ConfigNav :active="active" @navigate="$emit('navigate', $event)" @prefetch="$emit('prefetch', $event)" />
    <div class="settings-main">
      <div v-if="renderFailed" class="page-load-error" role="alert">
        <span>当前设置页未能显示，可以重试或切换到其他设置。</span>
        <button type="button" @click="renderFailed = false">重试</button>
      </div>
      <component v-else :is="current" :key="active" :active="active" @navigate="$emit('navigate', $event)" />
    </div>
  </div>
</template>

<script setup>
import { computed, onErrorCaptured, ref, watch } from 'vue'
import { settingsPages } from '../data/settingsPages.js'
import ConfigNav from '../components/ConfigNav.vue'

const props = defineProps({ active: String })
defineEmits(['navigate', 'prefetch'])

const current = computed(() => settingsPages[props.active] || settingsPages['settings-system'])
const renderFailed = ref(false)
watch(() => props.active, () => { renderFailed.value = false })
onErrorCaptured(() => {
  renderFailed.value = true
  return false
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
