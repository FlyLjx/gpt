import axios from 'axios'

const api = axios.create({
  baseURL: '',
  timeout: 30000,
})

export async function getBootstrap() {
  const { data } = await api.get('/api/bootstrap')
  return data
}

export async function saveSettings(payload) {
  const { data } = await api.put('/api/settings', payload)
  return data
}

export async function getRuntime() {
  const { data } = await api.get('/api/runtime')
  return data
}

export async function getLogs(cursor = 0) {
  const { data } = await api.get('/api/logs', { params: { cursor } })
  return data
}

export async function getFiles() {
  const { data } = await api.get('/api/files')
  return data
}

export async function getCloudSummary() {
  const { data } = await api.get('/api/cloud-summary')
  return data
}

export async function startRegister() {
  const { data } = await api.post('/api/actions/register')
  return data
}

export async function startRefill() {
  const { data } = await api.post('/api/actions/refill')
  return data
}

export async function startMonitor() {
  const { data } = await api.post('/api/actions/monitor/start')
  return data
}

export async function stopMonitor() {
  const { data } = await api.post('/api/actions/monitor/stop')
  return data
}

export async function importAccounts(file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post('/api/actions/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export function exportLogsUrl() {
  return '/api/logs/export'
}
