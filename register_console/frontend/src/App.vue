<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  Bell,
  Connection,
  DataLine,
  Document,
  Download,
  Files,
  Monitor,
  Promotion,
  RefreshRight,
  Setting,
  UploadFilled,
} from '@element-plus/icons-vue'
import {
  ElMessage,
  ElMessageBox,
} from 'element-plus'
import {
  exportLogsUrl,
  getBootstrap,
  getCloudSummary,
  getFiles,
  getLogs,
  getRuntime,
  importAccounts,
  saveSettings,
  startMonitor,
  startRefill,
  startRegister,
  stopMonitor,
} from './api'

const loading = ref(true)
const saving = ref(false)
const importLoading = ref(false)
const actionLoading = ref(false)
const cloudLoading = ref(false)
const fileInput = ref(null)
const logWrap = ref(null)
const activeTab = ref('basic')
const logCursor = ref(0)
const pollTimer = ref(null)

const settings = reactive({
  output_dir: '',
  count: 20,
  threads: 3,
  server: '',
  auth_key: '',
  min_active_accounts: 60,
  monitor_interval_seconds: 300,
  upload_to_cloud: true,
  enable_flaresolverr: false,
  flaresolverr_url: '',
})

const editor = reactive({
  register_config_text: '',
  env_text: '',
})

const runtime = reactive({
  busy: false,
  monitoring: false,
  status: 'idle',
  current_task: '',
  hint: '',
  monitor_countdown_text: '未启动',
  next_check_at: '',
  progress: {
    total: 0,
    submitted: 0,
    done: 0,
    success: 0,
    fail: 0,
    running: 0,
  },
  files: [],
})

const cloud = reactive({
  valid_account_count: 0,
  healthy: false,
  status: '',
  summary: {},
})

const logs = ref([])

const statusLabel = computed(() => {
  if (runtime.monitoring) return '监控中'
  if (runtime.busy) return '执行中'
  return '空闲'
})

const progressPercent = computed(() => {
  if (!runtime.progress.total) return 0
  return Math.min(100, Math.round((runtime.progress.done / runtime.progress.total) * 100))
})

const outputFiles = computed(() => runtime.files || [])

const statCards = computed(() => [
  {
    title: '当前状态',
    value: statusLabel.value,
    meta: runtime.hint || '等待执行',
    theme: runtime.monitoring ? 'good' : runtime.busy ? 'warm' : 'calm',
    icon: Monitor,
  },
  {
    title: '注册规模',
    value: `${settings.count} / ${settings.threads}`,
    meta: '数量 / 线程',
    theme: 'calm',
    icon: DataLine,
  },
  {
    title: '监控规则',
    value: `${settings.min_active_accounts} / ${settings.monitor_interval_seconds}s`,
    meta: '阈值 / 间隔',
    theme: 'muted',
    icon: Bell,
  },
  {
    title: '云端账号',
    value: String(cloud.valid_account_count || 0),
    meta: cloud.status || '待读取',
    theme: cloud.healthy ? 'good' : 'warm',
    icon: Connection,
  },
])

function patchObject(target, payload) {
  Object.keys(target).forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(payload, key)) {
      target[key] = payload[key]
    }
  })
}

function appendLogs(items) {
  if (!Array.isArray(items) || !items.length) return
  logs.value.push(...items)
  if (logs.value.length > 500) {
    logs.value.splice(0, logs.value.length - 500)
  }
  requestAnimationFrame(() => {
    if (!logWrap.value) return
    logWrap.value.scrollTop = logWrap.value.scrollHeight
  })
}

async function bootstrap() {
  loading.value = true
  try {
    const data = await getBootstrap()
    patchObject(settings, data.settings || {})
    editor.register_config_text = data.register_config_text || ''
    editor.env_text = data.env_text || ''
    patchObject(runtime, data.runtime || {})
    runtime.progress = data.runtime?.progress || runtime.progress
    logs.value = data.logs?.items || []
    logCursor.value = data.logs?.cursor || 0
  } finally {
    loading.value = false
  }
}

async function refreshRuntime() {
  const [runtimeData, logData, fileData] = await Promise.all([
    getRuntime(),
    getLogs(logCursor.value),
    getFiles(),
  ])
  patchObject(runtime, runtimeData || {})
  runtime.progress = runtimeData?.progress || runtime.progress
  runtime.files = fileData?.items || runtimeData?.files || []
  appendLogs(logData?.items || [])
  logCursor.value = logData?.cursor || logCursor.value
}

async function refreshCloud() {
  cloudLoading.value = true
  try {
    const data = await getCloudSummary()
    cloud.valid_account_count = data.valid_account_count || 0
    cloud.healthy = !!data.healthy
    cloud.status = data.status || ''
    cloud.summary = data.summary || {}
  } catch (error) {
    handleError(error)
  } finally {
    cloudLoading.value = false
  }
}

async function saveAllSettings() {
  saving.value = true
  try {
    const data = await saveSettings({
      settings: { ...settings },
      register_config_text: editor.register_config_text,
      env_text: editor.env_text,
    })
    patchObject(settings, data.settings || {})
    editor.register_config_text = data.register_config_text || editor.register_config_text
    editor.env_text = data.env_text || editor.env_text
    ElMessage.success('配置已保存')
  } catch (error) {
    handleError(error)
  } finally {
    saving.value = false
  }
}

async function executeAction(fn, successText) {
  actionLoading.value = true
  try {
    await fn()
    ElMessage.success(successText)
    await refreshRuntime()
  } catch (error) {
    handleError(error)
  } finally {
    actionLoading.value = false
  }
}

function triggerImport() {
  fileInput.value?.click()
}

async function onFileChange(event) {
  const [file] = event.target.files || []
  event.target.value = ''
  if (!file) return
  importLoading.value = true
  try {
    await importAccounts(file)
    ElMessage.success('导入任务已启动')
    await refreshRuntime()
  } catch (error) {
    handleError(error)
  } finally {
    importLoading.value = false
  }
}

function handleError(error) {
  const message = error?.response?.data?.detail?.error
    || error?.response?.data?.error
    || error?.message
    || '操作失败'
  ElMessage.error(message)
}

async function confirmStopMonitor() {
  try {
    await ElMessageBox.confirm('停止后当前轮次结束即退出监控，是否继续？', '停止监控', {
      type: 'warning',
      confirmButtonText: '停止',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await executeAction(stopMonitor, '已请求停止监控')
}

function startPolling() {
  stopPolling()
  pollTimer.value = window.setInterval(async () => {
    try {
      await refreshRuntime()
    } catch {
      // quiet polling
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer.value) {
    window.clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

onMounted(async () => {
  try {
    await bootstrap()
    await refreshCloud()
  } catch (error) {
    handleError(error)
  } finally {
    startPolling()
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <div class="page-shell">
    <div class="hero-panel">
      <div class="hero-mark">
        <div class="hero-badge">R</div>
        <div>
          <p class="eyebrow">LOCAL REGISTER CONSOLE</p>
          <h1>本地注册容器控制台</h1>
          <p class="hero-copy">独立运行、本地保存、按云端阈值自动补号。保留简洁操作流，不去污染主站后台。</p>
        </div>
      </div>
      <div class="hero-side">
        <span :class="['status-pill', runtime.monitoring ? 'status-good' : runtime.busy ? 'status-warm' : 'status-calm']">
          {{ statusLabel }}
        </span>
        <p>{{ runtime.monitor_countdown_text }}</p>
      </div>
    </div>

    <div class="stats-grid">
      <article v-for="card in statCards" :key="card.title" :class="['stat-card', `theme-${card.theme}`]">
        <div class="stat-head">
          <component :is="card.icon" class="stat-icon" />
          <span>{{ card.title }}</span>
        </div>
        <strong>{{ card.value }}</strong>
        <p>{{ card.meta }}</p>
      </article>
    </div>

    <div class="layout-grid">
      <section class="main-panel panel-surface">
        <header class="panel-head">
          <div>
            <p class="eyebrow">CONFIG</p>
            <h2>注册配置</h2>
          </div>
          <el-button :icon="Setting" :loading="saving" type="primary" plain @click="saveAllSettings">保存配置</el-button>
        </header>

        <el-tabs v-model="activeTab" class="compact-tabs">
          <el-tab-pane label="基础设置" name="basic">
            <div class="form-grid">
              <label class="field-card">
                <span>输出目录</span>
                <el-input v-model="settings.output_dir" placeholder="/app/output" />
              </label>
              <label class="field-card">
                <span>注册数量</span>
                <el-input-number v-model="settings.count" :min="1" :max="9999" />
              </label>
              <label class="field-card">
                <span>线程数</span>
                <el-input-number v-model="settings.threads" :min="1" :max="128" />
              </label>
              <label class="field-card">
                <span>云端地址</span>
                <el-input v-model="settings.server" placeholder="https://free-api.yccc.me/" />
              </label>
              <label class="field-card">
                <span>管理员密钥</span>
                <el-input v-model="settings.auth_key" show-password placeholder="YCCC-xxxx" />
              </label>
              <label class="field-card">
                <span>最低有效账号</span>
                <el-input-number v-model="settings.min_active_accounts" :min="1" :max="9999" />
              </label>
              <label class="field-card">
                <span>监控间隔(秒)</span>
                <el-input-number v-model="settings.monitor_interval_seconds" :min="5" :max="86400" />
              </label>
              <label class="field-card">
                <span>FlareSolverr URL</span>
                <el-input v-model="settings.flaresolverr_url" placeholder="http://127.0.0.1:8191" />
              </label>
            </div>

            <div class="switch-row">
              <el-switch v-model="settings.upload_to_cloud" inline-prompt active-text="上传云端" inactive-text="仅本地" />
              <el-switch v-model="settings.enable_flaresolverr" inline-prompt active-text="FS开启" inactive-text="FS关闭" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="register.json" name="register">
            <el-input
              v-model="editor.register_config_text"
              type="textarea"
              :rows="16"
              resize="none"
              class="editor-box"
            />
          </el-tab-pane>

          <el-tab-pane label=".env" name="env">
            <el-input
              v-model="editor.env_text"
              type="textarea"
              :rows="16"
              resize="none"
              class="editor-box"
            />
          </el-tab-pane>
        </el-tabs>

        <div class="action-bar">
          <el-button :icon="Promotion" :loading="actionLoading" type="primary" @click="executeAction(startRegister, '注册任务已启动')">
            开始注册
          </el-button>
          <el-button :icon="RefreshRight" :loading="actionLoading" @click="executeAction(startRefill, '补号任务已启动')">
            检查补号
          </el-button>
          <el-button :icon="UploadFilled" :loading="importLoading" @click="triggerImport">
            导入账号文件
          </el-button>
          <el-button
            v-if="!runtime.monitoring"
            :icon="Bell"
            :loading="actionLoading"
            type="success"
            plain
            @click="executeAction(startMonitor, '循环监控已启动')"
          >
            开启监控
          </el-button>
          <el-button v-else :icon="Bell" :loading="actionLoading" type="danger" plain @click="confirmStopMonitor">
            停止监控
          </el-button>
          <el-button :icon="Connection" :loading="cloudLoading" plain @click="refreshCloud">读取云端</el-button>
          <a class="ghost-link" :href="exportLogsUrl()" target="_blank" rel="noreferrer">
            <el-button :icon="Download" plain>导出日志</el-button>
          </a>
          <input ref="fileInput" class="hidden-input" type="file" accept=".json" @change="onFileChange" />
        </div>
      </section>

      <aside class="side-panel">
        <section class="panel-surface progress-panel">
          <header class="panel-head compact">
            <div>
              <p class="eyebrow">PROGRESS</p>
              <h2>任务进度</h2>
            </div>
            <strong>{{ progressPercent }}%</strong>
          </header>
          <el-progress :percentage="progressPercent" :stroke-width="12" :show-text="false" />
          <div class="mini-grid">
            <article class="mini-card">
              <span>已完成</span>
              <strong>{{ runtime.progress.done }} / {{ runtime.progress.total }}</strong>
            </article>
            <article class="mini-card">
              <span>成功</span>
              <strong>{{ runtime.progress.success }}</strong>
            </article>
            <article class="mini-card">
              <span>失败</span>
              <strong>{{ runtime.progress.fail }}</strong>
            </article>
            <article class="mini-card">
              <span>运行中</span>
              <strong>{{ runtime.progress.running }}</strong>
            </article>
          </div>
        </section>

        <section class="panel-surface files-panel">
          <header class="panel-head compact">
            <div>
              <p class="eyebrow">OUTPUT</p>
              <h2>输出文件</h2>
            </div>
            <el-button :icon="Files" plain size="small" @click="refreshRuntime">刷新</el-button>
          </header>
          <div class="file-list">
            <article v-for="file in outputFiles" :key="file.path" class="file-item">
              <div>
                <strong>{{ file.name }}</strong>
                <p>{{ file.updated_at }}</p>
              </div>
              <span>{{ Math.max(1, Math.round(file.size / 1024)) }} KB</span>
            </article>
            <div v-if="!outputFiles.length" class="empty-note">还没有生成输出文件</div>
          </div>
        </section>
      </aside>
    </div>

    <section class="panel-surface log-panel">
      <header class="panel-head compact">
        <div>
          <p class="eyebrow">STREAM</p>
          <h2>实时日志</h2>
        </div>
        <el-button :icon="Document" plain size="small" @click="refreshRuntime">刷新日志</el-button>
      </header>
      <div ref="logWrap" class="log-stream">
        <article v-for="item in logs" :key="item.id" :class="['log-line', `level-${item.level}`]">
          <span class="log-time">{{ item.timestamp }}</span>
          <span class="log-badge">{{ item.level }}</span>
          <span class="log-message">{{ item.message }}</span>
        </article>
        <div v-if="!logs.length && !loading" class="empty-note">暂无日志输出</div>
      </div>
    </section>
  </div>
</template>
