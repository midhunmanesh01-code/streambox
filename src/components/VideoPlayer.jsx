import { useEffect, useRef, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { formatBytes, formatDate, apiRequestTranscode, apiGetCurrentVideo, resolveApiUrl } from '../utils/api.js'

export default function VideoPlayer({ video, onReplace, onDelete, onVideoUpdate }) {
  const videoRef = useRef(null)
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(1)
  const [transcoding, setTranscoding] = useState(false)

  useEffect(() => {
    const element = videoRef.current
    if (!element) return
    element.muted = muted
    element.volume = volume
  }, [muted, volume])

  // Reset transcoding state when the video changes.
  useEffect(() => {
    setTranscoding(false)
  }, [video?.id])

  const handleToggleMute = () => {
    setMuted((current) => !current)
  }

  const handleVolumeChange = (event) => {
    const nextVolume = Number(event.target.value)
    setVolume(nextVolume)
    setMuted(nextVolume === 0)
  }

  const handleVideoError = async () => {
    if (transcoding || !video?.id) return
    // Only kick off transcoding once per video; ignore transient network errors.
    const element = videoRef.current
    if (element && element.error && element.error.code === MediaError.MEDIA_ERR_NETWORK) return
    setTranscoding(true)
    try {
      await apiRequestTranscode(video.id)
      // Poll until the transcoded playback file is ready.
      const started = Date.now()
      while (Date.now() - started < 300_000) {
        await new Promise((r) => setTimeout(r, 3000))
        const result = await apiGetCurrentVideo().catch(() => null)
        const updated = result?.video
        if (updated && updated.processing_status === 'ready' && updated.playback_url) {
          onVideoUpdate?.({
            id: updated.id,
            title: updated.title,
            originalFilename: updated.original_filename,
            sizeBytes: updated.size_bytes,
            uploadedAt: updated.uploaded_at,
            url: resolveApiUrl(updated.playback_url),
            playbackUrl: resolveApiUrl(updated.playback_url),
            processingStatus: updated.processing_status,
            videoCodec: updated.video_codec,
            audioCodec: updated.audio_codec,
            container: updated.container,
            width: updated.width,
            height: updated.height,
            duration: updated.duration,
            hasAudio: updated.has_audio,
          })
          return
        }
        if (updated?.processing_status === 'failed') return
      }
    } catch {
      // Silently ignore — the user can replace the video if it truly can't play.
    } finally {
      setTranscoding(false)
    }
  }

  return (
    <div className="animate-rise">
      <div className="relative rounded-2xl overflow-hidden border border-stage-700 shadow-glow bg-black">
        {transcoding && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/70 z-10 text-sm text-ink-300">
            Preparing browser-compatible version…
          </div>
        )}
        <video
          ref={videoRef}
          key={video.playbackUrl}
          src={video.playbackUrl}
          controls
          playsInline
          preload="metadata"
          className="w-full aspect-video bg-black"
          onError={handleVideoError}
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
