// TEMPORARY mock layer standing in for the future Flask REST API.
// Swap these functions for real fetch() calls once the backend exists:
//   POST   /api/video/upload   (multipart, chunked/direct-to-storage)
//   DELETE /api/video
//   GET    /api/video/current
// Keep the same function signatures so components don't need to change.

export const MAX_UPLOAD_BYTES = 1.5 * 1024 * 1024 * 1024 // 1.5 GB

export function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '—'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  const value = bytes / Math.pow(1024, i)
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)} ${units[i]}`
}

export function formatDate(date) {
  return new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

/**
 * Simulates a chunked upload with progress callbacks.
 * Returns a controller so the caller can cancel the simulated upload.
 */
export function simulateUpload(file, { onProgress, onComplete, onError }) {
  if (file.size > MAX_UPLOAD_BYTES) {
    onError('This file exceeds the 1.5 GB maximum upload size.')
    return { cancel: () => {} }
  }

  let uploaded = 0
  let cancelled = false
  const total = file.size
  // Randomized chunk pacing so the progress bar feels like a real transfer.
  const tick = () => {
    if (cancelled) return
    const chunk = total * (0.03 + Math.random() * 0.07)
    uploaded = Math.min(total, uploaded + chunk)
    const percent = Math.round((uploaded / total) * 100)
    onProgress(percent, uploaded, total)

    if (uploaded >= total) {
      setTimeout(() => {
        if (!cancelled) onComplete()
      }, 300)
      return
    }
    setTimeout(tick, 180 + Math.random() * 220)
  }

  setTimeout(tick, 250)

  return {
    cancel: () => {
      cancelled = true
    },
  }
}
