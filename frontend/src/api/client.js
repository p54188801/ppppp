/**
 * 与后端通信的薄封装。
 *
 * 约定：后端统一返回 { ok: true, data } 或 { ok: false, error }。
 * 这里把错误转换成异常，页面只关心成功时的 data。
 */

const TOKEN_KEY = 'eduflow_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(message, code, status) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

let unauthorizedHandler = null

export function onUnauthorized(handler) {
  unauthorizedHandler = handler
}

async function parseResponse(response) {
  const text = await response.text()
  let payload = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = null
  }
  if (!response.ok || (payload && payload.ok === false)) {
    const error = payload && payload.error ? payload.error : {}
    const message = error.message || `请求失败（HTTP ${response.status}）`
    if (response.status === 401) {
      clearToken()
      if (unauthorizedHandler) unauthorizedHandler()
    }
    throw new ApiError(message, error.code || 'http_error', response.status)
  }
  return payload ? payload.data : null
}

async function request(method, path, body, options = {}) {
  const headers = { ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let payload = body
  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  const response = await fetch(path, {
    method,
    headers,
    body: payload,
    credentials: 'same-origin',
  })
  return parseResponse(response)
}

export const api = {
  get(path, params) {
    if (!params) return request('GET', path)
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.append(key, value)
    })
    const suffix = query.toString()
    return request('GET', suffix ? `${path}?${suffix}` : path)
  },
  post(path, body) {
    return request('POST', path, body)
  },
  put(path, body) {
    return request('PUT', path, body)
  },
  del(path) {
    return request('DELETE', path)
  },
  upload(path, formData) {
    return request('POST', path, formData)
  },
}

/* 常用格式化工具，页面里到处要用 */
export function formatDate(value, withTime = false) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  const base = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  if (!withTime) return base
  return `${base} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function relativeTime(value) {
  if (!value) return ''
  const date = new Date(value)
  const diff = (Date.now() - date.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  return formatDate(value)
}

export function deadlineText(value) {
  if (!value) return '长期有效'
  const date = new Date(value)
  const diff = date.getTime() - Date.now()
  if (diff < 0) return `已截止（${formatDate(value, true)}）`
  const hours = Math.floor(diff / 3600000)
  if (hours < 1) return `${Math.max(1, Math.floor(diff / 60000))} 分钟后截止`
  if (hours < 24) return `${hours} 小时后截止`
  return `${Math.floor(hours / 24)} 天后截止`
}

export function percent(value, digits = 1) {
  const number = Number(value)
  if (Number.isNaN(number)) return '0%'
  return `${number.toFixed(digits)}%`
}
