<template>
  <section class="card-panel qq-panel" aria-labelledby="plugin-qq-heading" :aria-busy="busy">
    <h2 id="plugin-qq-heading">球球助力 · QQ 连接</h2>
    <p id="plugin-qq-help">在本机 OneBot 11 客户端登录你的 QQ，启用 HTTP 服务，再填写机器人好友的 QQ 号。</p>
    <p v-if="error" role="alert" class="qq-error">{{ error }}</p>
    <p v-if="connection" role="status">
      已核对好友 {{ connection.robotName }}（{{ connection.robotQq }}），最近验证于 {{ new Date(connection.checkedAt).toLocaleString('zh-CN') }}。
    </p>
    <form aria-describedby="plugin-qq-help" @submit.prevent="saveConnection">
      <fieldset :disabled="busy">
        <label>OneBot HTTP 地址
          <input v-model.trim="form.endpoint" class="input" placeholder="http://127.0.0.1:3000" maxlength="100" required>
        </label>
        <label>登录的 QQ 号
          <input v-model.trim="form.qqAccount" class="input" inputmode="numeric" pattern="[1-9][0-9]{0,19}" maxlength="20" required>
        </label>
        <label>机器人好友 QQ 号
          <input v-model.trim="form.robotQq" class="input" inputmode="numeric" pattern="[1-9][0-9]{0,19}" maxlength="20" required>
        </label>
        <label>Access Token
          <input v-model="form.accessToken" class="input" type="password" autocomplete="new-password" maxlength="512" :required="!canReuseToken" :placeholder="canReuseToken ? '留空沿用已保存的令牌' : ''">
        </label>
      </fieldset>
      <div class="qq-actions">
        <AppButton type="primary" native-type="submit" :disabled="busy">{{ busy ? '处理中…' : '验证并保存' }}</AppButton>
        <AppButton v-if="connection" :disabled="busy" @click="disconnect">移除 QQ 绑定</AppButton>
      </div>
    </form>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import AppButton from './AppButton.vue'
import { confirmAction } from '../utils/confirmAction.js'
import request from '../utils/request.js'

const endpoint = '/desktop/plugins/qq/connection'
const config = { uiMode: 'silent', suppressGlobalError: true }
const form = reactive({ endpoint: '', qqAccount: '', robotQq: '', accessToken: '' })
const connection = ref(null)
const error = ref('')
const busy = ref(false)
const canReuseToken = computed(() => !!connection.value &&
  form.endpoint.replace(/\/$/, '') === connection.value.endpoint && form.qqAccount === connection.value.qqAccount)

function applyConnection(data) {
  connection.value = data || null
  if (data) {
    form.endpoint = data.endpoint
    form.qqAccount = data.qqAccount
    form.robotQq = data.robotQq
  }
  form.accessToken = ''
}

async function run(action) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await action()
  } catch (err) {
    error.value = err?.message || 'QQ 连接操作失败，请重试。'
  } finally {
    busy.value = false
  }
}

function saveConnection() {
  return run(async () => applyConnection((await request.put(endpoint, { ...form }, config)).data))
}

async function disconnect() {
  if (!await confirmAction({
    title: '确认移除 QQ 绑定？',
    description: '移除后将清除已核对的机器人好友与本地保存的令牌。',
    dangerous: true,
  })) return
  return run(async () => {
    await request.delete(endpoint, config)
    applyConnection(null)
  })
}

onMounted(() => run(async () => applyConnection((await request.get(endpoint, config)).data)))
</script>

<style scoped>
.qq-panel { padding: 20px; }
h2 { margin: 0; font-size: 18px; }
p { margin: 6px 0 0; color: var(--muted); }
.qq-error { color: #b42318; }
fieldset { border: 0; padding: 0; margin: 16px 0; min-width: 0; display: flex; flex-wrap: wrap; gap: 12px; }
label { display: grid; gap: 6px; flex: 1 1 180px; min-width: 0; max-width: 280px; }
.qq-actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
