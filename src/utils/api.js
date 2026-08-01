const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export const MAX_UPLOAD_BYTES = 1.5 * 1024 * 1024 * 1024

function joinUrl(path) {
  return `${API_BASE}${path}`
}

async function parseJsonResponse(response) {
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(data?.error || 'Request failed.')
  }
  return data
}

export function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '—'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  const value = bytes / Math.pow(1024, index)
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`
}

export function formatDate(date) {
  return new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(date))
}

export async function apiLogin(username, password) {
  const response = await fetch(joinUrl('/api/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ username, password }),
  })
  return parseJsonResponse(response)
}

export async function apiLogout() {
  const response = await fetch(joinUrl('/api/auth/logout'), {
    method: 'POST',
    credentials: 'include',
  })
  return parseJsonResponse(response)
}

export async function apiAuthStatus() {
  const response = await fetch(joinUrl('/api/auth/status'), {
    credentials: 'include',
  })
  return parseJsonResponse(response)
}

export async function apiGetCurrentVideo() {
  const response = await fetch(joinUrl('/api/video/current'), {
    credentials: 'include',
  })
  return parseJsonResponse(response)
}

export async function apiDeleteCurrentVideo() {
  const response = await fetch(joinUrl('/api/video'), {
    method: 'DELETE',
    credentials: 'include',
  })
  return parseJsonResponse(response)
}

export async function apiInitUpload(file) {
  const response = await fetch(joinUrl('/api/video/upload/init'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type,
    }),
  })
  return parseJsonResponse(response)
}

export function apiUploadFile(uploadUrl, file, { onProgress } = {}) {
  const xhr = new XMLHttpRequest()

  const promise = new Promise((resolve, reject) => {
    xhr.open('POST', joinUrl(uploadUrl))
    xhr.withCredentials = true
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(event.loaded, event.total)
      }
    }
    xhr.onerror = () => reject(new Error('Upload failed.'))
    xhr.onabort = () => reject(new Error('Upload canceled.'))
    xhr.onload = () => {
      try {
        const response = JSON.parse(xhr.responseText || '{}')
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(response)
        } else {
          reject(new Error(response?.error || 'Upload failed.'))
        }
      } catch {
        reject(new Error('Upload failed.'))
      }
    }
    xhr.send(file)
  })

  return {
    promise,
    cancel: () => xhr.abort(),
  }
}

export async function apiCompleteUpload(uploadSessionId) {
  const response = await fetch(joinUrl('/api/video/upload/complete'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ upload_session_id: uploadSessionId }),
  })
  return parseJsonResponse(response)
}

export async function waitForVideoReady(uploadSessionId, { intervalMs = 2000, timeoutMs = 120000 } = {}) {
  const startedAt = Date.now()
  let attempts = 0
  while (Date.now() - startedAt < timeoutMs) {
    const result = await apiCompleteUpload(uploadSessionId)
    if (result.status === 'ready' && result.video) {
      return result.video
    }
    if (result.status === 'failed') {
      throw new Error(result.video?.error_message || 'Video processing failed.')
    }
    attempts += 1
    if (attempts >= 3) {
      const current = await apiGetCurrentVideo().catch(() => null)
      if (current?.video?.processing_status === 'ready') {
        return current.video
      }
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  throw new Error('Video processing is taking longer than expected.')
}