import { RefreshCw, Trash2 } from 'lucide-react'
import { formatBytes, formatDate } from '../utils/mockApi.js'

export default function VideoPlayer({ video, onReplace, onDelete }) {
  return (
    <div className="animate-rise">
      <div className="relative rounded-2xl overflow-hidden border border-stage-700 shadow-glow bg-black">
        <video
          key={video.url}
          src={video.url}
          controls
          className="w-full aspect-video bg-black"
        />
      </div>

      <div className="mt-5 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-display text-xl md:text-2xl text-ink-100 truncate">{video.title}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-500 font-mono">
            <span>{formatBytes(video.sizeBytes)}</span>
            <span className="w-1 h-1 rounded-full bg-stage-600" />
            <span>Uploaded {formatDate(video.uploadedAt)}</span>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onReplace}
            className="flex items-center gap-2 text-sm border border-stage-600 hover:border-brass-400/60 hover:text-brass-300 text-ink-300 rounded-lg px-4 py-2 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" strokeWidth={2} />
            Replace Video
          </button>
          <button
            onClick={onDelete}
            className="flex items-center gap-2 text-sm border border-stage-600 hover:border-signal-red/60 hover:text-signal-red text-ink-300 rounded-lg px-4 py-2 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" strokeWidth={2} />
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}
