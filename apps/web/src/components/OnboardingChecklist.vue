<template>
  <CardPanel v-if="visible" title="开店设置" class="onboarding-card">
    <template #action>
      <span class="onboarding-count">已完成 {{ completedCount }}/{{ steps.length }}</span>
    </template>
    <div class="onboarding-steps">
      <button
        v-for="step in steps"
        :key="step.key"
        type="button"
        :class="['onboarding-step', { done: isDone(step.key) }]"
        @click="go(step)"
      >
        <span class="step-check">{{ isDone(step.key) ? '✓' : step.order }}</span>
        <span><b>{{ step.title }}</b><em>{{ step.desc }}</em></span>
        <strong>{{ step.cta }} ›</strong>
      </button>
    </div>
    <div class="onboarding-actions">
      <button type="button" class="link danger" @click="onDismiss">不再提示</button>
    </div>
  </CardPanel>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import CardPanel from './CardPanel.vue'
import { getRuntimeStatus } from '../api/system.js'
import {
  isOnboardingDismissed,
  dismissOnboarding,
  getDoneKeys,
  markStepDone,
} from '../utils/onboardingState.js'

const emit = defineEmits(['navigate'])
const visible = ref(false)
const done = ref(getDoneKeys())

const steps = [
  { order: 1, key: 'account', title: '添加闲鱼账号', desc: '扫码或手动 Cookie 添加一个可用账号。', cta: '去添加', to: 'accounts' },
  { order: 2, key: 'sync', title: '同步线上商品', desc: '进入商品管理，同步账号下的在售商品。', cta: '去同步', to: 'products' },
  { order: 3, key: 'automation', title: '开启自动化', desc: '创建一条自动回复或自动发货规则并先用预览验证。', cta: '去配置', to: 'auto-reply' }
]

const isDone = key => done.value.includes(key)
const completedCount = computed(() => steps.filter(s => isDone(s.key)).length)

function go(step) {
  markStepDone(step.key)
  done.value = getDoneKeys()
  emit('navigate', step.to)
}

function onDismiss() {
  dismissOnboarding()
  visible.value = false
}

async function checkCompletionFromServer() {
  try {
    const res = await getRuntimeStatus()
    const data = res?.data || {}
    // 模型已配置视为"配置自动化"完成
    if (data.generalModelConfigured) markStepDone('automation')
    // 数据库连通视为已通过基础环境检查
    if (data.dbConnected) markStepDone('seen-guide')
    done.value = getDoneKeys()
  } catch {
    // 静默失败，不影响用户首次使用
  }
}

onMounted(() => {
  if (isOnboardingDismissed()) {
    visible.value = false
    return
  }
  // 完成所有步骤后不再显示
  if (completedCount.value >= steps.length) {
    visible.value = false
    return
  }
  visible.value = true
  checkCompletionFromServer()
})
</script>

<style scoped>
.onboarding-card { margin-bottom: 16px; }

.onboarding-count {
  color: var(--muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.onboarding-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 202px), 1fr));
  gap: 8px;
}

.onboarding-step {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 5px 10px;
  text-align: left;
  border: 1px solid var(--line);
  background: var(--card);
  border-radius: 8px;
  padding: 10px;
}

.onboarding-step:hover { background: var(--bg); }
.step-check {
  display: grid;
  grid-row: span 2;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #eaf1fd;
  color: var(--primary);
  font-weight: 700;
}
.done .step-check { background: #dcfae6; color: #067647; }
.onboarding-step b { display: block; color: var(--text); }
.onboarding-step em {
  display: block;
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
  line-height: 1.5;
  text-wrap: pretty;
}
.onboarding-step strong { grid-column: 2; color: var(--primary); font-size: 12px; }

.onboarding-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
.onboarding-actions .link {
  min-height: 36px;
  padding: 4px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
}
.onboarding-actions .link:hover { background: var(--bg); color: var(--text); }
.onboarding-actions .link.danger:hover { color: #b42318; }
</style>
