<template>
  <header class="page-head">
    <div v-if="title || subtitle" class="page-head-copy">
      <h1 v-if="title">{{ title }}</h1>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.default" class="page-head-actions">
      <slot />
    </div>
  </header>
</template>
<script setup>
defineProps({ title: String, subtitle: String })
</script>
<style scoped>
.page-head-copy {
  min-width: 0;
  overflow-wrap: anywhere;
}

.page-head-actions {
  max-width: 100%;
  margin-left: auto;
}

.page-head-actions:empty {
  display: none;
}
</style>
