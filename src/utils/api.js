const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export const MAX_UPLOAD_BYTES = 1.5 * 1024 * 1024 * 1024

function joinUrl(path) {
  return `${API_BASE}${path}`
}

export function resolveApiUrl(path) {
  if (!path) return null
  if (/^https?:\/\//i.test(path)) return path
  return joinUrl(path)
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

async function apiMultipartPartUrls(uploadSessionId, partNumbers) {
  const response = await fetch(joinUrl(`/api/video/upload/multipart/${uploadSessionId}/parts`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ part_numbers: partNumbers }),
  })
  return parseJsonResponse(response)
}

export async function apiCompleteMultipartUpload(uploadSessionId) {
  const response = await fetch(joinUrl(`/api/video/upload/multipart/${uploadSessionId}/complete`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })
  return parseJsonResponse(response)
}

export async function apiAbortMultipartUpload(uploadSessionId) {
  const response = await fetch(joinUrl(`/api/video/upload/multipart/${uploadSessionId}/abort`), {
    method: 'POST',
    credentials: 'include',
  })
  return parseJsonResponse(response)
}

function uploadPart(url, blob, onProgress, activeRequests) {
  const xhr = new XMLHttpRequest()
  const promise = new Promise((resolve, reject) => {
    xhr.open('PUT', url)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded)
    }
    xhr.onerror = () => reject(new Error('Part upload failed.'))
    xhr.onabort = () => reject(new Error('Upload canceled.'))
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve()
      else reject(new Error(`Part upload failed (${xhr.status}).`))
    }
    xhr.send(blob)
  })
  activeRequests.add(xhr)
  return promise.finally(() => activeRequests.delete(xhr))
}

// Direct-to-B2 uploads deliberately use a small worker pool. Progress includes
// completed parts plus bytes currently sent by all active parts.
export function apiUploadMultipart(uploadSession, file, { onProgress } = {}) {
  const activeRequests = new Set()
  const activeBytes = new Map()
  let completedBytes = 0
  let canceled = false
  const partSize = uploadSession.part_size_bytes
  const partCount = uploadSession.part_count

  const reportProgress = () => {
    const inFlight = [...activeBytes.values()].reduce((total, bytes) => total + bytes, 0)
    onProgress?.(Math.min(file.size, completedBytes + inFlight), file.size)
  }

  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))
  const uploadOnePart = async (partNumber) => {
    const start = (partNumber - 1) * partSize
    const blob = file.slice(start, Math.min(file.size, start + partSize))
    let lastError
    for (let attempt = 0; attempt < 4; attempt += 1) {
      if (canceled) throw new Error('Upload canceled.')
      activeBytes.set(partNumber, 0)
      reportProgress()
      try {
        const urlResult = await apiMultipartPartUrls(uploadSession.upload_session_id, [partNumber])
        await uploadPart(urlResult.parts[0].url, blob, (loaded) => {
          activeBytes.set(partNumber, loaded)
          reportProgress()
        }, activeRequests)
        activeBytes.delete(partNumber)
        completedBytes += blob.size
        reportProgress()
        return
      } catch (error) {
        lastError = error
        activeBytes.delete(partNumber)
        reportProgress()
        if (canceled) throw new Error('Upload canceled.')
        if (attempt < 3) await wait(500 * (2 ** attempt))
      }
    }
    throw lastError || new Error('Part upload failed.')
  }

  const promise = (async () => {
    let nextPart = 1
    const worker = async () => {
      while (!canceled) {
        const partNumber = nextPart
        nextPart += 1
        if (partNumber > partCount) return
        await uploadOnePart(partNumber)
      }
    }
    try {
      await Promise.all(Array.from({ length: Math.min(3, partCount) }, worker))
      if (canceled) throw new Error('Upload canceled.')
      return apiCompleteMultipartUpload(uploadSession.upload_session_id)
    } catch (error) {
      if (!canceled) apiAbortMultipartUpload(uploadSession.upload_session_id).catch(() => {})
      throw error
    }
  })()

  return {
    promise,
    cancel: () => {
      canceled = true
      activeRequests.forEach((xhr) => xhr.abort())
      apiAbortMultipartUpload(uploadSession.upload_session_id).catch(() => {})
    },
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

export async function waitForVideoReady(uploadSessionId, { intervalMs = 2000, timeoutMs = 120000, targetVideoId } = {}) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const result = await apiCompleteUpload(uploadSessionId)
    if (result.status === 'ready' && result.video) {
      if (!targetVideoId || result.video.id === targetVideoId) {
        return result.video
      }
    }
    if (result.status === 'failed') {
      throw new Error(result.video?.error_message || 'Video processing failed.')
    }
    if (targetVideoId) {
      const current = await apiGetCurrentVideo().catch(() => null)
      if (current?.video?.id === targetVideoId && current?.video?.processing_status === 'ready') {
        return current.video
      }
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  throw new Error('Video processing is taking longer than expected.')
}

export async function apiRequestTranscode(videoId) {
  const response = await fetch(joinUrl(`/api/video/${videoId}/transcode`), {
    method: 'POST',
    credentials: 'include',
  })
  return parseJsonResponse(response)
}

export async function apiGetVideo(videoId) {
  const response = await fetch(joinUrl(`/api/video/current`), {
    credentials: 'include',
  })
  return parseJsonResponse(response)
}
