<template>
  <div class="settings-layout">
    <ConfigNav :active="active" @navigate="$emit('navigate', $event)" @prefetch="$emit('prefetch', $event)" />
    <div class="settings-main">
      <component :is="current" :key="active" :active="active" @navigate="$emit('navigate', $event)" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { settingsPages } from '../data/settingsPages.js'
import ConfigNav from '../components/ConfigNav.vue'

const props = defineProps({ active: String })
defineEmits(['navigate', 'prefetch'])

const current = computed(() => settingsPages[props.active] || settingsPages['settings-system'])
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
