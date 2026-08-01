import { useEffect, useRef, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { formatBytes, formatDate } from '../utils/api.js'

export default function VideoPlayer({ video, onReplace, onDelete }) {
  const videoRef = useRef(null)
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(1)

  useEffect(() => {
    const element = videoRef.current
    if (!element) return
    element.muted = muted
    element.volume = volume
  }, [muted, volume])

  const handleToggleMute = () => {
    setMuted((current) => !current)
  }

  const handleVolumeChange = (event) => {
    const nextVolume = Number(event.target.value)
    setVolume(nextVolume)
    setMuted(nextVolume === 0)
  }

  return (
    <div className="animate-rise">
      <div className="relative rounded-2xl overflow-hidden border border-stage-700 shadow-glow bg-black">
        <video
          ref={videoRef}
          key={video.playbackUrl}
          src={video.playbackUrl}
          controls
          playsInline
          preload="metadata"
          className="w-full aspect-video bg-black"
        />
      </div>

      <div className="mt-3 flex items-center gap-3 text-sm text-ink-500">
        <button
          onClick={handleToggleMute}
          className="rounded-lg border border-stage-600 px-3 py-2 hover:border-brass-400/60 hover:text-brass-300 transition-colors"
        >
          {muted ? 'Unmute' : 'Mute'}
        </button>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={muted ? 0 : volume}
          onChange={handleVolumeChange}
          className="w-40 accent-brass-400"
          aria-label="Volume"
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
