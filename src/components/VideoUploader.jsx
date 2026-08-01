import { useCallback, useRef, useState } from 'react'
import { UploadCloud } from 'lucide-react'
import UploadProgress from './UploadProgress.jsx'
import { MAX_UPLOAD_BYTES, formatBytes, simulateUpload } from '../utils/mockApi.js'

export default function VideoUploader({ onUploadComplete, autoOpen }) {
  const inputRef = useRef(null)
  const controllerRef = useRef(null)

  const [isDragging, setIsDragging] = useState(false)
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState('idle') // idle | uploading | success | error
  const [percent, setPercent] = useState(0)
  const [uploadedBytes, setUploadedBytes] = useState(0)
  const [error, setError] = useState('')

  const startUpload = useCallback((selected) => {
    if (!selected) return

    if (selected.size > MAX_UPLOAD_BYTES) {
      setFile(selected)
      setStatus('error')
      setError('This file exceeds the 1.5 GB maximum upload size.')
      return
    }

    setFile(selected)
    setStatus('uploading')
    setPercent(0)
    setUploadedBytes(0)
    setError('')

    controllerRef.current = simulateUpload(selected, {
      onProgress: (pct, uploaded) => {
        setPercent(pct)
        setUploadedBytes(uploaded)
      },
      onComplete: () => {
        setStatus('success')
        setTimeout(() => onUploadComplete(selected), 500)
      },
      onError: (message) => {
        setStatus('error')
        setError(message)
      },
    })
  }, [onUploadComplete])

  const handleCancel = () => {
    controllerRef.current?.cancel()
    setFile(null)
    setStatus('idle')
  }

  const handleFileInput = (e) => {
    const selected = e.target.files?.[0]
    if (selected) startUpload(selected)
    e.target.value = ''
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    const dropped = e.dataTransfer.files?.[0]
    if (dropped) startUpload(dropped)
  }

  if (file && status !== 'idle') {
    return (
      <div className="space-y-3">
        <UploadProgress
          file={file}
          percent={percent}
          uploadedBytes={uploadedBytes}
          status={status}
          error={error}
          onCancel={handleCancel}
        />
        {status === 'error' && (
          <button
            onClick={handleCancel}
            className="text-sm text-brass-400 hover:text-brass-300 transition-colors"
          >
            Choose a different file
          </button>
        )}
      </div>
    )
  }

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={handleFileInput}
        autoFocus={autoOpen}
      />
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragging(true)
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-2xl border-2 border-dashed transition-colors px-6 py-14 flex flex-col items-center justify-center text-center ${
          isDragging
            ? 'border-brass-400 bg-brass-400/5'
            : 'border-stage-600 hover:border-stage-500 bg-stage-900/40'
        }`}
      >
        <div className="w-12 h-12 rounded-full bg-stage-800 flex items-center justify-center mb-4">
          <UploadCloud className="w-5 h-5 text-brass-400" strokeWidth={1.5} />
        </div>
        <p className="text-ink-100 font-medium">Drag and drop a video, or click to browse</p>
        <p className="text-ink-500 text-sm mt-2">Maximum video size: {formatBytes(MAX_UPLOAD_BYTES)}</p>
      </div>
    </div>
  )
}
