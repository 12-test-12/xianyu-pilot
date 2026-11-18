<template>
  <div class="plugin-page" :aria-busy="busy">
    <p v-if="error" class="global-notice error" role="alert">{{ error }}</p>
    <p v-if="notice" class="global-notice success" role="status">{{ notice }}</p>
    <section class="card-panel plugin-panel" aria-labelledby="available-plugins">
      <header class="plugin-heading">
        <div>
          <h2 id="available-plugins">可用插件</h2>
          <p>可离线安装程序自带的预演版，也可导入已签名的插件包。</p>
        </div>
        <div class="plugin-actions">
          <AppButton :disabled="busy" @click="openPicker($event, zipPicker)">安装 ZIP</AppButton>
          <AppButton :disabled="busy" @click="openPicker($event, folderPicker)">安装文件夹</AppButton>
          <AppButton :disabled="busy" @click="run(refresh)">刷新</AppButton>
        </div>
      </header>
      <input ref="zipPicker" type="file" accept=".zip,application/zip" aria-label="选择 ZIP 插件包" hidden @change="selectPackage($event, false)">
      <input ref="folderPicker" type="file" webkitdirectory aria-label="选择插件文件夹" hidden @change="selectPackage($event, true)">
      <p v-if="data?.publisherIssue" class="global-notice warn" role="status">{{ data.publisherIssue }}</p>
      <p v-if="data?.catalogIssue" class="global-notice warn" role="status">{{ data.catalogIssue }}</p>
      <ul v-if="data?.available.length" class="plugin-list">
        <li v-for="item in data.available" :key="item.id" class="plugin-row">
          <div>
            <h3>{{ item.name }} <small>v{{ item.version }}</small></h3>
            <p>{{ item.description }}</p>
            <p>支持{{ item.parameterTypes.map(type => parameterLabels[type] || type).join('、') }}。可批量预演并通过已绑定的 QQ 发送。</p>
          </div>
          <div class="plugin-actions">
            <Badge v-if="isInstalled(item)" type="green">已安装</Badge>
            <AppButton v-else type="primary" :disabled="busy" @click="installBundled(item)">安装预演版</AppButton>
          </div>
        </li>
      </ul>
      <p v-else-if="!data && busy" role="status">正在读取插件目录…</p>
    </section>
    <section class="card-panel plugin-panel" aria-labelledby="installed-plugins">
      <header class="plugin-heading">
        <div>
          <h2 id="installed-plugins">已安装</h2>
          <p>手动复制到插件目录的版本，点「刷新」后即可核对并启用。</p>
        </div>
      </header>
      <p v-if="data && !data.installed.length" class="plugin-empty">还没有通过校验的插件。安装后可在这里启用并运行预演。</p>
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
    <PluginQqConnection
      v-model:profiles="qqProfiles" v-model:selected-ids="selectedProfileIds"
      v-model:bound-accounts="boundAccounts" :locked="busy"
    />
    <section v-if="selected" class="card-panel plugin-panel" aria-labelledby="plugin-preview">
      <header class="plugin-heading">
        <div>
          <h2 id="plugin-preview" ref="previewHeading" tabindex="-1">{{ selected.name }} · 指令预演</h2>
          <p>每行输入一个目标。球球号可直接生成助力指令。</p>
        </div>
      </header>
      <form class="plugin-form" @submit.prevent="run(preview)">
        <fieldset class="plugin-parameter-types">
          <legend>参数类型</legend>
          <label v-for="type in selected.parameterTypes" :key="type">
            <input v-model="parameterType" type="radio" name="preview-parameter" :value="type" :disabled="busy" @change="groups = []">
            <span>{{ parameterLabels[type] || type }}</span>
          </label>
        </fieldset>
        <label>助力目标（每行一个，最多 50 个）
          <textarea v-model="value" class="input" rows="3" maxlength="25050" required :disabled="busy" @input="groups = []" />
        </label>
        <AppButton type="primary" native-type="submit" :disabled="busy">运行预演</AppButton>
      </form>
      <div aria-live="polite">
        <div v-if="groups.length" class="batch-select-actions">
          <AppButton size="small" :disabled="busy" @click="selectAllTargets">全选目标</AppButton>
          <AppButton size="small" :disabled="busy" @click="deselectAllTargets">取消全选</AppButton>
          <span>已勾选 {{ selectedValues.length }} / {{ groups.length }} 个目标</span>
        </div>
        <ol v-if="groups.length" class="plugin-steps">
          <li v-for="(group, groupIndex) in groups" :key="group.value">
            <div class="plugin-actions">
              <label class="target-choice"><input v-model="selectedValues" type="checkbox" :value="group.value" :disabled="busy">{{ group.value }}</label>
              <label v-if="chosenProfiles.length" class="route-choice">发送账号和机器人
                <select class="input" :value="routeFor(group, groupIndex)?.id" :disabled="busy" @change="assignments[group.value] = Number($event.target.value)">
                  <option v-for="profile in chosenProfiles" :key="profile.id" :value="profile.id">{{ profileLabel(profile) }}</option>
                </select>
              </label>
            </div>
            <div v-for="(step, index) in group.steps" :key="index">
              <p>{{ step.title }} · {{ step.command || '收到可核对的全服排名后生成指令' }}</p>
              <div v-if="step.command" class="plugin-actions draft-actions">
                <span v-if="sendResults[stepKey(group, index)]">{{ sendStateLabels[sendResults[stepKey(group, index)]] }} · {{ profileLabel(attemptedTargets[stepKey(group, index)]) }}</span>
                <AppButton v-if="routeFor(group, groupIndex)" :disabled="busy || !!sendResults[stepKey(group, index)]" @click="run(() => fillQqDraft(group, index, routeFor(group, groupIndex)))">填入 QQ 草稿</AppButton>
                <AppButton :disabled="busy" @click="run(() => copyCommand(step.command))">复制指令</AppButton>
                <AppButton v-if="sendResults[stepKey(group, index)] === 'uncertain'" :disabled="busy" @click="run(() => checkSend(group, index))">查询发送状态</AppButton>
                <AppButton v-if="sendResults[stepKey(group, index)] === 'uncertain'" :disabled="busy" @click="run(() => resetSend(group, index))">确认未发送</AppButton>
              </div>
            </div>
          </li>
        </ol>
      </div>
      <div v-if="groups.length" class="plugin-actions draft-actions">
        <AppButton type="primary" :disabled="busy || !queued.length || missingWindows.length > 0" @click="run(sendBatch)">自动发送所选指令（{{ queued.length }}）</AppButton>
        <span v-if="!chosenProfiles.length">请先勾选要用的 QQ 配置。</span>
        <span v-else-if="missingWindows.length">请先绑定发送账号 {{ missingWindows.join('、') }} 的 QQ 窗口。</span>
      </div>
      <p v-if="draftNotice" role="status">{{ draftNotice }}</p>
      <p v-if="draftError" role="alert" class="draft-error">{{ draftError }}</p>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import AppButton from '../components/AppButton.vue'
import Badge from '../components/Badge.vue'
import PluginQqConnection from '../components/PluginQqConnection.vue'
import { copyText } from '../utils/clipboard.js'
import { confirmAction } from '../utils/confirmAction.js'
import { createSecureId } from '../utils/secureId.js'
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
const groups = ref([])
const qqProfiles = ref([])
const selectedProfileIds = ref([])
const boundAccounts = ref([])
const selectedValues = ref([])
const assignments = ref(Object.create(null))
const sendResults = ref({})
const attemptedTargets = ref({})
const attemptedIds = ref({})
const sendStateLabels = {
  submitted: 'QQ 已提交', receipt_success: '助力已完成', receipt_capped: '助力已达上限', uncertain: '发送暂停，待核查',
}
const chosenProfiles = computed(() => qqProfiles.value.filter(profile => selectedProfileIds.value.includes(profile.id)))
const checkedTargets = computed(() => groups.value.filter(group => selectedValues.value.includes(group.value)).map(group => group.value))
const queued = computed(() => groups.value.flatMap((group, groupIndex) => {
  const target = routeFor(group, groupIndex)
  if (!target || !selectedValues.value.includes(group.value)) return []
  return group.steps.flatMap((step, stepIndex) => {
    const key = stepKey(group, stepIndex)
    return step.command && !sendResults.value[key] ? [{ key, target, value: group.value, stepIndex }] : []
  })
}))
const missingWindows = computed(() => [...new Set(queued.value.map(item => item.target.qqAccount))]
  .filter(account => !boundAccounts.value.includes(account)).map(account => account || '未填写发送账号'))
const draftNotice = ref('')
const draftError = ref('')
const pathFor = item => `${endpoint}/${item.id}/${item.version}`
const isInstalled = item => data.value.installed.some(plugin => pathFor(plugin) === pathFor(item))
let packageButton

async function run(action, trigger = document.activeElement) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  draftNotice.value = ''
  draftError.value = ''
  try {
    await action()
  } catch (err) {
    error.value = err?.message || '插件操作失败，请重试。'
  } finally {
    busy.value = false
    await nextTick()
    if (document.activeElement === document.body && trigger instanceof HTMLButtonElement) {
      if (trigger.isConnected && !trigger.disabled) trigger.focus()
      else previewHeading.value?.focus()
    }
  }
}

async function refresh() {
  try {
    const { data: status } = await request.get(endpoint, { uiMode: 'silent' })
    if (!Array.isArray(status?.available) || !Array.isArray(status?.installed)
      || !Array.isArray(status?.issues) || status.available.some(item => !Array.isArray(item.parameterTypes))) {
      throw new Error('请更新或重新启动闲鱼助手桌面版。')
    }
    data.value = status
  } catch (err) {
    throw new Error(`无法读取本机插件状态。${err?.message || '请刷新重试。'}`, { cause: err })
  }
  if (selected.value && !data.value.installed.some(item => item.enabled && pathFor(item) === pathFor(selected.value))) {
    selected.value = null
    groups.value = []
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
    await confirmInstall(item, () => request.post(`${endpoint}/package`, payload, config))
  }, packageButton)
}

async function confirmInstall(item, install) {
  if (!await confirmAction({
    title: `安装 ${item.name} v${item.version}`,
    description: `${item.description}\n安装后可在「已安装」中启用。`,
    confirmText: '安装插件',
  })) return
  await install()
  await refresh()
  notice.value = `${item.name} v${item.version} 已安装。`
}

function installBundled(item) {
  return run(() => confirmInstall(item, () => request.post(
    `${endpoint}/catalog/${item.id}/install`, null, { uiMode: 'silent' },
  )))
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
  parameterType.value = item.parameterTypes.includes('number') ? 'number' : item.parameterTypes[0]
  value.value = ''
  groups.value = []
  await nextTick()
  previewHeading.value?.focus()
}

async function preview() {
  groups.value = []
  const path = pathFor(selected.value)
  const rawValues = value.value
  const values = [...new Set(rawValues.split(/\r?\n/).map(item => item.trim()).filter(Boolean))]
  if (!values.length || values.length > 50 || values.some(item => item.length > 500)) {
    throw new Error('请输入 1 至 50 个目标，每行最多 500 个字符。')
  }
  const input = { parameterType: parameterType.value, values }
  const result = await request.post(`${path}/preview-batch`, input, { uiMode: 'silent' })
  if (selected.value && pathFor(selected.value) === path &&
      parameterType.value === input.parameterType && value.value === rawValues) {
    groups.value = result.data
    selectedValues.value = groups.value.map(group => group.value)
    assignments.value = Object.create(null)
  }
}

function profileLabel(profile) {
  return `${profile.qqAccount || '当前 QQ'} → ${profile.robotName || profile.robotQq}${profile.backup ? '（备用）' : ''}`
}

function routeFor(group, index) {
  const profiles = chosenProfiles.value
  if (!profiles.length) return null
  if (assignments.value[group.value]) {
    const assigned = profiles.find(profile => profile.id === assignments.value[group.value])
    if (assigned) return assigned
  }
  const primaries = profiles.filter(profile => !profile.backup)
  const pool = primaries.length ? primaries : profiles
  const checkedIndex = checkedTargets.value.indexOf(group.value)
  const defaultIndex = checkedIndex < 0 ? index : checkedIndex
  return pool[defaultIndex % pool.length]
}

function selectAllTargets() {
  selectedValues.value = groups.value.map(group => group.value)
}

function deselectAllTargets() {
  selectedValues.value = []
}

function stepKey(group, index) {
  return JSON.stringify([pathFor(selected.value), parameterType.value, group.value, index, group.steps[index].command])
}

function removeCompletedTargets() {
  const completed = groups.value.filter(group => group.steps.length &&
    group.steps.every((step, index) => step.command && sendResults.value[stepKey(group, index)] === 'receipt_success'))
  if (!completed.length) return

  const targets = new Set(completed.map(group => group.value))
  groups.value = groups.value.filter(group => !targets.has(group.value))
  selectedValues.value = selectedValues.value.filter(target => !targets.has(target))
  value.value = value.value.split(/\r?\n/).filter(line => !targets.has(line.trim())).join('\n')
  for (const group of completed) {
    delete assignments.value[group.value]
    for (const index of group.steps.keys()) {
      const key = stepKey(group, index)
      delete sendResults.value[key]
      delete attemptedTargets.value[key]
      delete attemptedIds.value[key]
    }
  }
  draftNotice.value += ` 已从清单移除 ${completed.length} 个完成目标。`
}

async function fillQqDraft(group, stepIndex, target) {
  draftError.value = ''
  draftNotice.value = '正在打开 QQ。如果没有自动切换，请从任务栏切到要使用的 QQ 主窗口。'
  try {
    await request.post(`${pathFor(selected.value)}/qq-draft`, {
      parameterType: parameterType.value, value: group.value, stepIndex, target,
    }, { uiMode: 'silent' })
    draftNotice.value = '指令已填入 QQ 输入框。请核对当前登录的 QQ 和机器人好友，再手动发送。'
  } catch (err) {
    draftNotice.value = ''
    draftError.value = err?.message || '无法确认 QQ 草稿是否已填入。请先查看 QQ 输入框。'
    throw err
  }
}

async function sendBatch() {
  const batch = queued.value
  if (!batch.length || missingWindows.value.length) return
  if (!await confirmAction({
    title: `通过 QQ 自动发送 ${batch.length} 条指令？`,
    description: '每条指令按清单里为它选定的发送账号和机器人提交。出现异常时队列会暂停。',
    confirmText: '开始发送',
  })) return
  const path = pathFor(selected.value)
  let sent = 0
  let completed = 0
  let capped = 0
  for (const { key, target, value, stepIndex } of batch) {
    const attemptId = createSecureId('qq-send')
    attemptedTargets.value[key] = target
    attemptedIds.value[key] = attemptId
    draftNotice.value = `正在发送第 ${sent + 1} / ${batch.length} 条 · ${profileLabel(target)}。如果没有自动切换，请切到发送账号的 QQ 主窗口。`
    let state
    try {
      const res = await request.post(`${path}/qq-send`, {
        parameterType: parameterType.value, target, value, stepIndex, attemptId,
      }, { timeout: 40000, uiMode: 'silent', suppressGlobalError: true })
      state = res.data?.state
      if (!sendStateLabels[state]) throw new Error('无法确认发送结果。')
    } catch (err) {
      sendResults.value[key] = 'uncertain'
      draftNotice.value = `已提交 ${sent} 条。请查询出错这条的发送状态或核对 QQ 聊天记录。`
      draftError.value = err?.message || '无法确认发送结果。'
      removeCompletedTargets()
      return
    }
    sendResults.value[key] = state
    completed += Number(state === 'receipt_success')
    capped += Number(state === 'receipt_capped')
    sent += 1
  }
  draftNotice.value = `QQ 已提交 ${sent} 条。助力完成 ${completed} 条，达到上限 ${capped} 条，待查看回执 ${sent - completed - capped} 条。`
  removeCompletedTargets()
}

async function checkSend(group, index) {
  const key = stepKey(group, index)
  const { data } = await request.get(`${endpoint}/qq-send/attempts/${attemptedIds.value[key]}`, { uiMode: 'silent' })
  if (sendStateLabels[data.state]) {
    sendResults.value[key] = data.state
    draftNotice.value = `本次发送状态为「${sendStateLabels[data.state]}」。`
    removeCompletedTargets()
  } else {
    draftNotice.value = data.state === 'sending'
      ? '发送仍在处理或上次未正常结束。请稍后再查，或核对 QQ 聊天记录。'
      : '未找到已提交记录。请先核对 QQ 聊天记录，再决定是否重试。'
  }
}

async function resetSend(group, index) {
  if (!await confirmAction({ title: '确认 QQ 聊天记录没有这条指令？', description: '确认后这条指令可以重新加入发送清单。', confirmText: '确认未发送' })) return
  const key = stepKey(group, index)
  await request.post(`${pathFor(selected.value)}/qq-send/clear`, {
    parameterType: parameterType.value, value: group.value, stepIndex: index, target: attemptedTargets.value[key],
    attemptId: attemptedIds.value[key],
  }, { uiMode: 'silent', suppressGlobalError: true })
  delete attemptedTargets.value[key]
  delete attemptedIds.value[key]
  delete sendResults.value[key]
}

async function copyCommand(command) {
  if (!await copyText(command)) throw new Error('无法复制，请选中指令文字手动复制。')
  draftNotice.value = '指令已复制。可在机器人 QQ 私聊中粘贴。'
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
.draft-actions { margin-top: 8px; }
.draft-actions span { color: var(--muted); }
.target-choice, .route-choice { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; overflow-wrap: anywhere; }
.draft-error { color: #b42318; margin-top: 8px; }
.plugin-form { margin-top: 16px; align-items: end; }
.plugin-form label { display: grid; gap: 6px; max-width: 100%; }
.plugin-parameter-types { display: flex; flex-wrap: wrap; gap: 6px; border: 0; margin: 0; padding: 0; min-width: 0; }
.plugin-parameter-types legend { padding: 0; margin-bottom: 6px; }
.plugin-parameter-types label { display: flex; align-items: center; min-height: 36px; padding: 0 8px; border: 1px solid var(--line); border-radius: 8px; cursor: pointer; }
.plugin-parameter-types input { margin: 0; accent-color: var(--primary); }
.plugin-parameter-types label:focus-within { outline: 2px solid var(--primary); outline-offset: 2px; }
.batch-select-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; margin-bottom: 8px; font-size: 13px; color: var(--muted); }
.plugin-panel .plugin-empty { margin-top: 14px; }
</style>
