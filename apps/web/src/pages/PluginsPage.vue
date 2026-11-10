<template>
  <div class="plugin-page" :aria-busy="busy">
    <p v-if="error" class="global-notice error" role="alert">{{ error }}</p>
    <p v-if="notice" class="global-notice success" role="status">{{ notice }}</p>
    <section class="card-panel plugin-panel" aria-labelledby="available-plugins">
      <header class="plugin-heading">
        <div>
          <h2 id="available-plugins">可用插件</h2>
          <p>插件由项目维护者独立发布，可按需安装到程序旁的 plugins 文件夹。</p>
        </div>
        <div class="plugin-actions">
          <AppButton type="primary" :disabled="busy || !data || !!data.publisherIssue" @click="openPicker($event, zipPicker)">安装 ZIP</AppButton>
          <AppButton :disabled="busy || !data || !!data.publisherIssue" @click="openPicker($event, folderPicker)">安装文件夹</AppButton>
          <AppButton :disabled="busy" @click="run(refresh)">刷新</AppButton>
        </div>
      </header>
      <input ref="zipPicker" type="file" accept=".zip,application/zip" aria-label="选择 ZIP 插件包" hidden @change="selectPackage($event, false)">
      <input ref="folderPicker" type="file" webkitdirectory aria-label="选择插件文件夹" hidden @change="selectPackage($event, true)">
      <p v-if="data?.publisherIssue" class="global-notice warn" role="status">{{ data.publisherIssue }}，配置后点「刷新」。</p>
      <ul v-if="data" class="plugin-list">
        <li v-for="item in data.available" :key="item.id" class="plugin-row">
          <div>
            <h3>{{ item.name }}</h3>
            <p>{{ item.description }}</p>
            <p>{{ item.requires }} · {{ item.source }}</p>
          </div>
          <Badge>{{ data.installed.some(plugin => plugin.id === item.id) ? '已安装' : '可安装' }}</Badge>
        </li>
      </ul>
      <p v-else-if="busy" role="status">正在读取插件目录…</p>
    </section>
    <section class="card-panel plugin-panel" aria-labelledby="installed-plugins">
      <header class="plugin-heading">
        <div>
          <h2 id="installed-plugins">已安装</h2>
          <p>手动复制到插件目录的版本，点「刷新」后即可核对并启用。</p>
        </div>
      </header>
      <p v-if="data && !data.installed.length" class="plugin-empty">暂无通过校验的插件。</p>
      <ul v-else-if="data" class="plugin-list">
        <li v-for="item in data.installed" :key="item.id + '/' + item.version" class="plugin-row">
          <div>
            <h3>{{ item.name }} <small>v{{ item.version }}</small></h3>
            <p>{{ item.description }}</p>
          </div>
          <div class="plugin-actions">
            <Badge :type="item.enabled ? 'green' : 'blue'">{{ item.enabled ? '已启用' : '已停用' }}</Badge>
            <AppButton v-if="item.enabled" :disabled="busy" :aria-label="`预演 ${item.name} ${item.version}`" @click="showPreview(item)">指令预演</AppButton>
            <AppButton :disabled="busy" :aria-label="`${item.enabled ? '停用' : '启用'} ${item.name} ${item.version}`" @click="toggle(item)">{{ item.enabled ? '停用' : '启用' }}</AppButton>
            <AppButton :disabled="busy" :aria-label="`卸载 ${item.name} ${item.version}`" @click="remove(item)">卸载</AppButton>
          </div>
        </li>
      </ul>
      <ul v-if="data?.issues.length" class="plugin-issues">
        <li v-for="issue in data.issues" :key="issue.path">{{ issue.path }} · {{ issue.message }}</li>
      </ul>
    </section>
    <section v-if="selected" class="card-panel plugin-panel" aria-labelledby="plugin-preview">
      <header class="plugin-heading">
        <div>
          <h2 id="plugin-preview" ref="previewHeading" tabindex="-1">{{ selected.name }} · 指令预演</h2>
          <p>在本机查看预计发送的指令。</p>
        </div>
      </header>
      <form class="plugin-form" @submit.prevent="run(preview)">
        <label>参数类型
          <select v-model="parameterType" class="input" @change="steps = []">
            <option v-for="type in selected.parameterTypes" :key="type" :value="type">{{ parameterLabels[type] || type }}</option>
          </select>
        </label>
        <label>样例参数
          <input v-model="value" class="input" maxlength="500" required @input="steps = []">
        </label>
        <AppButton type="primary" native-type="submit" :disabled="busy">运行预演</AppButton>
      </form>
      <div aria-live="polite">
        <ol v-if="steps.length" class="plugin-steps">
          <li v-for="(step, index) in steps" :key="index">
            <strong>{{ step.title }}</strong>
            <p>{{ step.command || '收到可核对的全服排名后生成指令' }}</p>
          </li>
        </ol>
      </div>
    </section>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import AppButton from '../components/AppButton.vue'
import Badge from '../components/Badge.vue'
import { confirmAction } from '../utils/confirmAction.js'
import request from '../utils/request.js'

const endpoint = '/desktop/plugins'
const parameterLabels = { short_link: '短链接', number: '球球号', nickname: '昵称' }
const data = ref(null)
const zipPicker = ref(null)
const folderPicker = ref(null)
const previewHeading = ref(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const selected = ref(null)
const parameterType = ref('')
const value = ref('')
const steps = ref([])
const pathFor = item => `${endpoint}/${item.id}/${item.version}`
let packageButton

async function run(action, trigger = document.activeElement) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await action()
  } catch (err) {
    error.value = err?.message || '插件操作失败，请重试。'
  } finally {
    busy.value = false
    await nextTick()
    if (document.activeElement === document.body && trigger instanceof HTMLButtonElement && trigger.isConnected) {
      trigger.focus()
    }
  }
}

async function refresh() {
  const result = await request.get(endpoint, { uiMode: 'silent' })
  data.value = result.data
  if (selected.value && !data.value.installed.some(item => item.enabled && pathFor(item) === pathFor(selected.value))) {
    selected.value = null
    steps.value = []
  }
}

async function folderPayload(files) {
  if (files.length !== 2 || files.some(file => file.size > 24 * 1024 || file.webkitRelativePath.split('/').length !== 2)) {
    throw new Error('请选择直接包含 manifest.json 和 manifest.sig 的插件文件夹。')
  }
  const contents = await Promise.all(files.map(async file => [
    file.name, btoa(String.fromCharCode(...new Uint8Array(await file.arrayBuffer()))),
  ]))
  return Object.fromEntries(contents)
}

function selectPackage(event, folder) {
  const files = [...event.target.files]
  event.target.value = ''
  if (!files.length) return
  return run(async () => {
    if (!folder && files[0].size > 64 * 1024) throw new Error('插件包不能超过 64 KB。')
    const payload = folder ? await folderPayload(files) : files[0]
    const config = { uiMode: 'silent', headers: { 'Content-Type': folder ? 'application/json' : 'application/zip' } }
    const { data: item } = await request.post(`${endpoint}/package/inspect`, payload, config)
    if (!await confirmAction({
      title: `安装 ${item.name} v${item.version}`,
      description: `${item.description}\n维护者签名已校验 · 支持离线预演`,
      confirmText: '安装插件',
    })) return
    await request.post(`${endpoint}/package`, payload, config)
    await refresh()
    notice.value = `${item.name} v${item.version} 已安装。`
  }, packageButton)
}

function openPicker(event, picker) {
  packageButton = event.currentTarget
  picker.click()
}

function toggle(item) {
  return run(async () => {
    await request.patch(pathFor(item), { enabled: !item.enabled }, { uiMode: 'silent' })
    await refresh()
    notice.value = `${item.name} v${item.version} 已${item.enabled ? '停用' : '启用'}。`
  })
}

function remove(item) {
  return run(async () => {
    if (!await confirmAction({
      title: `卸载 ${item.name} v${item.version}`,
      description: '此操作会移除这个版本的插件文件。',
      confirmText: '卸载',
      dangerous: true,
    })) return
    await request.delete(pathFor(item), { uiMode: 'silent' })
    await refresh()
    notice.value = `${item.name} v${item.version} 已卸载。`
  })
}

async function showPreview(item) {
  selected.value = item
  parameterType.value = item.parameterTypes[0]
  value.value = ''
  steps.value = []
  await nextTick()
  previewHeading.value?.focus()
}

async function preview() {
  steps.value = []
  const result = await request.post(`${pathFor(selected.value)}/preview`, {
    parameterType: parameterType.value, value: value.value,
  }, { uiMode: 'silent' })
  steps.value = result.data
}

onMounted(() => run(refresh))
</script>

<style scoped>
.plugin-page { display: grid; gap: 16px; }
.plugin-page .global-notice { position: static; margin: 0; }
.plugin-panel { padding: 20px; }
.plugin-heading, .plugin-row, .plugin-actions, .plugin-form {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.plugin-heading, .plugin-row { justify-content: space-between; }
.plugin-heading h2 { margin: 0; font-size: 18px; }
.plugin-row h3 { margin: 0; font-size: 15px; }
.plugin-panel p, .plugin-row small { color: var(--muted); }
.plugin-panel p { margin: 5px 0 0; overflow-wrap: anywhere; }
.plugin-list { list-style: none; margin: 14px 0 0; padding: 0; }
.plugin-row { border-top: 1px solid var(--line, #e1e8f2); padding: 14px 0 0; margin: 0 0 14px; }
.plugin-row:last-child { margin-bottom: 0; }
.plugin-issues, .plugin-steps { margin: 14px 0 0; padding-left: 24px; }
.plugin-steps li + li { margin-top: 12px; }
.plugin-form { margin-top: 16px; align-items: end; }
.plugin-form label { display: grid; gap: 6px; max-width: 100%; }
.plugin-panel .plugin-empty { margin-top: 14px; }
</style>
