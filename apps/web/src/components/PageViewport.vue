<template>
  <div class="page-viewport">
    <div v-if="failed" class="page-load-error" role="alert">
      <span>当前页面显示异常，可以重新加载此页或切换页面。</span>
      <button type="button" @click="failed = false">重试当前页</button>
    </div>
    <slot v-else />
  </div>
</template>

<script setup>
import { onErrorCaptured, ref, watch } from 'vue'
import { recordClientError } from '../utils/errorReporter.js'

const props = defineProps({ route: String })
const failed = ref(false)
watch(() => props.route, () => { failed.value = false })

onErrorCaptured((error, _component, phase) => {
  if (phase !== 'setup function' && phase !== 'render function' && !/#runtime-[01]$/.test(phase)) return
  failed.value = true
  recordClientError(error, { source: 'page_render', context: { page: props.route } })
  return false
})
</script>
