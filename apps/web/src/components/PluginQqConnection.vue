<template>
  <section class="card-panel qq-panel" aria-labelledby="plugin-qq-heading">
    <h2 id="plugin-qq-heading">球球助力 · QQ 账号与机器人</h2>
    <p v-if="error" role="alert" class="qq-error">{{ error }}</p>
    <p v-if="status" role="status">{{ status }}</p>
    <AppButton v-if="!loaded && error" @click="load">重新读取</AppButton>
    <template v-if="loaded">
      <fieldset v-if="profiles.length" class="qq-profiles" :disabled="busy || locked">
        <legend>勾选本次使用的配置</legend>
        <ul>
          <li v-for="profile in profiles" :key="profile.id">
            <label class="profile-choice">
              <input v-model="selection" type="checkbox" :value="profile.id">
              <span>{{ profile.qqAccount || '原有配置，待填写发送账号' }} → {{ profile.robotName || '机器人' }}（{{ profile.robotQq }}）{{ profile.backup ? ' · 备用' : ' · 常用' }}</span>
            </label>
            <div class="qq-actions">
              <AppButton v-if="profile.qqAccount" :aria-label="`绑定账号 ${profile.qqAccount} 的 QQ 主窗口`" @click="bind(profile.qqAccount)">
                {{ boundAccounts.includes(profile.qqAccount) ? '重新绑定窗口' : '绑定窗口' }}
              </AppButton>
              <AppButton v-if="boundAccounts.includes(profile.qqAccount)" :aria-label="`解除账号 ${profile.qqAccount} 的窗口绑定`" @click="unbind(profile.qqAccount)">解绑窗口</AppButton>
              <AppButton :aria-label="`编辑机器人 ${profile.robotQq} 的配置`" @click="edit(profile)">编辑</AppButton>
              <AppButton :aria-label="`移除机器人 ${profile.robotQq} 的配置`" @click="remove(profile)">移除</AppButton>
            </div>
          </li>
        </ul>
      </fieldset>

      <form v-if="changing || !profiles.length" class="qq-form" aria-describedby="qq-profile-help" @submit.prevent="save">
        <p id="qq-profile-help">每组配置填写一个发送 QQ 和一个机器人好友。相同机器人可以给不同账号分别保存。</p>
        <label>发送 QQ 号
          <input ref="accountField" v-model.trim="form.qqAccount" class="input" inputmode="numeric" pattern="[1-9][0-9]{4,19}" maxlength="20" required :disabled="busy || locked">
        </label>
        <label>机器人好友 QQ 号
          <input v-model.trim="form.robotQq" class="input" inputmode="numeric" pattern="[1-9][0-9]{4,19}" maxlength="20" required :disabled="busy || locked">
        </label>
        <label>QQ 备注或昵称（选填）
          <input v-model.trim="form.robotName" class="input" maxlength="80" :disabled="busy || locked">
        </label>
        <label class="profile-choice"><input v-model="form.backup" type="checkbox" :disabled="busy || locked">备用机器人</label>
        <AppButton type="primary" native-type="submit" :disabled="busy || locked">保存配置</AppButton>
        <AppButton v-if="profiles.length" :disabled="busy || locked" @click="finishEditing">取消</AppButton>
      </form>
      <AppButton v-else ref="addButton" class="add-button" :disabled="busy || locked" @click="edit()">新增 QQ 配置</AppButton>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import AppButton from './AppButton.vue'
import { confirmAction } from '../utils/confirmAction.js'
import request from '../utils/request.js'

const props = defineProps({
  profiles: { type: Array, required: true },
  selectedIds: { type: Array, required: true },
  boundAccounts: { type: Array, required: true },
  locked: Boolean,
})
const emit = defineEmits(['update:profiles', 'update:selectedIds', 'update:boundAccounts'])
const profilesPath = '/desktop/plugins/qq/profiles'
const windowsPath = '/desktop/plugins/qq/windows'
const config = { uiMode: 'silent', suppressGlobalError: true }
const selection = computed({
  get: () => props.selectedIds,
  set: ids => emit('update:selectedIds', ids),
})
const emptyForm = () => ({ qqAccount: '', robotQq: '', robotName: '', backup: false })
const form = ref(emptyForm())
const editingId = ref(null)
const changing = ref(false)
const accountField = ref(null)
const addButton = ref(null)
const loaded = ref(false)
const busy = ref(false)
const status = ref('')
const error = ref('')

async function run(action) {
  if (busy.value || props.locked) return
  busy.value = true
  error.value = ''
  status.value = ''
  try {
    await action()
  } catch (err) {
    status.value = ''
    error.value = err?.message || 'QQ 配置操作失败，请重试。'
  } finally {
    busy.value = false
  }
}

function load() {
  return run(async () => {
    const [profiles, windows] = await Promise.all([request.get(profilesPath, config), request.get(windowsPath, config)])
    emit('update:profiles', profiles.data)
    emit('update:boundAccounts', windows.data)
    if (profiles.data.length) selection.value = [profiles.data[0].id]
    loaded.value = true
  })
}

async function edit(profile) {
  editingId.value = profile?.id ?? null
  form.value = profile ? {
    qqAccount: profile.qqAccount, robotQq: profile.robotQq, robotName: profile.robotName, backup: profile.backup,
  } : emptyForm()
  changing.value = true
  await nextTick()
  accountField.value?.focus()
}

async function finishEditing() {
  changing.value = false
  form.value = emptyForm()
  await nextTick()
  addButton.value?.$el?.focus()
}

function save() {
  return run(async () => {
    const { data } = editingId.value === null
      ? await request.post(profilesPath, form.value, config)
      : await request.put(`${profilesPath}/${editingId.value}`, form.value, config)
    emit('update:profiles', [...props.profiles.filter(profile => profile.id !== data.id), data])
    if (!selection.value.length) selection.value = [data.id]
    status.value = 'QQ 配置已保存。'
    await finishEditing()
  })
}

function remove(profile) {
  return run(async () => {
    if (!await confirmAction({ title: '移除这组 QQ 配置？', description: `${profile.qqAccount || '原有配置'} → ${profile.robotQq}`, confirmText: '移除' })) return
    await request.delete(`${profilesPath}/${profile.id}`, config)
    emit('update:profiles', props.profiles.filter(item => item.id !== profile.id))
    selection.value = selection.value.filter(id => id !== profile.id)
    status.value = 'QQ 配置已移除。'
  })
}

function bind(account) {
  return run(async () => {
    if (!await confirmAction({
      title: `绑定发送 QQ ${account}`,
      description: `点击开始后，在任务栏切到 QQ ${account} 的已登录主窗口。请确认切到的是这个账号。`,
      confirmText: '开始绑定',
    })) return
    status.value = `请在 16 秒内切到 QQ ${account} 的主窗口。`
    const { data } = await request.put(`${windowsPath}/${account}`, {}, config)
    emit('update:boundAccounts', data)
    status.value = `发送 QQ ${account} 的窗口已绑定。`
  })
}

function unbind(account) {
  return run(async () => {
    const { data } = await request.delete(`${windowsPath}/${account}`, config)
    emit('update:boundAccounts', data)
    status.value = `已解除 QQ ${account} 的窗口绑定。`
  })
}

onMounted(load)
</script>

<style scoped>
.qq-panel { padding: 20px; }
h2 { margin: 0; font-size: 18px; }
p { margin: 6px 0 0; color: var(--muted); }
.qq-error { color: #b42318; }
.qq-profiles { border: 0; padding: 0; margin: 12px 0 0; min-width: 0; }
.qq-profiles ul { margin: 6px 0 0; padding: 0; list-style: none; }
.qq-profiles li { padding: 8px 0; border-bottom: 1px solid var(--line); }
.qq-actions, .qq-form { display: flex; flex-wrap: wrap; gap: 10px; }
.qq-actions { margin-top: 6px; }
.qq-form { margin-top: 12px; align-items: end; }
.qq-form > p { flex-basis: 100%; margin: 0; }
.qq-form > label { display: grid; gap: 6px; flex: 1 1 160px; min-width: 0; }
.profile-choice, .qq-form > .profile-choice { display: flex; align-items: center; gap: 8px; overflow-wrap: anywhere; }
.add-button { margin-top: 12px; }
</style>
