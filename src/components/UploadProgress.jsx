import { AlertTriangle, CheckCircle2, FileVideo, X } from 'lucide-react'
import { formatBytes } from '../utils/mockApi.js'

export default function UploadProgress({ file, percent, uploadedBytes, status, error, onCancel }) {
  return (
    <div className="bg-stage-900 border border-stage-700 rounded-xl p-5 animate-rise">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-stage-800 flex items-center justify-center shrink-0">
          <FileVideo className="w-4 h-4 text-brass-400" strokeWidth={1.5} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm text-ink-100 truncate">{file.name}</p>
            {status === 'uploading' && (
              <button
                onClick={onCancel}
                className="text-ink-500 hover:text-ink-100 transition-colors shrink-0"
                aria-label="Cancel upload"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          <p className="text-xs text-ink-500 font-mono mt-0.5">{formatBytes(file.size)}</p>

          {status !== 'error' && (
            <div className="mt-3.5">
              <div className="h-1.5 w-full bg-stage-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-200 ${
                    status === 'success' ? 'bg-signal-green' : 'bg-brass-400'
                  }`}
                  style={{ width: `${percent}%` }}
                />
              </div>
              <div className="mt-2 flex items-center justify-between text-xs font-mono text-ink-500">
                <span>
                  {formatBytes(uploadedBytes)} / {formatBytes(file.size)}
                </span>
                <span className="flex items-center gap-1.5">
                  {status === 'success' && (
                    <CheckCircle2 className="w-3.5 h-3.5 text-signal-green" strokeWidth={2} />
                  )}
                  {status === 'success' ? 'Complete' : `${percent}%`}
                </span>
              </div>
            </div>
          )}

          {status === 'error' && (
            <div className="mt-3 flex items-center gap-2 text-signal-red text-xs bg-signal-red/10 border border-signal-red/20 rounded-lg px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
              <span>{error}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
