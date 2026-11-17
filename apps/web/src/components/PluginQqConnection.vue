<template>
  <section class="card-panel qq-panel" aria-labelledby="plugin-qq-heading" :aria-busy="busy">
    <h2 id="plugin-qq-heading">球球助力 · QQ 机器人</h2>
    <p v-if="error" role="alert" class="qq-error">{{ error }}</p>
    <p v-if="!loaded && error"><AppButton @click="load">重新读取</AppButton></p>
    <p v-if="target" role="status">
      已保存 {{ target.robotName || '机器人' }}（{{ target.robotQq }}）。下次打开闲鱼助手可继续使用。
    </p>
    <template v-if="loaded">
      <form v-if="editing || !target" class="qq-form" aria-describedby="qq-target-help" @submit.prevent="save">
        <p id="qq-target-help">打开 QQ 机器人的好友资料，填一次 QQ 号。备注或昵称按 QQ 窗口里显示的填写，方便核对同名好友。</p>
        <label>机器人好友 QQ 号
          <input ref="numberField" v-model.trim="robotQq" class="input" inputmode="numeric" pattern="[1-9][0-9]{4,19}" maxlength="20" required :disabled="busy">
        </label>
        <label>QQ 备注或昵称（选填）
          <input v-model.trim="robotName" class="input" maxlength="80" :disabled="busy">
        </label>
        <AppButton type="primary" native-type="submit" :disabled="busy">{{ busy ? '保存中…' : '保存机器人' }}</AppButton>
        <AppButton v-if="target" :disabled="busy" @click="finishEditing">取消</AppButton>
      </form>
      <AppButton v-else ref="changeButton" class="change-button" @click="edit">更换机器人</AppButton>
    </template>
  </section>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import AppButton from './AppButton.vue'
import request from '../utils/request.js'

const props = defineProps({ target: { type: Object, default: null } })
const emit = defineEmits(['update:target'])
const path = '/desktop/plugins/qq/target'
const config = { uiMode: 'silent', suppressGlobalError: true }
const robotQq = ref('')
const robotName = ref('')
const numberField = ref(null)
const changeButton = ref(null)
const editing = ref(false)
const loaded = ref(false)
const busy = ref(false)
const error = ref('')

async function edit() {
  robotQq.value = props.target.robotQq
  robotName.value = props.target.robotName
  editing.value = true
  await nextTick()
  numberField.value?.focus()
}

async function finishEditing() {
  editing.value = false
  await nextTick()
  changeButton.value?.$el?.focus()
}

async function load() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    emit('update:target', (await request.get(path, config)).data)
    loaded.value = true
  } catch (err) {
    error.value = err?.message || '无法读取保存的机器人。'
  } finally {
    busy.value = false
  }
}

async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { data } = await request.put(path, { robotQq: robotQq.value, robotName: robotName.value }, config)
    emit('update:target', data)
    await finishEditing()
  } catch (err) {
    error.value = err?.message || '无法保存机器人，请重试。'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.qq-panel { padding: 20px; }
h2 { margin: 0; font-size: 18px; }
p { margin: 6px 0 0; color: var(--muted); }
.qq-error { color: #b42318; }
.qq-form { margin-top: 12px; display: flex; flex-wrap: wrap; align-items: end; gap: 10px; }
.qq-form > p { flex-basis: 100%; margin: 0; }
label { display: grid; gap: 6px; flex: 1 1 190px; min-width: 0; max-width: 280px; }
.change-button { margin-top: 12px; }
</style>
