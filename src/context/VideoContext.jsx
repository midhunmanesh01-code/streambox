import { createContext, useContext, useEffect, useState } from 'react'
import { apiDeleteCurrentVideo, apiGetCurrentVideo ,resolveApiUrl } from '../utils/api.js'
import { useAuth } from './AuthContext.jsx'

const VideoContext = createContext(null)

export function VideoProvider({ children }) {
  const [video, setVideo] = useState(null)
  const [loading, setLoading] = useState(true)
  const { isAuthenticated, checking } = useAuth()

  const setCurrentVideo = (currentVideo) => {
    setVideo(currentVideo)
  }

  const refreshCurrentVideo = async () => {
    if (!isAuthenticated) {
      setVideo(null)
      setLoading(false)
      return null
    }

    setLoading(true)
    try {
      const result = await apiGetCurrentVideo()
      const current = result.video
      if (!current) {
        setVideo(null)
        return null
      }
      setVideo({
        id: current.id,
        title: current.title,
        originalFilename: current.original_filename,
        sizeBytes: current.size_bytes,
        uploadedAt: current.uploaded_at,
        url: resolveApiUrl(current.playback_url),
        playbackUrl: resolveApiUrl(current.playback_url),
        processingStatus: current.processing_status,
        videoCodec: current.video_codec,
        audioCodec: current.audio_codec,
        container: current.container,
        width: current.width,
        height: current.height,
        duration: current.duration,
        hasAudio: current.has_audio,
      })
      return current
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (checking) return
    refreshCurrentVideo().catch(() => {
      setVideo(null)
      setLoading(false)
    })
  }, [checking, isAuthenticated])

  const clearVideo = async () => {
    await apiDeleteCurrentVideo()
    setVideo(null)
  }

  return (
    <VideoContext.Provider value={{ video, loading, refreshCurrentVideo, clearVideo, setCurrentVideo }}>
      {children}
    </VideoContext.Provider>
  )
}

export function useVideo() {
  const ctx = useContext(VideoContext)
  if (!ctx) throw new Error('useVideo must be used within VideoProvider')
  return ctx
}
